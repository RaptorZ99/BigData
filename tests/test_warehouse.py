"""Découpage des scripts SQL et substitution des paramètres.

Le découpage sur point-virgule est un endroit où une erreur passe inaperçue :
elle produit du SQL tronqué, donc une erreur de syntaxe éloignée de sa cause.
"""

from __future__ import annotations

import pytest

from eds.warehouse import render, split_statements


def test_decoupe_plusieurs_instructions():
    script = "SELECT 1; SELECT 2;"
    assert list(split_statements(script)) == ["SELECT 1", "SELECT 2"]


def test_le_point_virgule_dans_une_chaine_ne_coupe_pas():
    """Un libellé métier peut contenir un point-virgule ; il ne sépare rien."""
    script = "SELECT 'panne de capteur ; motif tracé' AS motif;"
    assert list(split_statements(script)) == ["SELECT 'panne de capteur ; motif tracé' AS motif"]


def test_apostrophe_echappee_dans_une_chaine():
    script = "SELECT 'sortie antérieure à l''admission' AS libelle; SELECT 2;"
    instructions = list(split_statements(script))
    assert instructions[0] == "SELECT 'sortie antérieure à l''admission' AS libelle"
    assert instructions[1] == "SELECT 2"


def test_les_commentaires_sont_retires():
    script = "-- un commentaire\nSELECT 1; -- un autre\nSELECT 2;"
    assert list(split_statements(script)) == ["SELECT 1", "SELECT 2"]


def test_un_double_tiret_dans_une_chaine_n_est_pas_un_commentaire():
    """« FC hors 20-250 » ou un libellé contenant `--` doit rester intact."""
    script = "SELECT 'plage 20--250' AS bornes;"
    assert list(split_statements(script)) == ["SELECT 'plage 20--250' AS bornes"]


def test_derniere_instruction_sans_point_virgule():
    assert list(split_statements("SELECT 1;\nSELECT 2")) == ["SELECT 1", "SELECT 2"]


def test_script_vide():
    assert list(split_statements("  \n-- rien\n")) == []


def test_substitution_des_parametres():
    assert render("SELECT '{jour}'", {"jour": "2026-08-26"}) == "SELECT '2026-08-26'"


def test_les_apostrophes_des_parametres_sont_echappees():
    """Défense de principe : une valeur ne doit pas pouvoir refermer une chaîne."""
    assert render("SELECT '{v}'", {"v": "l'hôpital"}) == "SELECT 'l''hôpital'"


def test_sans_parametre_le_script_est_inchange():
    script = "SELECT 1"
    assert render(script) == script


@pytest.mark.parametrize(
    "script",
    [
        "INSERT INTO t SELECT 'a; b', 'c'; SELECT 1;",
        "SELECT 'a' AS x; -- commentaire ; avec point-virgule\nSELECT 'b' AS y;",
    ],
)
def test_deux_instructions_quel_que_soit_le_bruit(script):
    assert len(list(split_statements(script))) == 2
