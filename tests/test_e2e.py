"""Tests d'intégration : invariants de l'entrepôt après un run complet.

Ces tests vérifient que les chiffres produits sont exactement ceux attendus des
données du CHU — c'est la garantie que les indicateurs sont reproductibles et
qu'une régression de la logique de transformation serait détectée.

Les six KPI du sujet sont ancrés valeur par valeur sur la feuille de réponses
remise par l'intervenant avec le jeu de données corrigé — non distribuée avec le
dépôt, ses valeurs sont reprises ici littéralement. Ce n'est pas un test de
non-régression : c'est la vérification que l'entrepôt produit la bonne réponse,
pas seulement la même qu'hier.

Depuis le 29 août 2026, le dépôt porte aussi les actes médicaux et la description des
services : la section « Évolution » vérifie que l'entrepôt les exploite sans que rien
d'antérieur n'ait bougé.

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
# Ces valeurs découlent des vingt-huit jours de dépôt fournis et des règles qualité.
# Les faire évoluer suppose d'expliquer pourquoi : c'est le but.

BRONZE_ATTENDU = {
    "patients": 18_000,  # les 6 000 patients redéposés trois fois (26, 27, 28 août)
    "sejours": 6_797,
    "diagnostics": 12_720,
    "monitoring": 41_778,
    # Dépôt du 29 août : un flux de faits et deux nomenclatures.
    "actes": 8_112,
    "description_service": 7,  # NEURO n'y figure pas
    "ccam": 8,
}

SILVER_ATTENDU = {
    "dim_patient": 6_000,  # 18 000 lignes → 6 000 patients distincts
    "fact_sejour": 6_729,  # 6 797 - 68 séjours aux horodatages incohérents
    "sejours_rejets": 68,
    "fact_diagnostic": 12_720,  # aucune perte : le rejet Q2 ne cascade pas
    "fact_monitoring": 40_920,  # 41 778 - 858 capteurs hors plage
    "monitoring_rejets": 858,  # hors plage physiologique, et rien d'autre
    "dim_ccam": 8,
    "fact_acte": 8_112,  # tous rattachés à un séjour déposé
    "actes_rejets": 0,
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
    """Q2 : la règle qui motive les 68 rejets doit être sans exception."""
    restants = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_sejour "
        "WHERE discharge_ts IS NOT NULL AND discharge_ts < admission_ts",
    )
    assert restants == 0


def test_les_sejours_en_cours_sont_conserves(client):
    """Q3 : une sortie non renseignée est un cas métier, pas une anomalie."""
    assert scalar(client, "SELECT countIf(is_ongoing) FROM eds_silver.fact_sejour") == 683


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
    assert flags == 136


def test_aucun_releve_posterieur_a_la_sortie(client):
    """Q8 : contrôle actif, évalué sur les seuls séjours temporellement cohérents.

    Sur les autres, c'est la date de sortie elle-même qui est fausse : la
    comparaison n'aurait aucun sens et le contrôle passerait au rouge sans qu'une
    seule donnée soit en cause.
    """
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


def test_le_rejet_d_un_sejour_ne_cascade_pas(client):
    """Un rejet ne vaut que pour la table où vit l'anomalie.

    Q2 invalide les HORODATAGES d'un séjour, pas le séjour : le patient existe, le
    service existe, les diagnostics codés sont des faits cliniques et les relevés de
    constantes portent leur propre horodatage. Les écarter en cascade minorait la
    prévalence de quinze patients et perdait 520 relevés parfaitement valides.
    """
    diagnostics = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_diagnostic "
        "WHERE stay_id IN (SELECT stay_id FROM eds_silver.sejours_rejets)",
    )
    releves = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_monitoring "
        "WHERE stay_id IN (SELECT stay_id FROM eds_silver.sejours_rejets)",
    )
    assert (diagnostics, releves) == (127, 520)

    # Et le patient reste résolu : aucun fait orphelin de dimension.
    orphelins = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_diagnostic "
        "WHERE patient_pseudo NOT IN (SELECT patient_pseudo FROM eds_silver.dim_patient)",
    )
    assert orphelins == 0


def test_le_monitoring_ne_couvre_que_la_reanimation_et_la_cardiologie(client):
    services = scalar(
        client,
        "SELECT arraySort(groupUniqArray(service_code)) FROM eds_silver.fact_monitoring",
    )
    assert list(services) == ["CARDIO", "REA"]


# ── Indicateurs : ancrés sur la feuille de réponses du jeu corrigé ──────────
# Chaque valeur ci-dessous vient de la feuille de réponses de l'intervenant. Un écart
# signifie que l'entrepôt ne répond pas à la question posée — pas qu'il a changé.

KPI1_DMS_PAR_SERVICE = {
    "REA": (423, 9.05, 217.1),
    "NEURO": (1_077, 7.06, 169.5),
    "ONCO": (185, 6.87, 164.8),
    "PNEUMO": (753, 6.20, 148.9),
    "CARDIO": (1_459, 5.31, 127.5),
    "CHIR": (424, 4.39, 105.2),
    "PEDIA": (448, 3.19, 76.5),
    "URGENCES": (1_277, 2.15, 51.7),
}

# (jour d'août, passages, encore présents, durée moyenne en heures)
KPI3_URGENCES_PAR_JOUR = [
    (1, 46, 0, 47.6),
    (2, 40, 0, 50.5),
    (3, 48, 0, 46.9),
    (4, 42, 0, 46.9),
    (5, 41, 0, 48.8),
    (6, 53, 0, 58.1),
    (7, 58, 0, 52.4),
    (8, 50, 0, 49.5),
    (9, 55, 0, 51.4),
    (10, 45, 0, 49.7),
    (11, 62, 0, 56.1),
    (12, 46, 0, 47.3),
    (13, 57, 0, 51.2),
    (14, 48, 0, 54.7),
    (15, 68, 0, 55.9),
    (16, 54, 15, 56.1),
    (17, 55, 17, 50.0),
    (18, 63, 18, 49.4),
    (19, 73, 15, 48.8),
    (20, 59, 17, 56.9),
    (21, 82, 14, 50.7),
    (22, 56, 9, 58.6),
    (23, 64, 8, 51.5),
    (24, 53, 10, 52.9),
    (25, 69, 14, 46.0),
    (26, 9, 3, 60.3),
    (27, 11, 1, 48.8),
    (28, 16, 5, 54.7),
]

# (jour d'août, relevés, alertes, taux %)
KPI4_ALERTES_PAR_JOUR = [
    (1, 351, 25, 7.1),
    (2, 1_199, 103, 8.6),
    (3, 1_543, 110, 7.1),
    (4, 1_333, 103, 7.7),
    (5, 1_341, 103, 7.7),
    (6, 1_247, 106, 8.5),
    (7, 1_192, 98, 8.2),
    (8, 1_461, 118, 8.1),
    (9, 1_520, 140, 9.2),
    (10, 1_303, 111, 8.5),
    (11, 1_330, 110, 8.3),
    (12, 1_431, 106, 7.4),
    (13, 1_549, 114, 7.4),
    (14, 1_801, 135, 7.5),
    (15, 1_766, 130, 7.4),
    (16, 1_594, 127, 8.0),
    (17, 1_862, 135, 7.3),
    (18, 2_022, 172, 8.5),
    (19, 1_792, 165, 9.2),
    (20, 1_539, 128, 8.3),
    (21, 1_540, 134, 8.7),
    (22, 1_592, 128, 8.0),
    (23, 1_674, 148, 8.8),
    (24, 1_939, 171, 8.8),
    (25, 2_182, 173, 7.9),
    (26, 1_709, 135, 7.9),
    (27, 669, 45, 6.7),
    (28, 275, 19, 6.9),
    (29, 130, 14, 10.8),
    (30, 34, 8, 23.5),
]

# (code CIM-10, tranche d'âge, sexe) → effectif publié ; None = masqué par le seuil.
KPI6_COHORTE = {
    ("C34", "50-59", "M"): 73,
    ("C34", "60-69", "M"): 62,
    ("C34", "70-79", "M"): 75,
    ("C34", "80-89", "M"): 29,
    ("E11", "40-49", "F"): 107,
    ("E11", "40-49", "M"): 160,
    ("E11", "50-59", "F"): 100,
    ("E11", "50-59", "M"): 45,
    ("E11", "60-69", "F"): 110,
    ("E11", "60-69", "M"): 81,
    ("E11", "70-79", "F"): 96,
    ("E11", "70-79", "M"): 71,
    ("E11", "80-89", "F"): 41,
    ("E11", "80-89", "M"): 32,
    ("E84", "0-9", "F"): None,
    ("E84", "10-19", "M"): None,
    ("E84", "20-29", "F"): None,
    ("F32", "10-19", "F"): 18,
    ("F32", "10-19", "M"): 21,
    ("F32", "20-29", "F"): 62,
    ("F32", "20-29", "M"): 102,
    ("F32", "30-39", "F"): 60,
    ("F32", "30-39", "M"): 97,
    ("F32", "40-49", "F"): 77,
    ("F32", "40-49", "M"): 114,
    ("F32", "50-59", "F"): 79,
    ("F32", "50-59", "M"): 56,
    ("F32", "60-69", "F"): 67,
    ("F32", "60-69", "M"): 62,
    ("F32", "70-79", "F"): 7,
    ("F32", "70-79", "M"): 5,
    ("G12", "0-9", "F"): None,
    ("G12", "0-9", "M"): None,
    ("G12", "10-19", "F"): None,
    ("G12", "10-19", "M"): None,
    ("G12", "20-29", "F"): None,
    ("G12", "20-29", "M"): None,
    ("G12", "30-39", "F"): None,
    ("I21", "40-49", "M"): 67,
    ("I21", "50-59", "M"): 115,
    ("I21", "60-69", "M"): 106,
    ("I21", "70-79", "M"): 69,
    ("I21", "80-89", "M"): 57,
    ("I21", "90-99", "M"): 7,
    ("I50", "60-69", "F"): 133,
    ("I50", "60-69", "M"): 93,
    ("I50", "70-79", "F"): 113,
    ("I50", "70-79", "M"): 76,
    ("I50", "80-89", "F"): 106,
    ("I50", "80-89", "M"): 49,
    ("I50", "90-99", "F"): 87,
    ("I50", "90-99", "M"): 72,
    ("I63", "50-59", "F"): 33,
    ("I63", "50-59", "M"): 29,
    ("I63", "60-69", "F"): 93,
    ("I63", "60-69", "M"): 77,
    ("I63", "70-79", "F"): 93,
    ("I63", "70-79", "M"): 70,
    ("I63", "80-89", "F"): 65,
    ("I63", "80-89", "M"): 56,
    ("I63", "90-99", "F"): 64,
    ("I63", "90-99", "M"): 63,
    ("J18", "0-9", "F"): 30,
    ("J18", "0-9", "M"): 26,
    ("J18", "50-59", "F"): 37,
    ("J18", "50-59", "M"): 19,
    ("J18", "60-69", "F"): 121,
    ("J18", "60-69", "M"): 89,
    ("J18", "70-79", "F"): 117,
    ("J18", "70-79", "M"): 101,
    ("J18", "80-89", "F"): 93,
    ("J18", "80-89", "M"): 71,
    ("J18", "90-99", "F"): 75,
    ("J18", "90-99", "M"): 71,
    ("J44", "50-59", "M"): 30,
    ("J44", "60-69", "M"): 89,
    ("J44", "70-79", "M"): 81,
    ("J44", "80-89", "M"): 75,
    ("J44", "90-99", "M"): 12,
    ("K35", "0-9", "F"): 67,
    ("K35", "0-9", "M"): 84,
    ("K35", "10-19", "F"): 127,
    ("K35", "10-19", "M"): 129,
    ("K35", "20-29", "F"): 64,
    ("K35", "20-29", "M"): 123,
    ("K35", "30-39", "F"): 68,
    ("K35", "30-39", "M"): 119,
    ("K35", "40-49", "F"): 7,
    ("K35", "40-49", "M"): 18,
    ("N39", "0-9", "F"): 37,
    ("N39", "0-9", "M"): 35,
    ("N39", "20-29", "F"): 91,
    ("N39", "30-39", "F"): 80,
    ("N39", "40-49", "F"): 131,
    ("N39", "50-59", "F"): 120,
    ("N39", "60-69", "F"): 132,
    ("N39", "70-79", "F"): 125,
    ("N39", "80-89", "F"): 93,
    ("N39", "90-99", "F"): 12,
    ("Q90", "0-9", "M"): None,
    ("Q90", "10-19", "M"): None,
    ("Q90", "30-39", "F"): None,
}

KPI5_PREVALENCE = {
    "N39": 2_234,
    "E11": 2_177,
    "I50": 2_156,
    "J44": 1_775,
    "J18": 850,
    "F32": 827,
    "K35": 806,
    "I63": 643,
    "I21": 421,
    "C34": 239,
    "G12": 8,
    "E84": None,
    "Q90": None,  # sous le seuil : effectif masqué
}


def test_kpi1_dms_par_service(client):
    """Grain : le service. Une DMS par jour de sortie répondrait à une autre question."""
    lignes = {
        code: (nb, dms_j, dms_h)
        for code, nb, dms_j, dms_h in client.query(
            "SELECT service_code, nb_sejours, dms_jours, dms_heures "
            "FROM eds_gold_pilotage.kpi_dms_service"
        ).result_rows
    }
    assert lignes == KPI1_DMS_PAR_SERVICE


def test_kpi2_readmissions_30_jours(client):
    """Un séjour est suivi d'une réadmission si le patient revient dans les 30 jours.

    Dénominateur : tous les séjours valides. Un séjour en cours y figure et compte
    pour zéro au numérateur — sa sortie n'a pas eu lieu.
    """
    readmissions, sejours, taux = client.query(
        "SELECT nb_readmissions_30j, nb_sejours, taux_readmission_30j_pct "
        "FROM eds_gold_pilotage.kpi_readmissions_30j"
    ).result_rows[0]
    assert (readmissions, sejours, taux) == (780, 6_729, 11.59)


def test_la_ventilation_des_readmissions_se_reconcilie_avec_le_global(client):
    """Deux tables, une seule définition : leurs totaux ne peuvent pas diverger."""
    ventile = client.query(
        "SELECT sum(nb_sejours), sum(nb_readmissions_30j) "
        "FROM eds_gold_pilotage.kpi_readmissions_service"
    ).result_rows[0]
    global_ = client.query(
        "SELECT nb_sejours, nb_readmissions_30j FROM eds_gold_pilotage.kpi_readmissions_30j"
    ).result_rows[0]
    assert ventile == global_


def test_kpi3_activite_des_urgences_par_jour(client):
    """Un passage = un séjour dans l'unité URGENCES, compté à sa date d'admission."""
    lignes = [
        (jour.day, passages, presents, duree)
        for jour, passages, presents, duree in client.query(
            "SELECT admission_date, nb_passages, nb_encore_presents, duree_moy_heures "
            "FROM eds_gold_pilotage.kpi_urgences_jour ORDER BY admission_date"
        ).result_rows
    ]
    assert lignes == KPI3_URGENCES_PAR_JOUR


def test_kpi4_releves_en_alerte_par_jour(client):
    """Seuils de vigilance : FC < 50 ou > 100, SpO2 < 92, température > 38,5 °C.

    Ils sont volontairement plus serrés que les bornes de plausibilité qui filtrent
    les capteurs en panne : une constante peut être parfaitement mesurée et
    cliniquement anormale.
    """
    lignes = [
        (jour.day, releves, alertes, taux)
        for jour, releves, alertes, taux in client.query(
            "SELECT jour, nb_releves, nb_alertes, taux_alertes_pct "
            "FROM eds_gold_pilotage.kpi_alertes_jour ORDER BY jour"
        ).result_rows
    ]
    assert lignes == KPI4_ALERTES_PAR_JOUR


def test_le_calendrier_d_activite_n_a_aucun_trou(client):
    """Un jour sans aucun mouvement doit rester dans la courbe de charge.

    Le 12 septembre n'a ni admission ni sortie dans tout l'hôpital, mais 687 patients
    y sont hospitalisés. Construire l'axe temporel depuis les seuls jours porteurs
    d'un mouvement le faisait disparaître, et la courbe sautait sans rien signaler.
    """
    jours, premier, dernier, lignes = client.query(
        "SELECT uniqExact(jour), min(jour), max(jour), count() "
        "FROM eds_gold_pilotage.kpi_activite_service"
    ).result_rows[0]
    services = scalar(client, "SELECT count() FROM eds_silver.dim_service")
    assert jours == (dernier - premier).days + 1, "il manque des jours au calendrier"
    assert lignes == jours * services


def test_la_dms_ignore_les_sejours_en_cours(client):
    """Une durée partielle fausserait la moyenne : elle ne doit pas être comptée."""
    agrege = scalar(client, "SELECT sum(nb_sejours) FROM eds_gold_pilotage.kpi_dms_service")
    termines = scalar(
        client, "SELECT countIf(discharge_ts IS NOT NULL) FROM eds_silver.fact_sejour"
    )
    assert agrege == termines


def test_les_tuiles_de_synthese_reprennent_les_tables_gold(client):
    """Une tuile qui recalcule son chiffre finit par diverger du graphique qui le détaille."""
    sejours, dms, readm, taux, alertes, pct = client.query(
        "SELECT nb_sejours, dms_globale_jours, nb_readmissions_30j, taux_readmission_pct, "
        "       nb_releves_alerte, pct_releves_alerte FROM eds_gold_pilotage.kpi_synthese"
    ).result_rows[0]
    assert (sejours, dms, readm, taux, alertes, pct) == (6_729, 5.15, 780, 11.59, 3_314, 8.1)


# ── Évolution du 29 août 2026 : actes médicaux et description des services ──
# Le CHU a ajouté des données ; rien de ce qui précède ne doit avoir bougé. Les cinq
# indicateurs sont ancrés sur la feuille de réponses de l'évolution : mêmes colonnes,
# mêmes lignes, dans le même ordre — qui est aussi l'ordre physique de chaque table
# (clé de tri `rang`).

# KPI 1 — (catégorie, séjours clos, DMS en jours)
KPI_EVO1_ACTIVITE_PAR_CATEGORIE = [
    ("medecine", 2_397, 5.71),  # CARDIO, PNEUMO, ONCO
    ("urgences", 1_277, 2.15),
    ("(non decrit)", 1_077, 7.06),  # NEURO, absent de la description
    ("pediatrie", 448, 3.19),
    ("chirurgie", 424, 4.39),
    ("reanimation", 423, 9.05),
]

# KPI 2 — (service, libellé, actes, séjours ayant au moins un acte, actes par séjour)
KPI_EVO2_ACTES_PAR_SERVICE = [
    ("CARDIO", "Cardiologie", 1_935, 1_213, 1.6),
    ("URGENCES", "Urgences", 1_731, 1_090, 1.59),
    ("NEURO", "Neurologie", 1_471, 918, 1.6),
    ("PNEUMO", "Pneumologie", 1_009, 642, 1.57),
    ("PEDIA", "Pediatrie", 598, 379, 1.58),
    ("CHIR", "Chirurgie", 564, 344, 1.64),
    ("REA", "Reanimation", 563, 355, 1.59),
    ("ONCO", "Oncologie", 241, 155, 1.55),
]

# KPI 3 — (code CCAM, libellé, actes)
KPI_EVO3_ACTES_PAR_TYPE = [
    ("ZBQK001", "Radiographie du thorax", 1_043),
    ("YYYY010", "Consultation de suivi", 1_039),
    ("DZEA001", "Coronarographie", 1_030),
    ("EBLA003", "Pose de catheter central", 1_025),
    ("HGQD001", "Coloscopie totale", 1_015),
    ("GLLD001", "Ventilation mecanique assistee", 1_000),
    ("NEJA001", "IRM cerebrale", 982),
    ("HHFA001", "Appendicectomie", 978),
]

# KPI 4 — (service, libellé, lits, actes, actes par lit). NEURO n'est pas décrit :
# capacité inconnue, densité NULL, classé en dernier.
#
# Urgences : 1 731 / 20 = 86,55 exactement. ClickHouse arrondit la demi-unité vers le
# haut (86,6) ; la feuille de réponses affiche 86,5 — l'arrondi du flottant binaire
# 86,549 999… par l'outil qui l'a produite. Écart de 0,1, dans la tolérance de la
# feuille (±0,1 sur les moyennes) ; les sept autres densités sont identiques.
KPI_EVO4_DENSITE_PAR_LIT = [
    ("URGENCES", "Urgences", 20, 1_731, 86.6),
    ("CARDIO", "Cardiologie", 30, 1_935, 64.5),
    ("PNEUMO", "Pneumologie", 28, 1_009, 36.0),
    ("REA", "Reanimation", 16, 563, 35.2),
    ("PEDIA", "Pediatrie", 22, 598, 27.2),
    ("CHIR", "Chirurgie", 40, 564, 14.1),
    ("ONCO", "Oncologie", 35, 241, 6.9),
    ("NEURO", "Neurologie", None, 1_471, None),
]

# KPI 5 — (service, libellé, actes, montant facturé en euros) ; total 2 199 450 €
KPI_EVO5_FACTURATION_PAR_SERVICE = [
    ("CARDIO", "Cardiologie", 1_935, 521_655),
    ("URGENCES", "Urgences", 1_731, 478_585),
    ("NEURO", "Neurologie", 1_471, 393_850),
    ("PNEUMO", "Pneumologie", 1_009, 268_045),
    ("PEDIA", "Pediatrie", 598, 171_165),
    ("REA", "Reanimation", 563, 154_740),
    ("CHIR", "Chirurgie", 564, 147_145),
    ("ONCO", "Oncologie", 241, 64_265),
]


def _table_dans_l_ordre_de_la_feuille(client, table: str, colonnes: str, attendu: list) -> None:
    """Mêmes valeurs, même ordre que la feuille — et cet ordre est celui de la table.

    `rang` est la clé de tri physique : un `SELECT *` sans ORDER BY rend les lignes
    dans l'ordre du classement. On le vérifie sur la définition de la table, pas
    sur un hasard de lecture.
    """
    lignes = client.query(
        f"SELECT {colonnes}, rang FROM eds_gold_pilotage.{table} ORDER BY rang"
    ).result_rows
    assert [tuple(ligne[:-1]) for ligne in lignes] == attendu, table
    assert [ligne[-1] for ligne in lignes] == list(range(1, len(attendu) + 1)), "rang non dense"
    cle = scalar(
        client,
        "SELECT sorting_key FROM system.tables "
        f"WHERE database = 'eds_gold_pilotage' AND name = '{table}'",
    )
    assert cle == "rang", f"{table} n'est pas triée par rang"


def test_les_kpi_historiques_sont_inchanges_apres_l_evolution(client):
    """Non-régression, en une ligne : les six indicateurs du corrigé valent toujours pareil.

    Chacun a son propre test plus haut ; celui-ci existe pour que la promesse de
    l'évolution — « sans rien casser » — soit vérifiée à un seul endroit, nommément.
    """
    invariants = client.query(
        "SELECT (SELECT count() FROM eds_silver.fact_sejour), "
        "       (SELECT dms_jours FROM eds_gold_pilotage.kpi_dms_service "
        "        WHERE service_code = 'REA'), "
        "       (SELECT taux_readmission_30j_pct FROM eds_gold_pilotage.kpi_readmissions_30j), "
        "       (SELECT sum(nb_passages) FROM eds_gold_pilotage.kpi_urgences_jour), "
        "       (SELECT sum(nb_alertes) FROM eds_gold_pilotage.kpi_alertes_jour), "
        "       (SELECT nb_patients FROM eds_gold_recherche.prevalence_pathologie "
        "        WHERE code_cim10 = 'N39'), "
        "       (SELECT countIf(diffusable) FROM eds_gold_recherche.cohorte_demographie)"
    ).result_rows[0]
    assert invariants == (6_729, 9.05, 11.59, 1_423, 3_314, 2_234, 89)


def test_dim_service_est_completee_sans_perdre_le_service_non_decrit(client):
    """Le référentiel de description ne couvre que sept services sur huit.

    NEURO en est absent — le piège annoncé par le sujet. Il reste dans la dimension :
    catégorie et pôle « (non decrit) », capacité NULL et jamais inventée, et le fait
    est porté par `est_decrit` puis compté par la règle Q9.
    """
    lignes = {
        code: (categorie, pole, lits, decrit)
        for code, categorie, pole, lits, decrit in client.query(
            "SELECT service_code, categorie, pole, capacite_lits, est_decrit "
            "FROM eds_silver.dim_service"
        ).result_rows
    }
    assert len(lignes) == 8, "un service a disparu de la dimension"
    assert lignes["NEURO"] == ("(non decrit)", "(non decrit)", None, False)
    assert lignes["CARDIO"] == ("medecine", "Coeur-Poumon", 30, True)
    assert lignes["REA"] == ("reanimation", "Soins critiques", 16, True)
    assert sum(1 for _, _, _, decrit in lignes.values() if decrit) == 7


def test_fact_acte_porte_le_service_du_sejour_sans_jointure_fait_a_fait(client):
    """Le service est résolu au build et rangé sur le fait — c'est la réponse au piège n° 2.

    Il vient du référentiel de tous les séjours déposés : les 82 actes réalisés
    pendant les 68 séjours aux horodatages incohérents gardent leur service et
    restent comptés, comme les diagnostics et les relevés (un rejet ne vaut que
    pour la table où vit l'anomalie).
    """
    actes, codes_inconnus, hors_sejour, montant, sur_rejetes, sejours = client.query(
        "SELECT count(), countIf(is_code_inconnu), countIf(is_hors_sejour), "
        "       sum(montant_euros), "
        "       countIf(stay_id IN (SELECT stay_id FROM eds_silver.sejours_rejets)), "
        "       uniqExact(stay_id) "
        "FROM eds_silver.fact_acte"
    ).result_rows[0]
    assert (actes, codes_inconnus, hors_sejour, sur_rejetes, sejours) == (8_112, 0, 0, 82, 5_096)
    assert montant == 2_199_450

    sans_service = scalar(
        client,
        "SELECT count() FROM eds_silver.fact_acte "
        "WHERE service_code NOT IN (SELECT service_code FROM eds_silver.dim_service)",
    )
    assert sans_service == 0

    # Minimisation : aucun indicateur d'actes ne compte des patients, le pseudonyme
    # ne descend donc pas jusqu'à cette table.
    colonnes = scalar(
        client,
        "SELECT groupArray(name) FROM system.columns "
        "WHERE database = 'eds_silver' AND table = 'fact_acte'",
    )
    assert "patient_pseudo" not in colonnes


def test_kpi_evolution_1_activite_et_dms_par_categorie(client):
    """Grain : la catégorie de service, séjours clos. Le service non décrit y apparaît."""
    _table_dans_l_ordre_de_la_feuille(
        client,
        "kpi_activite_categorie",
        "categorie, nb_sejours, dms_jours",
        KPI_EVO1_ACTIVITE_PAR_CATEGORIE,
    )
    clos = scalar(client, "SELECT sum(nb_sejours) FROM eds_gold_pilotage.kpi_activite_categorie")
    assert clos == 6_046, "les catégories partitionnent les séjours terminés (6 729 - 683)"


def test_kpi_evolution_2_actes_par_service(client):
    """Le service est celui du séjour, résolu sur le fait : aucune jointure fait à fait."""
    _table_dans_l_ordre_de_la_feuille(
        client,
        "kpi_actes_service",
        "service_code, service_label, nb_actes, nb_sejours_avec_acte, actes_par_sejour",
        KPI_EVO2_ACTES_PAR_SERVICE,
    )


def test_kpi_evolution_3_actes_par_type(client):
    """Grain : le code CCAM. Chaque acte porte un code : les lignes totalisent les actes."""
    _table_dans_l_ordre_de_la_feuille(
        client,
        "kpi_actes_type",
        "code_ccam, libelle_ccam, nb_actes",
        KPI_EVO3_ACTES_PAR_TYPE,
    )


def test_kpi_evolution_4_densite_d_actes_par_lit(client):
    """NULL pour NEURO : sa capacité n'est pas connue, on ne divise pas par un nombre inventé."""
    _table_dans_l_ordre_de_la_feuille(
        client,
        "kpi_densite_lits",
        "service_code, service_label, capacite_lits, nb_actes, actes_par_lit",
        KPI_EVO4_DENSITE_PAR_LIT,
    )


def test_kpi_evolution_5_montant_facture_par_service(client):
    """Somme des tarifs T2A portés par le fait ; le total de l'établissement en tuile."""
    _table_dans_l_ordre_de_la_feuille(
        client,
        "kpi_facturation_service",
        "service_code, service_label, nb_actes, montant_facture_euros",
        KPI_EVO5_FACTURATION_PAR_SERVICE,
    )


def test_les_tables_d_actes_se_reconcilient_avec_le_fait(client):
    """Le garde-fou du piège n° 2 : une jointure fait-à-fait ferait exploser ces sommes.

    Les KPI 2, 4 et 5 sont trois lectures d'une même agrégation, le KPI 3 une
    répartition par code : chacun totalise exactement les lignes de `fact_acte`.
    """
    faits, *par_table = client.query(
        "SELECT (SELECT count() FROM eds_silver.fact_acte), "
        "       (SELECT sum(nb_actes) FROM eds_gold_pilotage.kpi_actes_service), "
        "       (SELECT sum(nb_actes) FROM eds_gold_pilotage.kpi_actes_type), "
        "       (SELECT sum(nb_actes) FROM eds_gold_pilotage.kpi_densite_lits), "
        "       (SELECT sum(nb_actes) FROM eds_gold_pilotage.kpi_facturation_service)"
    ).result_rows[0]
    assert faits == 8_112
    assert par_table == [faits] * 4

    montant = scalar(
        client, "SELECT sum(montant_facture_euros) FROM eds_gold_pilotage.kpi_facturation_service"
    )
    assert montant == 2_199_450

    tuiles = client.query(
        "SELECT nb_actes, montant_facture_euros FROM eds_gold_pilotage.kpi_synthese"
    ).result_rows[0]
    assert tuiles == (8_112, 2_199_450)


def test_les_regles_qualite_de_l_evolution_sont_chiffrees(client):
    """Quatre règles de plus : un signalement (Q9) et trois contrôles attendus à zéro."""
    from eds.state import last_quality_run_id

    mesures = {
        rule: (rows_in, rows_kept, rows_rejected, rows_flagged)
        for rule, rows_in, rows_kept, rows_rejected, rows_flagged in client.query(
            "SELECT rule, rows_in, rows_kept, rows_rejected, rows_flagged "
            "FROM ops.quality_report "
            f"WHERE run_id = '{last_quality_run_id(client)}' "
            "  AND rule IN ('Q9_service_non_decrit', 'C3_sejour_inconnu', "
            "               'Q6_ccam_referentiel', 'Q10_acte_hors_sejour')"
        ).result_rows
    }
    assert mesures == {
        "Q9_service_non_decrit": (8, 8, 0, 1),
        "C3_sejour_inconnu": (8_112, 8_112, 0, 0),
        "Q6_ccam_referentiel": (8_112, 8_112, 0, 0),
        "Q10_acte_hors_sejour": (8_112, 8_112, 0, 0),
    }


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
    """Aucun effectif diffusé ne doit décrire moins de 5 patients.

    Les cellules sous le seuil gardent leur ligne mais perdent leur effectif : ce
    qui est contrôlé, c'est qu'aucune valeur NON NULLE ne passe sous le seuil.
    """
    tables = ("prevalence_pathologie", "cohorte_demographie", "cohorte_demographie_globale")
    for table in tables:
        fuites = scalar(
            client,
            f"SELECT countIf(nb_patients IS NOT NULL AND nb_patients < 5) "
            f"FROM eds_gold_recherche.{table}",
        )
        assert fuites == 0, f"{table} diffuse {fuites} effectif(s) sous le seuil"


def test_le_masquage_et_le_drapeau_disent_la_meme_chose(client):
    """Une cellule diffusable porte un effectif, une cellule masquée n'en porte aucun."""
    tables = ("prevalence_pathologie", "cohorte_demographie", "cohorte_demographie_globale")
    for table in tables:
        incoherences = scalar(
            client,
            f"SELECT countIf(diffusable != (nb_patients IS NOT NULL)) "
            f"FROM eds_gold_recherche.{table}",
        )
        assert incoherences == 0, table


def test_aucune_pathologie_n_est_publiee_a_moitie(client):
    """La parade contre l'attaque par différenciation, à sa racine.

    Publier une partie des cellules d'une pathologie et en masquer d'autres casse
    deux choses d'un coup : l'agrégation devient fausse (les cellules manquantes
    sont systématiquement les plus petites), et la valeur masquée se retrouve par
    soustraction dès qu'un total de la pathologie est diffusé ailleurs.

    Ici la condition tient d'elle-même : les trois pathologies sous le seuil le sont
    sur TOUTES leurs cellules. Le test existe pour que, le jour où elle cesserait de
    tenir, on l'apprenne par un échec de build et non par une courbe fausse.
    """
    partielles = scalar(
        client,
        """
        SELECT count() FROM (
            SELECT code_cim10
            FROM eds_gold_recherche.cohorte_demographie
            GROUP BY code_cim10
            HAVING countIf(diffusable) > 0 AND countIf(NOT diffusable) > 0
        )
        """,
    )
    assert partielles == 0, f"{partielles} pathologie(s) publiées à moitié"


def test_le_k_anonymat_masque_effectivement_des_cellules(client):
    """Si rien n'était jamais masqué, la règle ne serait pas démontrée."""
    mesures = {
        table: (calculees, diffusees, masquees)
        for table, calculees, diffusees, masquees in client.query(
            "SELECT table_cible, cellules_calculees, cellules_diffusees, cellules_masquees "
            "FROM eds_gold_recherche.k_anonymat_controle"
        ).result_rows
    }
    assert mesures == {
        "prevalence_pathologie": (13, 11, 2),
        "cohorte_demographie": (102, 89, 13),
        "cohorte_demographie_globale": (20, 20, 0),
    }


def test_le_seuil_mord_sur_des_pathologies_entieres(client):
    """La mucoviscidose (4 patients) et la trisomie 21 (3) restent visibles, pas chiffrées.

    Faire disparaître la ligne serait moins protecteur, pas plus : le chercheur ne
    saurait pas qu'une valeur a été retirée, et le dispositif ne serait vérifiable
    nulle part. C'est l'effectif qui est protégé, et il ne sort pas de silver.
    """
    referentiel = scalar(client, "SELECT count() FROM eds_silver.dim_cim10")
    publiees = scalar(
        client, "SELECT countIf(diffusable) FROM eds_gold_recherche.prevalence_pathologie"
    )
    assert (referentiel, publiees) == (13, 11)

    masquees = scalar(
        client,
        "SELECT arraySort(groupArrayIf(code_cim10, NOT diffusable)) "
        "FROM eds_gold_recherche.prevalence_pathologie",
    )
    assert list(masquees) == ["E84", "Q90"]

    for table in ("prevalence_pathologie", "cohorte_demographie"):
        fuite = scalar(
            client,
            f"SELECT countIf(nb_patients IS NOT NULL) FROM eds_gold_recherche.{table} "
            f"WHERE code_cim10 IN ('E84', 'Q90')",
        )
        assert fuite == 0, f"{table} chiffre une pathologie sous le seuil"


def test_les_effectifs_publies_sont_ceux_de_la_feuille_de_reponses(client):
    """KPI 5 — la prévalence, code par code, y compris les deux cohortes masquées."""
    publie = dict(
        client.query(
            "SELECT code_cim10, nb_patients FROM eds_gold_recherche.prevalence_pathologie"
        ).result_rows
    )
    assert publie == KPI5_PREVALENCE


def test_kpi6_description_de_cohorte(client):
    """Grain pathologie × tranche d'âge × sexe, sur le diagnostic PRINCIPAL.

    Le rang du diagnostic n'est pas un détail : décrire une cohorte, c'est décrire
    les patients pris en charge POUR cette pathologie. Compter aussi les comorbidités
    gonflerait le diabète et l'insuffisance cardiaque de plus du double.

    Les 102 cellules sont comparées une à une, masquages compris.
    """
    publie = {
        (code, tranche, sexe): nb
        for code, tranche, sexe, nb in client.query(
            "SELECT code_cim10, tranche_age, sexe, nb_patients "
            "FROM eds_gold_recherche.cohorte_demographie"
        ).result_rows
    }
    assert publie == KPI6_COHORTE


def test_la_part_de_femmes_publiee_est_exacte(client):
    """Un pourcentage tiré d'une table filtrée n'est vrai que si rien n'a été retiré.

    Le tableau de bord somme les tranches d'âge d'une pathologie pour en tirer une
    part de femmes. C'est légitime ici parce qu'aucune pathologie n'est publiée à
    moitié — et ce test le vérifie sur le résultat, en comparant à la valeur
    recalculée depuis silver.
    """
    ecarts = scalar(
        client,
        """
        SELECT count() FROM (
            SELECT c.code_cim10,
                   round(100.0 * sumIf(c.nb_patients, c.sexe = 'F')
                               / sum(c.nb_patients), 1) AS publie,
                   any(v.reel) AS reel
            FROM eds_gold_recherche.cohorte_demographie AS c
            INNER JOIN (
                SELECT d.code_cim10 AS code,
                       round(100.0 * uniqExactIf(d.patient_pseudo, p.sex = 'F')
                                   / uniqExact(d.patient_pseudo), 1) AS reel
                FROM eds_silver.fact_diagnostic AS d
                INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
                WHERE d.is_principal
                GROUP BY code
            ) AS v ON v.code = c.code_cim10
            WHERE c.diffusable
            GROUP BY c.code_cim10
            HAVING abs(publie - reel) > 0.05
        )
        """,
    )
    assert ecarts == 0, f"{ecarts} pathologie(s) publient une part de femmes biaisée"


def test_la_deduplication_garde_la_version_la_plus_recente(client):
    """Q1 : le CHU redépose ses patients chaque jour, et certains changent de département.

    « Garder la version la plus récente » n'est démontrable que si des versions
    diffèrent : 118 patients ont un département différent entre deux dépôts. La
    dimension doit porter celui du dernier dépôt, sans exception.
    """
    versions = scalar(
        client,
        "SELECT count() FROM (SELECT patient_pseudo FROM eds_bronze.patients "
        "GROUP BY patient_pseudo HAVING uniqExact(region_code) > 1)",
    )
    assert versions == 118, "sans divergence entre dépôts, la règle ne serait pas exercée"

    perimes = scalar(
        client,
        """
        SELECT count()
        FROM eds_silver.dim_patient AS d
        INNER JOIN (
            SELECT patient_pseudo, argMax(region_code, _ingest_date) AS dernier
            FROM eds_bronze.patients GROUP BY patient_pseudo
        ) AS b USING (patient_pseudo)
        WHERE d.region_code != b.dernier
        """,
    )
    assert perimes == 0, "dim_patient porte une version périmée"


@pytest.mark.parametrize("base", ["eds_gold_recherche", "eds_gold_pilotage"])
def test_les_bases_de_restitution_n_exposent_que_des_types_manipulables(client, base):
    """Une colonne diffusée doit pouvoir être agrégée sans erreur de type.

    Un `UNION ALL` réconciliant `countIf` (UInt64) et une soustraction (Int64)
    produit un `Variant(Int64, UInt64)` : un simple `sum()` sur une telle
    colonne échoue avec ILLEGAL_TYPE_OF_ARGUMENT. Invisible tant qu'on se
    contente de lire la table, bloquant dès qu'un chercheur l'agrège.
    """
    exotiques = client.query(
        "SELECT table, name, type FROM system.columns "
        f"WHERE database = '{base}' AND (type LIKE '%Variant%' OR type LIKE '%Dynamic%')"
    ).result_rows
    assert not exotiques, f"{base} expose des colonnes non agrégeables : {exotiques}"


@pytest.mark.parametrize("base", ["eds_gold_recherche", "eds_gold_pilotage"])
def test_aucune_base_de_restitution_n_expose_de_pseudonyme(client, base):
    """Minimisation à l'intérieur même de l'entrepôt.

    Le pseudonyme n'est pourtant pas identifiant, mais aucun indicateur n'en a
    besoin : il ne descend donc pas jusqu'aux bases de restitution. C'est
    l'affirmation du modèle de menace du rapport (§4.1), ancrée ici.
    """
    colonnes = scalar(
        client,
        f"SELECT count() FROM system.columns WHERE database = '{base}' AND name = 'patient_pseudo'",
    )
    assert colonnes == 0, f"{base} expose un pseudonyme patient"


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
    ("usage", "dashboard", "connexion"),
    [
        ("pilotage", "🏥 Pilotage hospitalier", "EDS — Pilotage hospitalier"),
        ("recherche", "🔬 Recherche clinique", "EDS — Recherche clinique"),
    ],
)
def test_un_utilisateur_ne_voit_qu_un_seul_univers(config, usage, dashboard, connexion):
    """Le cloisonnement ne doit pas se contenter de refuser : il doit masquer.

    Un contenu visible mais grisé indique déjà qu'il existe. Ici, l'autre usage
    n'apparaît nulle part — ni tableau de bord, ni connexion à la base. Le test
    interroge l'API avec les identifiants de l'utilisateur, comme le ferait son
    navigateur.
    """
    from eds.metabase import MetabaseClient, MetabaseError

    email = config.pilotage_email if usage == "pilotage" else config.recherche_email
    mot_de_passe = (
        config.metabase_pilotage_password
        if usage == "pilotage"
        else config.metabase_recherche_password
    )

    client = MetabaseClient(config.metabase_url)
    try:
        client.authenticate(email, mot_de_passe)
    except MetabaseError as exc:
        pytest.skip(f"Metabase indisponible : {exc}")

    assert [d["name"] for d in client.get("/api/dashboard")] == [dashboard]
    assert [b["name"] for b in client.get("/api/database")["data"]] == [connexion]


def test_les_dashboards_sont_provisionnes_en_pleine_largeur(config):
    """Le rendu ne doit pas dépendre de l'historique de l'instance Metabase.

    `POST /api/dashboard` ignore silencieusement `width` : un tableau de bord
    créé de zéro restait en largeur `fixed` — enfermé dans un millier de pixels,
    avec deux marges vides — alors qu'un tableau de bord reprovisionné passait
    bien en `full`. Le défaut ne se voyait donc jamais en développement, et
    seulement après un `make reset`. Ce contrôle porte sur l'état réel de
    l'instance, pas sur l'intention du code.
    """
    from eds.metabase import MetabaseClient, MetabaseError

    client = MetabaseClient(config.metabase_url)
    try:
        client.authenticate(config.admin_email, config.admin_password)
    except MetabaseError as exc:
        pytest.skip(f"Metabase indisponible : {exc}")

    provisionnes = [
        client.get(f"/api/dashboard/{d['id']}")
        for d in client.get("/api/dashboard")
        if d["name"].startswith(("🏥", "🔬"))
    ]
    assert len(provisionnes) == 2, "les deux tableaux de bord doivent exister"

    for dashboard in provisionnes:
        assert dashboard["width"] == "full", (
            f"« {dashboard['name']} » est en largeur {dashboard['width']!r} : "
            "la grille n'occupera pas l'écran"
        )

        # La disposition poussée doit être celle que le code décrit : si deux
        # cartes se recouvraient, Metabase les repousserait à l'affichage.
        cartes = dashboard["dashcards"]
        hauteur = max(c["row"] + c["size_y"] for c in cartes)
        for ligne in range(hauteur):
            occupation = sum(
                c["size_x"] for c in cartes if c["row"] <= ligne < c["row"] + c["size_y"]
            )
            assert occupation == 24, (
                f"« {dashboard['name']} » : ligne {ligne} à {occupation} colonnes sur 24"
            )


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
    """92 fichiers sur vingt-neuf jours et six domaines, tous chargés avec succès.

    Les 89 premiers viennent des vingt-huit jours du dépôt initial ; les trois
    derniers, du 29 août — un flux d'actes et deux nomenclatures, ingérés par le
    même pipeline incrémental sans qu'aucun des 89 autres ne soit retraité.
    """
    total, succes, jours, domaines = client.query(
        "SELECT count(), countIf(status = 'success'), uniqExact(ingest_date), "
        "       uniqExact(domain) FROM ops.ingest_log FINAL"
    ).result_rows[0]
    assert (total, succes, jours, domaines) == (92, 92, 29, 6)

    evolution = sorted(
        client.query(
            "SELECT domain, source_file, rows_loaded FROM ops.ingest_log FINAL "
            "WHERE ingest_date = '2026-08-29'"
        ).result_rows
    )
    assert evolution == [
        ("actes", "actes.parquet", 8_112),
        ("referentiels", "ccam.csv", 8),
        ("referentiels", "description_service.csv", 7),
    ]


def test_le_rapport_qualite_est_renseigne(client):
    """Les chiffres publiés doivent toujours être adossés à un rapport qualité.

    On vise le dernier run ayant construit les tables, et non le dernier run tout
    court : un passage incrémental sans nouveau fichier ne reconstruit rien.
    """
    from eds.state import last_quality_run_id

    run_id = last_quality_run_id(client)
    assert run_id is not None, "aucun rapport qualité en base"

    # Le compte exact est publié dans le rapport : le figer ici empêche les deux
    # de diverger en silence. Quatre lignes en gold pour deux règles — le
    # k-anonymat est chiffré table diffusée par table diffusée. Dix-huit en silver,
    # dont les quatre de l'évolution du 29 août.
    lignes, regles = client.query(
        f"SELECT count(), uniqExact(rule) FROM ops.quality_report WHERE run_id = '{run_id}'"
    ).result_rows[0]
    assert (lignes, regles) == (22, 20)

    par_couche = dict(
        client.query(
            "SELECT layer, count() FROM ops.quality_report "
            f"WHERE run_id = '{run_id}' GROUP BY layer"
        ).result_rows
    )
    assert par_couche == {"silver": 18, "gold": 4}


def test_les_regles_rgpd_de_la_couche_gold_sont_chiffrees(client):
    """Le coût du k-anonymat est publié table par table, pas résumé d'un seul chiffre."""
    from eds.state import last_quality_run_id

    mesures = {
        (rule, table): (rows_in, rows_kept, rows_rejected)
        for rule, table, rows_in, rows_kept, rows_rejected in client.query(
            "SELECT rule, table_name, rows_in, rows_kept, rows_rejected "
            "FROM ops.quality_report "
            f"WHERE run_id = '{last_quality_run_id(client)}' AND layer = 'gold'"
        ).result_rows
    }

    assert mesures[("RGPD_k_anonymat", "prevalence_pathologie")] == (13, 11, 2)
    assert mesures[("RGPD_k_anonymat", "cohorte_demographie")] == (102, 89, 13)
    assert mesures[("RGPD_k_anonymat", "cohorte_demographie_globale")] == (20, 20, 0)
    # Aucune colonne identifiante ni pseudonyme dans la base des chercheurs.
    assert mesures[("RGPD_minimisation", "eds_gold_recherche")][2] == 0


def test_les_comptes_de_restitution_sont_bornes(client):
    """Garde-fou de disponibilité : le SQL libre ne doit pas pouvoir saturer le moteur.

    Le GRANT interdit déjà d'écrire ; ces bornes empêchent une requête maladroite
    de priver l'autre usage de son tableau de bord (cf. rapport, §6.2).
    """
    profil = dict(
        client.query(
            "SELECT setting_name, value FROM system.settings_profile_elements "
            "WHERE profile_name = 'restitution'"
        ).result_rows
    )
    assert profil["readonly"] == "2", "readonly = 1 casserait le pilote JDBC de Metabase"
    assert int(profil["max_execution_time"]) > 0
    assert int(profil["max_memory_usage"]) > 0

    for compte in ("chu_pilotage", "chu_recherche"):
        rattache = scalar(
            client,
            "SELECT count() FROM system.settings_profile_elements "
            f"WHERE user_name = '{compte}' AND inherit_profile = 'restitution'",
        )
        assert rattache == 1, f"{compte} n'hérite pas du profil de restitution"

    beneficiaires = scalar(
        client, "SELECT apply_to_list FROM system.quotas WHERE name = 'restitution'"
    )
    assert sorted(beneficiaires) == ["chu_pilotage", "chu_recherche"]
