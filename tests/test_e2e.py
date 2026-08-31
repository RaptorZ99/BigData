"""Tests d'intégration : invariants de l'entrepôt après un run complet.

Ces tests vérifient que les chiffres produits sont exactement ceux attendus des
données du CHU — c'est la garantie que les indicateurs sont reproductibles et
qu'une régression de la logique de transformation serait détectée.

Prérequis : `make up && make pipeline`.
Lancement : `make test-e2e`.
"""

from __future__ import annotations

import pytest

from eds.config import load_config
from eds.transform import missing_tables
from eds.warehouse import connect, count_rows, scalar

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def client(config):
    return connect(config)


# ── Volumétrie attendue, couche par couche ──────────────────────────────────
# Ces valeurs découlent des trois jours de dépôt fournis et des règles qualité.
# Les faire évoluer suppose d'expliquer pourquoi : c'est le but.

BRONZE_ATTENDU = {
    "patients": 16_200,  # fichiers cumulatifs : 4 800 + 5 400 + 6 000
    "sejours": 15_000,
    "diagnostics": 37_380,
    "monitoring": 66_677,
}

SILVER_ATTENDU = {
    "dim_patient": 6_000,  # 16 200 lignes → 6 000 patients distincts
    "fact_sejour": 14_864,  # 15 000 - 136 séjours incohérents
    "sejours_rejets": 136,
    "fact_diagnostic": 37_040,  # 37 380 - 340 en cascade
    "fact_monitoring": 64_799,  # 66 677 - 1 878 rejets
    "monitoring_rejets": 1_878,  # 1 369 hors plage + 520 cascade - 11 cumulés
}


@pytest.mark.parametrize(("table", "attendu"), BRONZE_ATTENDU.items())
def test_volumetrie_bronze(client, table, attendu):
    assert count_rows(client, "eds_bronze", table) == attendu


@pytest.mark.parametrize(("table", "attendu"), SILVER_ATTENDU.items())
def test_volumetrie_silver(client, table, attendu):
    assert count_rows(client, "eds_silver", table) == attendu


def test_toutes_les_tables_attendues_existent(client):
    assert missing_tables(client) == []


# ── Règles qualité ──────────────────────────────────────────────────────────
def test_aucun_sejour_conserve_avec_sortie_avant_admission(client):
    """Q2 : la règle qui motive les 136 rejets doit être sans exception."""
    restants = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_sejour "
        "WHERE discharge_ts IS NOT NULL AND discharge_ts < admission_ts",
    )
    assert restants == 0


def test_les_sejours_en_cours_sont_conserves(client):
    """Q3 : une sortie non renseignée est un cas métier, pas une anomalie."""
    assert scalar(client, "SELECT countIf(is_ongoing) FROM eds_silver.fact_sejour") == 1_190


def test_aucune_constante_hors_plage_physiologique(client):
    """Q4 : bornes FC 20-250, SpO2 50-100, température 30-45."""
    restants = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_monitoring "
        "WHERE heart_rate NOT BETWEEN 20 AND 250 "
        "   OR spo2 NOT BETWEEN 50 AND 100 "
        "   OR temp_c NOT BETWEEN 30 AND 45",
    )
    assert restants == 0


def test_chaque_rejet_porte_un_motif(client):
    """On n'écarte jamais une ligne sans dire pourquoi."""
    for table in ("sejours_rejets", "monitoring_rejets"):
        sans_motif = scalar(client, f"SELECT countIf(reject_reason = '') FROM eds_silver.{table}")
        assert sans_motif == 0, table


def test_flag_admission_post_deces(client):
    """Q7 : anomalie signalée, pas rejetée."""
    flags = scalar(client, "SELECT countIf(is_post_mortem_anomaly) FROM eds_silver.fact_sejour")
    assert flags == 192


def test_aucun_releve_posterieur_a_la_sortie(client):
    """Q8 : contrôle actif — ces relevés appartenaient aux séjours incohérents."""
    assert scalar(client, "SELECT countIf(is_after_discharge) FROM eds_silver.fact_monitoring") == 0


# ── Intégrité de la constellation ───────────────────────────────────────────
def test_integrite_referentielle_des_faits(client):
    """Chaque fait pointe vers des dimensions existantes."""
    orphelins = {
        "fact_sejour → dim_patient": (
            "SELECT count() FROM eds_silver.fact_sejour "
            "WHERE patient_pseudo NOT IN (SELECT patient_pseudo FROM eds_silver.dim_patient)"
        ),
        "fact_sejour → dim_service": (
            "SELECT count() FROM eds_silver.fact_sejour "
            "WHERE service_code NOT IN (SELECT service_code FROM eds_silver.dim_service)"
        ),
        "fact_diagnostic → dim_cim10": (
            "SELECT count() FROM eds_silver.fact_diagnostic "
            "WHERE code_cim10 NOT IN (SELECT code_cim10 FROM eds_silver.dim_cim10)"
        ),
        "fact_monitoring → dim_service": (
            "SELECT count() FROM eds_silver.fact_monitoring "
            "WHERE service_code NOT IN (SELECT service_code FROM eds_silver.dim_service)"
        ),
    }
    for relation, requete in orphelins.items():
        assert scalar(client, requete) == 0, relation


def test_le_monitoring_ne_couvre_que_la_reanimation_et_la_cardiologie(client):
    services = scalar(
        client,
        "SELECT arraySort(groupUniqArray(service_code)) FROM eds_silver.fact_monitoring",
    )
    assert list(services) == ["CARDIO", "REA"]


# ── Indicateurs ─────────────────────────────────────────────────────────────
def test_readmissions_30_jours(client):
    """Définition : une admission postérieure à la sortie, dans les 30 jours."""
    eligibles, readmissions = client.query(
        "SELECT sum(sorties_eligibles), sum(readmissions_30j) "
        "FROM eds_gold_pilotage.kpi_readmissions_30j"
    ).result_rows[0]
    assert eligibles == 11_678
    assert readmissions == 687


def test_la_dms_ignore_les_sejours_en_cours(client):
    """Une durée partielle fausserait la moyenne : elle ne doit pas être comptée."""
    sorties_gold = scalar(client, "SELECT sum(nb_sorties) FROM eds_gold_pilotage.kpi_dms_service")
    sejours_termines = scalar(
        client, "SELECT countIf(discharge_ts IS NOT NULL) FROM eds_silver.fact_sejour"
    )
    assert sorties_gold == sejours_termines


def test_relevés_en_alerte(client):
    assert scalar(client, "SELECT countIf(is_alert) FROM eds_silver.fact_monitoring") == 3_053


# ── RGPD ────────────────────────────────────────────────────────────────────
def test_aucune_colonne_identifiante_dans_l_entrepot(client):
    """Le NIR, le nom, le prénom et l'IPP ne doivent exister nulle part."""
    colonnes = scalar(
        client,
        "SELECT count() FROM system.columns "
        "WHERE database LIKE 'eds_%' "
        "  AND name IN ('nir', 'nom', 'prenom', 'birth_date', 'patient_id')",
    )
    assert colonnes == 0


def test_le_pseudonyme_ne_ressemble_pas_a_un_ipp(client):
    """Contrôle par échantillon : le format doit être celui du HMAC tronqué."""
    exemple = scalar(client, "SELECT patient_pseudo FROM eds_silver.dim_patient LIMIT 1")
    assert exemple.startswith("P")
    assert "IPP" not in exemple


def test_k_anonymat_respecte_sur_toutes_les_tables_de_recherche(client):
    """Aucune cellule diffusée ne doit regrouper moins de 5 patients."""
    tables = (
        "cohorte_pathologie",
        "prevalence_pathologie",
        "cohorte_demographie",
        "cohorte_demographie_region",
    )
    for table in tables:
        minimum = scalar(client, f"SELECT min(nb_patients) FROM eds_gold_recherche.{table}")
        assert minimum >= 5, f"{table} diffuse une cohorte de {minimum} patients"


def test_le_k_anonymat_supprime_effectivement_des_cellules(client):
    """Si rien n'était jamais supprimé, la règle ne serait pas démontrée."""
    calculees, diffusees, supprimees = client.query(
        "SELECT cellules_calculees, cellules_diffusees, cellules_supprimees "
        "FROM eds_gold_recherche.k_anonymat_controle"
    ).result_rows[0]
    assert calculees == 1_600
    assert diffusees == 1_596
    assert supprimees == 4


def test_la_base_recherche_ne_contient_aucun_pseudonyme_individuel(client):
    """Minimisation : seuls des agrégats sont diffusés à la recherche."""
    colonnes = scalar(
        client,
        "SELECT count() FROM system.columns "
        "WHERE database = 'eds_gold_recherche' AND name = 'patient_pseudo'",
    )
    assert colonnes == 0


# ── Cloisonnement ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("user_key", "base_interdite"),
    [
        ("recherche", "eds_gold_pilotage"),
        ("recherche", "eds_silver"),
        ("recherche", "eds_bronze"),
        ("pilotage", "eds_gold_recherche"),
        ("pilotage", "eds_silver"),
    ],
)
def test_acces_refuse_hors_de_son_perimetre(config, user_key, base_interdite):
    """Le cloisonnement est porté par ClickHouse, pas seulement par Metabase."""
    mot_de_passe = (
        config.recherche_password if user_key == "recherche" else config.pilotage_password
    )
    restreint = connect(config, user=f"chu_{user_key}", password=mot_de_passe)

    with pytest.raises(Exception):  # noqa: B017 — tout refus fait l'affaire
        restreint.query(f"SELECT count() FROM {base_interdite}.fact_sejour")


def test_cloisonnement_du_contenu_dans_metabase(config):
    """Seconde barrière : un compte n'ouvre pas le tableau de bord de l'autre usage.

    Le contrôle SQL prouve que le moteur refuse la requête ; celui-ci prouve que
    l'interface ne montre même pas le contenu. C'est la démonstration demandée
    par le sujet, sous une forme rejouable.
    """
    from eds.metabase import MetabaseError, verifier_cloisonnement

    try:
        resultats = verifier_cloisonnement(config)
    except MetabaseError as exc:
        pytest.skip(f"Metabase indisponible : {exc}")

    assert len(resultats) == 4, "deux utilisateurs × deux tableaux de bord"
    non_conformes = [f"{c.utilisateur} → {c.dashboard}" for c in resultats if not c.conforme]
    assert not non_conformes, f"accès non conformes : {non_conformes}"


@pytest.mark.parametrize(
    ("user_key", "base_autorisee"),
    [("pilotage", "eds_gold_pilotage"), ("recherche", "eds_gold_recherche")],
)
def test_acces_autorise_a_son_perimetre(config, user_key, base_autorisee):
    mot_de_passe = (
        config.recherche_password if user_key == "recherche" else config.pilotage_password
    )
    restreint = connect(config, user=f"chu_{user_key}", password=mot_de_passe)

    tables = scalar(
        restreint,
        f"SELECT count() FROM system.tables WHERE database = '{base_autorisee}'",
    )
    assert tables > 0


# ── Traçabilité ─────────────────────────────────────────────────────────────
LIGNAGE_ATTENDU = [
    ("eds_bronze", table)
    for table in ("patients", "sejours", "diagnostics", "monitoring", "services", "cim10")
] + [
    ("eds_silver", table)
    for table in (
        "dim_patient",
        "dim_service",
        "dim_cim10",
        "fact_sejour",
        "fact_diagnostic",
        "fact_monitoring",
        "sejours_rejets",
        "monitoring_rejets",
    )
]


@pytest.mark.parametrize(("database", "table"), LIGNAGE_ATTENDU)
def test_toutes_les_lignes_portent_leur_lignage(client, database, table):
    """Sans exception : chaque ligne sait de quel fichier et de quel jour elle vient.

    Le contrôle couvre les quatorze tables de bronze et de silver — dimensions
    comprises — pour que l'affirmation du rapport reste vérifiable.
    """
    colonnes = scalar(
        client,
        "SELECT count() FROM system.columns "
        f"WHERE database = '{database}' AND table = '{table}' "
        "  AND name IN ('_source_file', '_ingest_date')",
    )
    assert colonnes == 2, f"{database}.{table} n'a pas ses colonnes de lignage"

    sans_lignage = scalar(
        client,
        f"SELECT countIf(_source_file = '' OR _ingest_date = toDate(0)) FROM {database}.{table}",
    )
    assert sans_lignage == 0, f"{database}.{table}"


def test_l_ingestion_est_journalisee(client):
    """14 fichiers déposés sur trois jours, tous chargés avec succès."""
    total, succes = client.query(
        "SELECT count(), countIf(status = 'success') FROM ops.ingest_log FINAL"
    ).result_rows[0]
    assert total == 14
    assert succes == 14


def test_le_rapport_qualite_est_renseigne(client):
    """Les chiffres publiés doivent toujours être adossés à un rapport qualité.

    On vise le dernier run ayant construit les tables, et non le dernier run tout
    court : un passage incrémental sans nouveau fichier ne reconstruit rien.
    """
    from eds.state import last_quality_run_id

    run_id = last_quality_run_id(client)
    assert run_id is not None, "aucun rapport qualité en base"

    regles = scalar(
        client,
        f"SELECT uniqExact(rule) FROM ops.quality_report WHERE run_id = '{run_id}'",
    )
    assert regles >= 14
