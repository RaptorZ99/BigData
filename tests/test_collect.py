"""La collecte doit produire un lake déjà dépourvu de données identifiantes."""

from __future__ import annotations

import re

from eds import storage
from eds.collect import checksum, collect, discover
from eds.config import Config
from eds.pseudo import PSEUDO_PATTERN, pseudonymize_id

IPP_PATTERN = re.compile(r"IPP\d+")


def _zones(config: Config):
    """Les deux zones de la cible locale : dépôt du CHU et lake."""
    return storage.for_source(config), storage.for_lake(config)


def _collect_all(config: Config) -> dict[str, str]:
    """Exécute la collecte et renvoie le contenu du lake par domaine."""
    depot, lake = _zones(config)
    contents = {}
    for source in discover(depot):
        collect(source, depot, lake, config)
        contents[source.domain] = lake.read_text(source)
    return contents


def test_le_lake_ne_contient_aucune_donnee_identifiante(config: Config):
    """Contrôle central du projet : NIR, nom, prénom et IPP ne sortent pas de la source."""
    contents = _collect_all(config)

    for domain, text in contents.items():
        assert "MARTIN" not in text, domain
        assert "Claire" not in text, domain
        assert "199017512345678" not in text, domain
        assert not IPP_PATTERN.search(text), f"identifiant en clair dans {domain}"
        for column in ("nir", "nom", "prenom", "birth_date"):
            assert column not in text.splitlines()[0], f"{column} présent dans l'en-tête {domain}"


def test_la_date_de_naissance_est_reduite_a_l_annee(config: Config):
    contents = _collect_all(config)
    lines = contents["patients"].strip().splitlines()

    assert lines[0] == "patient_pseudo,birth_year,sex,region_code"
    assert lines[1].split(",")[1] == "1990"
    assert "1990-01-15" not in contents["patients"]


def test_le_sexe_est_normalise(config: Config):
    """Le 'm' minuscule de la source ressort en 'M'."""
    contents = _collect_all(config)
    sexes = [line.split(",")[2] for line in contents["patients"].strip().splitlines()[1:]]
    assert sexes == ["F", "M", "F"]


def test_la_jointure_patients_sejours_est_preservee(config: Config):
    """Le même IPP donne le même pseudonyme dans les deux fichiers."""
    contents = _collect_all(config)
    attendu = pseudonymize_id("IPP0000001", config.salt)

    patients_pseudos = {
        line.split(",")[0] for line in contents["patients"].strip().splitlines()[1:]
    }
    sejours_pseudos = {line.split(",")[1] for line in contents["sejours"].strip().splitlines()[1:]}

    assert attendu in patients_pseudos
    assert attendu in sejours_pseudos
    assert sejours_pseudos <= patients_pseudos
    assert all(PSEUDO_PATTERN.match(p) for p in patients_pseudos)


def test_la_collecte_est_deterministe(config: Config):
    """Rejouer une collecte réécrit exactement le même contenu (idempotence)."""
    premier = _collect_all(config)
    second = _collect_all(config)
    assert premier == second


def test_les_anomalies_ne_sont_pas_filtrees_a_la_collecte(config: Config):
    """Le lake reste une copie fidèle : le tri qualité appartient à la couche silver."""
    contents = _collect_all(config)
    lignes_sejours = contents["sejours"].strip().splitlines()[1:]

    assert len(lignes_sejours) == 3, "aucun séjour ne doit être écarté à la collecte"
    assert any(",2026-08-25 10:15:00," in ligne for ligne in lignes_sejours)


def test_le_checksum_source_est_calcule(config: Config):
    """Il sert de clé d'idempotence dans ops.ingest_log."""
    depot, _ = _zones(config)
    empreintes = [checksum(source, depot) for source in discover(depot)]
    assert all(len(e) == 64 for e in empreintes)
    assert len(set(empreintes)) == len(empreintes)


def test_le_checksum_ne_depend_pas_de_la_collecte(config: Config):
    """Il porte sur le fichier source : on peut décider avant de copier quoi que ce soit.

    C'est ce qui rend un run sans nouveau dépôt réellement gratuit — ni copie,
    ni repseudonymisation.
    """
    depot, lake = _zones(config)
    source = next(iter(discover(depot)))
    avant = checksum(source, depot)
    collect(source, depot, lake, config)
    assert checksum(source, depot) == avant
    assert not (config.lake_dir / "inexistant").exists()
