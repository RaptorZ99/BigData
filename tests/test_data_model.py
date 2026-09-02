"""Le diagramme du modèle de données décrit-il encore l'entrepôt réel ?

`docs/data-model.puml` fait foi pour les DDL et illustre le dossier de
conception. C'est aussi le document qui dérive le plus facilement : il ne casse
rien quand il ment, personne ne s'en aperçoit avant la soutenance, et une table
ajoutée sans y figurer donne l'impression d'un modèle qu'on n'a pas relu.

Ce test ne compare pas colonne par colonne — un diagramme synthétise, il ne
duplique pas le schéma. Il vérifie l'invariant qui compte : **toute table
attendue de l'entrepôt est représentée**, et le diagramme ne mentionne pas de
table qui n'existerait plus.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eds.transform import EXPECTED_TABLES

DIAGRAMME = Path(__file__).resolve().parents[1] / "docs" / "data-model.puml"

# Tables bronze et ops : elles ne figurent pas dans EXPECTED_TABLES, qui ne
# couvre que les couches reconstruites à chaque run.
BRONZE = (
    "patients",
    "sejours",
    "diagnostics",
    "monitoring",
    "services",
    "cim10",
    # Évolution du 29 août 2026.
    "actes",
    "description_service",
    "ccam",
)
OPS = ("ingest_log", "pipeline_runs", "quality_report")


@pytest.fixture(scope="module")
def entites() -> set[str]:
    """Noms d'entités déclarés dans le diagramme."""
    source = DIAGRAMME.read_text(encoding="utf-8")
    # `entity "**nom**\n<i>…</i>" as alias {` — on extrait le nom en gras.
    return set(re.findall(r'entity "\*\*([a-z_0-9]+)\*\*', source))


@pytest.mark.parametrize("table", BRONZE)
def test_les_tables_bronze_sont_au_diagramme(entites: set[str], table: str):
    assert table in entites


@pytest.mark.parametrize("table", OPS)
def test_les_tables_ops_sont_au_diagramme(entites: set[str], table: str):
    assert table in entites


@pytest.mark.parametrize(
    ("base", "table"),
    [(base, table) for base, tables in EXPECTED_TABLES.items() for table in tables],
)
def test_les_tables_derivees_sont_au_diagramme(entites: set[str], base: str, table: str):
    """Silver et gold : le diagramme doit suivre chaque ajout de table.

    C'est exactement ce qui avait dérivé : `k_anonymat_controle` (la preuve
    chiffrée du dispositif) existait dans l'entrepôt et dans le rapport, mais pas
    sur le schéma.
    """
    assert table in entites, (
        f"{base}.{table} est déclarée dans EXPECTED_TABLES mais absente de "
        f"{DIAGRAMME.name} — le diagramme ne décrit plus l'entrepôt"
    )


def test_le_diagramme_ne_decrit_pas_de_table_disparue(entites: set[str]):
    """L'inverse compte autant : une table retirée doit quitter le schéma."""
    attendues = set(BRONZE) | set(OPS) | {t for tables in EXPECTED_TABLES.values() for t in tables}
    fantomes = entites - attendues
    assert not fantomes, f"{DIAGRAMME.name} décrit des tables inexistantes : {sorted(fantomes)}"


def test_le_rendu_est_a_jour(entites: set[str]):
    """Le PNG et le SVG doivent avoir été régénérés après modification.

    `make diagram` les reconstruit. Sans ce contrôle, le dossier afficherait un
    schéma périmé alors que sa source est correcte — le pire des deux mondes.
    """
    source = DIAGRAMME.stat().st_mtime
    for rendu in ("eds-data-model.png", "eds-data-model.svg"):
        chemin = DIAGRAMME.parent / "img" / rendu
        assert chemin.is_file(), f"{rendu} manquant — lancez `make diagram`"
        assert chemin.stat().st_mtime >= source, (
            f"{rendu} est plus ancien que {DIAGRAMME.name} — lancez `make diagram`"
        )
