"""Cohérence des tableaux de bord, vérifiée sans démarrer Metabase.

Trois défauts de restitution ne se voient qu'à l'écran, une fois le
provisionnement passé — donc trop tard, et jamais dans une revue de code :

  * deux cartes qui se chevauchent : Metabase les repousse à l'affichage, dans
    un ordre que le code ne décide pas. La disposition versionnée cesse alors de
    décrire ce que l'utilisateur voit ;
  * un titre trop long pour sa carte : il est tronqué, et une tuile de synthèse
    tronquée n'indique plus de quel chiffre il s'agit ;
  * une requête visant une table gold qui n'existe pas : la carte affiche une
    erreur au lieu d'un indicateur.

Ces tests les attrapent à la seconde, sans Docker.
"""

from __future__ import annotations

import re

import pytest

from eds.metabase_content import DASHBOARDS
from eds.transform import EXPECTED_TABLES

# Largeur de la grille Metabase.
GRILLE = 24

# Caractères lisibles par colonne de grille, mesuré à l'écran : une tuile de
# quatre colonnes en tient treize, une de cinq colonnes dix-sept. Au-delà,
# Metabase coupe le titre avec une ellipse.
CARACTERES_PAR_COLONNE = 3.4

# Base gold interrogée par chaque tableau de bord.
BASE_PAR_DASHBOARD = {
    "pilotage": "eds_gold_pilotage",
    "recherche": "eds_gold_recherche",
}


def _cartes(cle: str) -> list[dict]:
    return DASHBOARDS[cle]["cards"]


def _rectangle(carte: dict) -> tuple[int, int, int, int]:
    """(gauche, haut, droite, bas), bornes exclues à droite et en bas."""
    return (
        carte["col"],
        carte["row"],
        carte["col"] + carte["size_x"],
        carte["row"] + carte["size_y"],
    )


def _se_chevauchent(a: dict, b: dict) -> bool:
    g1, h1, d1, b1 = _rectangle(a)
    g2, h2, d2, b2 = _rectangle(b)
    return g1 < d2 and g2 < d1 and h1 < b2 and h2 < b1


def _titre(carte: dict) -> str:
    return carte.get("name") or "(bloc de texte)"


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_aucune_carte_ne_se_chevauche(cle: str):
    cartes = _cartes(cle)
    collisions = [
        f"« {_titre(a)} » et « {_titre(b)} »"
        for i, a in enumerate(cartes)
        for b in cartes[i + 1 :]
        if _se_chevauchent(a, b)
    ]
    assert not collisions, f"{cle} : cartes superposées — {', '.join(collisions)}"


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_aucune_carte_ne_deborde_de_la_grille(cle: str):
    for carte in _cartes(cle):
        gauche, _, droite, _ = _rectangle(carte)
        assert gauche >= 0, f"{cle} : « {_titre(carte)} » commence hors grille"
        assert droite <= GRILLE, (
            f"{cle} : « {_titre(carte)} » déborde ({droite} > {GRILLE} colonnes)"
        )


def test_les_tuiles_de_synthese_couvrent_toute_la_largeur():
    """Cinq tuiles alignées : la bande doit faire exactement 24 colonnes.

    Une bande incomplète laisse un vide à droite ; une bande trop large repousse
    la dernière tuile à la ligne suivante.
    """
    tuiles = [c for c in _cartes("pilotage") if c.get("display") == "scalar"]
    assert len(tuiles) == 5
    assert {c["row"] for c in tuiles} == {2}, "les tuiles doivent être sur une seule ligne"
    assert sum(c["size_x"] for c in tuiles) == GRILLE
    assert len({c["size_y"] for c in tuiles}) == 1, "hauteurs inégales : la bande serait crantée"

    # Elles doivent aussi être jointives, sans trou entre deux colonnes.
    debuts = sorted((c["col"], c["size_x"]) for c in tuiles)
    attendu = 0
    for col, largeur in debuts:
        assert col == attendu, f"trou ou recouvrement à la colonne {attendu}"
        attendu += largeur


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_chaque_ligne_de_la_grille_est_pleine(cle: str):
    """Toute la largeur est occupée, sur toute la hauteur — ni trou, ni bande orpheline.

    C'est la traduction vérifiable de « le tableau de bord prend toute la page » :
    combinée à l'absence de chevauchement, cette règle garantit que les cartes
    pavent exactement la grille.
    """
    cartes = _cartes(cle)
    hauteur = max(c["row"] + c["size_y"] for c in cartes)

    for ligne in range(hauteur):
        occupation = sum(c["size_x"] for c in cartes if c["row"] <= ligne < c["row"] + c["size_y"])
        assert occupation == GRILLE, (
            f"{cle} : la ligne {ligne} occupe {occupation} colonnes sur {GRILLE} — "
            "vide à droite, ou bande incomplète"
        )


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_les_titres_des_tuiles_tiennent_dans_leur_carte(cle: str):
    """La contrainte porte sur la largeur réelle de la carte, pas sur un maximum fixe.

    C'est le mode d'échec qui s'était produit : les cinq tuiles avaient été
    raccourcies sous un seuil unique, mais la plus étroite avait hérité du titre
    le plus long et restait tronquée.
    """
    for carte in _cartes(cle):
        if carte.get("display") != "scalar":
            continue
        nom = carte["name"]
        budget = int(carte["size_x"] * CARACTERES_PAR_COLONNE)
        assert len(nom) <= budget, (
            f"{cle} : « {nom} » ({len(nom)} caractères) sera tronqué dans une carte "
            f"de {carte['size_x']} colonnes ({budget} caractères) — raccourcir le nom, "
            "élargir la carte, ou déplacer le détail dans la description"
        )


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_chaque_carte_de_donnees_est_documentee(cle: str):
    """La description est la seule place où la définition d'un indicateur tient."""
    for carte in _cartes(cle):
        if carte.get("kind") == "text":
            continue
        assert carte.get("description", "").strip(), f"{cle} : « {_titre(carte)} » sans description"


@pytest.mark.parametrize("cle", sorted(DASHBOARDS))
def test_les_requetes_ne_visent_que_des_tables_existantes(cle: str):
    """Garde-fou entre la restitution et le modèle : les deux doivent bouger ensemble.

    Renommer une table gold sans toucher au dashboard produirait une carte en
    erreur, visible seulement en ouvrant l'interface.
    """
    connues = set(EXPECTED_TABLES[BASE_PAR_DASHBOARD[cle]])
    for carte in _cartes(cle):
        if carte.get("kind") == "text":
            continue
        referencees = set(re.findall(r"\bFROM\s+([a-z_][a-z0-9_]*)", carte["sql"]))
        inconnues = referencees - connues
        assert not inconnues, (
            f"{cle} : « {_titre(carte)} » interroge {sorted(inconnues)}, "
            f"absent de EXPECTED_TABLES[{BASE_PAR_DASHBOARD[cle]!r}]"
        )
