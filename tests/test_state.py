"""Décision d'ingestion : ce qui doit être rechargé, et pourquoi.

C'est le cœur de l'incrémentalité exigée par le sujet — « ingérer chaque jour
les nouveaux fichiers, sans retraiter ni dupliquer les anciens ». Les quatre
branches de décision sont couvertes ici, sans dépendre de l'entrepôt.
"""

from __future__ import annotations

from eds.state import IngestedFile, needs_ingestion
from eds.storage import SourceFile

SOURCE = SourceFile(
    domain="sejours",
    ingest_date="2026-08-27",
    relative_name="sejours.csv",
)
CLE = ("sejours", "2026-08-27", "sejours.csv")
EMPREINTE = "a" * 64


def test_un_fichier_inconnu_est_ingere():
    """Le cas nominal : un nouveau jour déposé par le CHU."""
    charger, raison = needs_ingestion(SOURCE, EMPREINTE, journal={})
    assert charger is True
    assert "nouveau" in raison


def test_un_fichier_deja_ingere_est_saute():
    """Sans cela, relancer le pipeline dupliquerait les données."""
    journal = {CLE: IngestedFile(*CLE, EMPREINTE, "success")}
    charger, raison = needs_ingestion(SOURCE, EMPREINTE, journal)
    assert charger is False
    assert raison == "déjà ingéré"


def test_un_fichier_modifie_a_la_source_est_recharge():
    """Le CHU a redéposé un fichier corrigé : l'empreinte a changé."""
    journal = {CLE: IngestedFile(*CLE, "b" * 64, "success")}
    charger, raison = needs_ingestion(SOURCE, EMPREINTE, journal)
    assert charger is True
    assert "modifié" in raison


def test_un_fichier_en_echec_est_retente():
    """Une reprise après incident ne doit demander aucune action manuelle."""
    journal = {CLE: IngestedFile(*CLE, EMPREINTE, "failed")}
    charger, raison = needs_ingestion(SOURCE, EMPREINTE, journal)
    assert charger is True
    assert "échec" in raison


def test_le_journal_d_un_autre_jour_n_influence_pas_la_decision():
    """L'indexation par (domaine, jour, fichier) doit être stricte."""
    autre_jour = ("sejours", "2026-08-26", "sejours.csv")
    journal = {autre_jour: IngestedFile(*autre_jour, EMPREINTE, "success")}
    charger, _ = needs_ingestion(SOURCE, EMPREINTE, journal)
    assert charger is True


def test_un_meme_fichier_dans_un_autre_domaine_est_distinct():
    """Deux référentiels partagent un jour : ils ne doivent pas se confondre."""
    services = SourceFile("referentiels", "2026-08-26", "services.csv")
    journal = {
        ("referentiels", "2026-08-26", "cim10.csv"): IngestedFile(
            "referentiels", "2026-08-26", "cim10.csv", EMPREINTE, "success"
        )
    }
    charger, _ = needs_ingestion(services, EMPREINTE, journal)
    assert charger is True
