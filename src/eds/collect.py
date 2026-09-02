"""Collecte : dépôt du CHU (lecture seule) → zone de travail (lake).

C'est ici — et nulle part ailleurs — que la pseudonymisation a lieu : le lake ne
contient déjà plus aucune donnée directement identifiante, et tout ce qui suit
(bronze, silver, gold, dashboards) travaille sur des pseudonymes.

Les fichiers sont traités **en flux, ligne à ligne, de la source vers le lake** :
la mémoire reste constante quelle que soit la taille du dépôt, et surtout
l'identité en clair ne devient jamais un fichier intermédiaire. Le module ne sait
pas si les deux zones sont des dossiers ou des conteneurs de stockage objet —
c'est le rôle de `storage.py`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import IO

from eds.config import Config
from eds.logging_setup import get_logger
from eds.pseudo import generalize_birth_date, pseudonymize_id
from eds.storage import SourceFile, Storage, copy_stream

log = get_logger(__name__)

# Colonnes directement ou indirectement identifiantes : elles ne sont jamais
# écrites dans le lake. La liste sert de garde-fou vérifié — `_verifier_sortie`
# refuse d'écrire un fichier qui en contiendrait une.
FORBIDDEN_COLUMNS = ("nir", "nom", "prenom", "birth_date", "patient_id")


@dataclass(frozen=True, slots=True)
class CollectResult:
    """Résultat de la copie pseudonymisée d'un fichier vers le lake."""

    source: SourceFile
    rows: int


def checksum(source: SourceFile, storage: Storage) -> str:
    """Empreinte du fichier source : clé d'idempotence de l'ingestion.

    Calculée **avant** toute copie, pour pouvoir décider s'il y a lieu de
    travailler : un fichier inchangé ne doit être ni recopié ni repseudonymisé.
    """
    return storage.fingerprint(source)


def _verifier_sortie(fieldnames: list[str]) -> None:
    """Refuse d'écrire un fichier dont l'en-tête porterait une colonne interdite.

    Garde-fou de dernier recours : une évolution maladroite d'un collecteur ne
    doit pas pouvoir faire entrer une donnée identifiante dans le lake.
    """
    interdites = sorted(set(fieldnames) & set(FORBIDDEN_COLUMNS))
    if interdites:
        raise ValueError(
            "Colonne(s) identifiante(s) dans la sortie du lake : "
            f"{', '.join(interdites)}. Elles ne doivent jamais quitter la source."
        )


def _transform_csv(
    entree: IO[bytes],
    sortie: IO[bytes],
    fieldnames: list[str],
    transform: Callable[[dict[str, str]], dict[str, object] | None],
) -> int:
    """Réécrit un CSV ligne à ligne en appliquant `transform`.

    Les deux flux sont habillés en texte sans tampon intermédiaire : une ligne
    lue est une ligne transformée puis écrite. Rien n'accumule.
    """
    _verifier_sortie(fieldnames)

    lecteur = io.TextIOWrapper(entree, encoding="utf-8", newline="")
    ecrivain = io.TextIOWrapper(sortie, encoding="utf-8", newline="", write_through=True)
    writer = csv.DictWriter(ecrivain, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    rows = 0
    for record in csv.DictReader(lecteur):
        transformed = transform(record)
        if transformed is not None:
            writer.writerow(transformed)
            rows += 1

    ecrivain.flush()
    # `detach` évite que la fermeture du wrapper ferme le flux sous-jacent :
    # c'est au `Storage` de décider quand le fichier est publié.
    ecrivain.detach()
    return rows


def _collect_patients(entree: IO[bytes], sortie: IO[bytes], config: Config) -> int:
    """Pseudonymise l'identité patient et généralise la date de naissance.

    Sortie : patient_pseudo, birth_year, sex, region_code.
    Le NIR, le nom et le prénom ne sont simplement jamais écrits.
    """

    def transform(record: dict[str, str]) -> dict[str, object]:
        return {
            "patient_pseudo": pseudonymize_id(record["patient_id"], config.salt),
            "birth_year": generalize_birth_date(record["birth_date"]),
            "sex": (record.get("sex") or "").strip().upper(),
            "region_code": (record.get("region_code") or "").strip(),
        }

    return _transform_csv(
        entree, sortie, ["patient_pseudo", "birth_year", "sex", "region_code"], transform
    )


def _collect_sejours(entree: IO[bytes], sortie: IO[bytes], config: Config) -> int:
    """Remplace la référence patient par le même pseudonyme (jointure préservée)."""
    fieldnames = [
        "stay_id",
        "patient_pseudo",
        "service_code",
        "admission_ts",
        "discharge_ts",
        "admission_mode",
        "discharge_mode",
    ]

    def transform(record: dict[str, str]) -> dict[str, object]:
        row: dict[str, object] = {
            name: (record.get(name) or "").strip() for name in fieldnames if name in record
        }
        row["patient_pseudo"] = pseudonymize_id(record["patient_id"], config.salt)
        return row

    return _transform_csv(entree, sortie, fieldnames, transform)


# Un domaine = un motif de fichiers déposés + la façon de les amener au lake.
_COLLECTORS: dict[str, Callable[[IO[bytes], IO[bytes], Config], int]] = {
    "patients": _collect_patients,
    "sejours": _collect_sejours,
}

# Flux quotidiens : chaque jour déposé doit contenir ce fichier. Un jour partiel n'est
# pas un run normal, il alerte (voir `missing_files`).
EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    "patients": ("patients.csv",),
    "sejours": ("sejours.csv",),
    "diagnostics": ("diagnostics.json",),
    "monitoring": ("monitoring.parquet",),
    # Évolution du 29 août 2026 : nouveau flux de faits.
    "actes": ("actes.parquet",),
}

# Nomenclatures : le CHU ne dépose que celles qui changent — les services et la CIM-10
# le premier jour, la description des services et la CCAM le 29 août. Un jour donné,
# chaque fichier est donc facultatif. Ce qui est anormal, c'est un jour de dépôt qui
# n'en contient aucun de reconnu, ou un fichier inconnu qui serait passé sous silence.
REFERENTIEL_DOMAIN = "referentiels"
REFERENTIEL_FILES: tuple[str, ...] = (
    "services.csv",
    "cim10.csv",
    "description_service.csv",
    "ccam.csv",
)
AUCUNE_NOMENCLATURE = "(aucune nomenclature reconnue)"


def discover(storage: Storage) -> Iterator[SourceFile]:
    """Parcourt le dépôt du CHU et énumère les fichiers présents, par jour.

    L'ordre est déterministe (domaine, puis jour) pour des runs reproductibles.
    Les fichiers attendus mais absents sont signalés par `missing_files`.
    """
    for source, present in _scan(storage):
        if present:
            yield source


def missing_files(storage: Storage) -> list[str]:
    """Fichiers attendus pour un jour déposé, mais absents du dépôt.

    Un jour partiellement déposé n'est pas un run normal : l'entrepôt serait
    reconstruit sur une source amputée. Le pipeline le traite donc comme un
    échec, afin que le code de sortie alerte plutôt que de laisser croire à une
    exécution nominale.

    Pour les nomenclatures, le manque est un jour de dépôt sans aucun fichier
    reconnu : le CHU a créé le dossier, mais rien dedans ne peut être chargé.
    """
    return [source.label for source, present in _scan(storage) if not present]


def _scan(storage: Storage) -> Iterator[tuple[SourceFile, bool]]:
    """Énumère tous les fichiers attendus, présents ou non."""
    for domain in sorted({*EXPECTED_FILES, REFERENTIEL_DOMAIN}):
        jours = storage.days(domain)
        if not jours:
            log.warning("Domaine absent du dépôt : %s", domain)
            continue

        for day in jours:
            if domain == REFERENTIEL_DOMAIN:
                yield from _scan_referentiels(storage, day)
                continue
            for filename in EXPECTED_FILES[domain]:
                source = SourceFile(domain, day, filename)
                yield source, storage.exists(source)


def _scan_referentiels(storage: Storage, day: str) -> Iterator[tuple[SourceFile, bool]]:
    """Un jour de nomenclatures : ce qui est reconnu se charge, le reste se signale."""
    presents = storage.list_files(REFERENTIEL_DOMAIN, day)
    reconnus = [nom for nom in REFERENTIEL_FILES if nom in presents]

    for inconnu in sorted(set(presents) - set(REFERENTIEL_FILES)):
        log.warning(
            "Fichier non reconnu dans %s/%s, ignoré : %s (attendus : %s)",
            REFERENTIEL_DOMAIN,
            day,
            inconnu,
            ", ".join(REFERENTIEL_FILES),
        )

    if not reconnus:
        yield SourceFile(REFERENTIEL_DOMAIN, day, AUCUNE_NOMENCLATURE), False
        return

    for nom in reconnus:
        yield SourceFile(REFERENTIEL_DOMAIN, day, nom), True


def collect(source: SourceFile, depot: Storage, lake: Storage, config: Config) -> CollectResult:
    """Copie un fichier vers le lake en appliquant la pseudonymisation requise."""
    collector = _COLLECTORS.get(source.domain)

    with depot.open_read(source) as entree, lake.open_write(source) as sortie:
        if collector is None:
            copy_stream(entree, sortie)
            rows = -1  # comptage délégué à ClickHouse au chargement
            log.debug("Copie brute : %s", source.label)
        else:
            rows = collector(entree, sortie, config)
            log.debug("Copie pseudonymisée : %s (%s lignes)", source.label, rows)

    return CollectResult(source=source, rows=rows)
