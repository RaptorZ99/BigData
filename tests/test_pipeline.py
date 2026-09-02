"""Robustesse du pipeline : ce qui doit alerter, et ce qui doit se réparer.

La documentation promet trois choses au titre de la « gestion des erreurs »
exigée par la partie 2 du sujet. Ces tests les vérifient sans Docker :

  * un dépôt incomplet alerte au lieu de passer pour un run nominal ;
  * un échec de chargement suspend la publication plutôt que de republier des
    indicateurs calculés sur une source amputée ;
  * une couche dérivée en retard est détectée et reconstruite au run suivant.
"""

from __future__ import annotations

from pathlib import Path

from eds import storage
from eds.collect import discover, missing_files
from eds.config import Config


def _vider(chemin: Path) -> None:
    chemin.unlink()


def test_un_depot_complet_ne_signale_aucun_manque(config: Config):
    assert missing_files(storage.for_source(config)) == []


def test_un_fichier_absent_est_signale(config: Config, source_dir: Path):
    """Sans ce contrôle, un jour partiellement déposé passerait pour normal.

    C'est le cas le plus insidieux : le pipeline se terminerait en succès, le
    cron n'alerterait pas, et l'entrepôt serait reconstruit amputé d'un domaine.
    """
    _vider(source_dir / "sejours" / "2026-08-26" / "sejours.csv")

    manquants = missing_files(storage.for_source(config))
    assert manquants == ["sejours/2026-08-26/sejours.csv"]

    # Le fichier disparaît aussi de l'énumération : rien ne sera chargé pour lui.
    assert all(s.relative_name != "sejours.csv" for s in discover(storage.for_source(config)))


def test_un_jour_entierement_absent_n_est_pas_un_manque(config: Config, source_dir: Path):
    """Le CHU n'a pas encore déposé : ce n'est pas une anomalie, juste rien à faire."""
    import shutil

    shutil.rmtree(source_dir / "sejours" / "2026-08-26")
    assert missing_files(storage.for_source(config)) == []


def test_les_manques_sont_listes_par_domaine_et_par_jour(config: Config, source_dir: Path):
    """Le message doit désigner précisément quoi redéposer."""
    _vider(source_dir / "patients" / "2026-08-26" / "patients.csv")
    _vider(source_dir / "sejours" / "2026-08-26" / "sejours.csv")

    assert sorted(missing_files(storage.for_source(config))) == [
        "patients/2026-08-26/patients.csv",
        "sejours/2026-08-26/sejours.csv",
    ]


# ── Statut d'un run ─────────────────────────────────────────────────────────
def test_le_statut_reflete_les_echecs():
    """`partial` distingue un run dégradé d'un run entièrement raté."""
    from eds.pipeline import RunReport

    assert RunReport(run_id="x").status == "success"
    assert RunReport(run_id="x", files_ok=3).status == "success"
    assert RunReport(run_id="x", files_failed=1).status == "failed"
    assert RunReport(run_id="x", files_ok=3, files_failed=1).status == "partial"


def test_un_run_sans_chargement_ne_declare_pas_de_changement():
    """Ce booléen décide de la reconstruction : il ne doit pas être optimiste."""
    from eds.pipeline import RunReport

    assert RunReport(run_id="x").has_changes is False
    assert RunReport(run_id="x", files_skipped=14).has_changes is False
    assert RunReport(run_id="x", files_ok=1).has_changes is True


# ── Nomenclatures : un jour ne porte que celles qui changent ────────────────
def _deposer_referentiel(source_dir: Path, day: str, *fichiers: str) -> Path:
    dossier = source_dir / "referentiels" / day
    dossier.mkdir(parents=True, exist_ok=True)
    for nom in fichiers:
        (dossier / nom).write_text("a,b\n1,2\n", encoding="utf-8")
    return dossier


def test_un_jour_de_nomenclatures_partiel_est_normal(config: Config, source_dir: Path):
    """Le 29 août n'apporte que la description des services et la CCAM.

    Exiger les quatre nomenclatures à chaque dépôt ferait échouer précisément le
    dépôt d'évolution : le premier jour n'a que services et CIM-10, le 29 août
    seulement les deux nouvelles.
    """
    _deposer_referentiel(source_dir, "2026-08-01", "services.csv", "cim10.csv")
    _deposer_referentiel(source_dir, "2026-08-29", "description_service.csv", "ccam.csv")

    depot = storage.for_source(config)
    assert missing_files(depot) == []
    reconnus = sorted(
        (s.ingest_date, s.relative_name) for s in discover(depot) if s.domain == "referentiels"
    )
    assert reconnus == [
        ("2026-08-01", "cim10.csv"),
        ("2026-08-01", "services.csv"),
        ("2026-08-29", "ccam.csv"),
        ("2026-08-29", "description_service.csv"),
    ]


def test_un_jour_de_nomenclatures_vide_est_signale(config: Config, source_dir: Path):
    """Un dossier de dépôt sans aucune nomenclature reconnue ne peut pas passer inaperçu."""
    _deposer_referentiel(source_dir, "2026-08-29", "nomenclature_inconnue.csv")

    manquants = missing_files(storage.for_source(config))
    assert manquants == ["referentiels/2026-08-29/(aucune nomenclature reconnue)"]


def test_un_fichier_inconnu_n_est_pas_charge_mais_les_autres_le_sont(
    config: Config, source_dir: Path
):
    """Une faute de frappe dans un nom de fichier ne doit ni bloquer le dépôt ni être chargée."""
    _deposer_referentiel(source_dir, "2026-08-29", "ccam.csv", "ccam.CSV.bak")

    depot = storage.for_source(config)
    assert missing_files(depot) == []
    noms = [s.relative_name for s in discover(depot) if s.domain == "referentiels"]
    assert noms == ["ccam.csv"]


def test_le_flux_d_actes_est_un_domaine_quotidien(config: Config, source_dir: Path):
    """Comme le monitoring : un jour déposé sans son fichier alerte."""
    (source_dir / "actes" / "2026-08-29").mkdir(parents=True)
    assert missing_files(storage.for_source(config)) == ["actes/2026-08-29/actes.parquet"]
