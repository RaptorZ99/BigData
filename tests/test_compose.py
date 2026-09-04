"""La pile Docker Compose d'une copie du dépôt ne doit jamais se mêler à celle d'une autre.

Un `name:` figé dans `docker-compose.yml`, ou des `container_name:`, font que deux
copies du projet sur une même machine — un clone et une archive dézippée — désignent la
même pile : la seconde s'attache aux conteneurs et aux volumes de la première, y compris
à son Metabase, dont le mot de passe n'est pas celui de son propre `.env`. C'est arrivé.
Le nom du projet doit dériver du dossier, et les conteneurs porter le nom de leur service.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_le_projet_compose_n_a_pas_de_nom_fige():
    pile = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "name" not in pile, "un `name:` figé fait partager la pile entre deux copies du dépôt"


def test_aucun_conteneur_n_a_de_nom_fige():
    pile = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    figes = [svc for svc, defn in pile["services"].items() if "container_name" in defn]
    assert not figes, f"`container_name` figé pour {figes} : deux copies entreraient en collision"


def test_les_services_gardent_leurs_noms():
    """Le Makefile, la CI et les tests parlent aux services par leur nom, pas au conteneur."""
    pile = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert {"clickhouse", "metabase", "scheduler"} <= set(pile["services"])
