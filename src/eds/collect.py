"""Collecte : dépôt du CHU (lecture seule) → zone de travail (lake).

C'est ici — et nulle part ailleurs — que la pseudonymisation a lieu : le lake ne
contient déjà plus aucune donnée directement identifiante, et tout ce qui suit
(bronze, silver, gold, dashboards) travaille sur des pseudonymes.

Les fichiers sont traités **en flux, ligne à ligne** : la mémoire reste
constante quelle que soit la taille du dépôt.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from eds.config import Config
from eds.logging_setup import get_logger
from eds.pseudo import generalize_birth_date, pseudonymize_id

log = get_logger(__name__)

DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHUNK_SIZE = 1024 * 1024

# Colonnes directement ou indirectement identifiantes : elles ne sont jamais
# écrites dans le lake. La liste sert de garde-fou vérifié — `_verifier_sortie`
# refuse d'écrire un fichier qui en contiendrait une.
FORBIDDEN_COLUMNS = ("nir", "nom", "prenom", "birth_date", "patient_id")


@dataclass(frozen=True, slots=True)
class SourceFile:
    """Un fichier déposé par le CHU, pour un domaine et un jour donnés."""

    domain: str
    ingest_date: str
    path: Path
    relative_name: str

    @property
    def label(self) -> str:
        return f"{self.domain}/{self.ingest_date}/{self.relative_name}"


@dataclass(frozen=True, slots=True)
class CollectResult:
    """Résultat de la copie pseudonymisée d'un fichier vers le lake."""

    source: SourceFile
    lake_path: Path
    rows: int


def checksum(source: SourceFile) -> str:
    """Empreinte du fichier source : clé d'idempotence de l'ingestion.

    Calculée **avant** toute copie, pour pouvoir décider s'il y a lieu de
    travailler : un fichier inchangé ne doit être ni recopié ni repseudonymisé.
    """
    digest = hashlib.sha256()
    with source.path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(target: Path, write: Callable[[Path], int]) -> int:
    """Écrit via un fichier temporaire puis renomme : jamais de fichier tronqué.

    Un crash en cours d'écriture laisse le lake dans son état précédent plutôt
    qu'avec un fichier partiel qui serait chargé silencieusement.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        rows = write(tmp)
        os.replace(tmp, target)
        return rows
    finally:
        tmp.unlink(missing_ok=True)


def _copy_verbatim(source: Path, target: Path) -> int:
    """Copie sans transformation (aucune donnée identifiante dans ces fichiers)."""

    def write(tmp: Path) -> int:
        shutil.copyfile(source, tmp)
        return -1  # comptage délégué à ClickHouse au chargement

    return _atomic_write(target, write)


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
    source: Path,
    target: Path,
    fieldnames: list[str],
    transform: Callable[[dict[str, str]], dict[str, object] | None],
) -> int:
    """Réécrit un CSV ligne à ligne en appliquant `transform`."""
    _verifier_sortie(fieldnames)

    def write(tmp: Path) -> int:
        rows = 0
        with (
            source.open("r", encoding="utf-8", newline="") as fin,
            tmp.open("w", encoding="utf-8", newline="") as fout,
        ):
            writer = csv.DictWriter(fout, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for record in csv.DictReader(fin):
                transformed = transform(record)
                if transformed is not None:
                    writer.writerow(transformed)
                    rows += 1
        return rows

    return _atomic_write(target, write)


def _collect_patients(source: Path, target: Path, config: Config) -> int:
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
        source, target, ["patient_pseudo", "birth_year", "sex", "region_code"], transform
    )


def _collect_sejours(source: Path, target: Path, config: Config) -> int:
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

    return _transform_csv(source, target, fieldnames, transform)


# Un domaine = un motif de fichiers déposés + la façon de les amener au lake.
_COLLECTORS: dict[str, Callable[[Path, Path, Config], int]] = {
    "patients": _collect_patients,
    "sejours": _collect_sejours,
}

EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    "patients": ("patients.csv",),
    "sejours": ("sejours.csv",),
    "diagnostics": ("diagnostics.json",),
    "monitoring": ("monitoring.parquet",),
    "referentiels": ("services.csv", "cim10.csv"),
}


def discover(config: Config) -> Iterator[SourceFile]:
    """Parcourt le dépôt du CHU et énumère les fichiers présents, par jour.

    L'ordre est déterministe (domaine, puis jour) pour des runs reproductibles.
    Les fichiers attendus mais absents sont signalés par `missing_files`.
    """
    for domain, day, path, filename, present in _scan(config):
        if present:
            yield SourceFile(domain, day, path, filename)


def missing_files(config: Config) -> list[str]:
    """Fichiers attendus pour un jour déposé, mais absents du dépôt.

    Un jour partiellement déposé n'est pas un run normal : l'entrepôt serait
    reconstruit sur une source amputée. Le pipeline le traite donc comme un
    échec, afin que le code de sortie alerte plutôt que de laisser croire à une
    exécution nominale.
    """
    return [
        f"{domain}/{day}/{filename}"
        for domain, day, _path, filename, present in _scan(config)
        if not present
    ]


def _scan(config: Config) -> Iterator[tuple[str, str, Path, str, bool]]:
    """Énumère tous les fichiers attendus, présents ou non."""
    for domain in sorted(EXPECTED_FILES):
        domain_dir = config.source_dir / domain
        if not domain_dir.is_dir():
            log.warning("Domaine absent du dépôt : %s", domain)
            continue

        for day_dir in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
            if not DAY_PATTERN.match(day_dir.name):
                log.warning("Dossier ignoré (nom de jour invalide) : %s", day_dir)
                continue

            for filename in EXPECTED_FILES[domain]:
                path = day_dir / filename
                yield domain, day_dir.name, path, filename, path.is_file()


def collect(source: SourceFile, config: Config) -> CollectResult:
    """Copie un fichier vers le lake en appliquant la pseudonymisation requise."""
    lake_path = config.lake_dir / source.domain / source.ingest_date / source.relative_name

    collector = _COLLECTORS.get(source.domain)
    if collector is None:
        rows = _copy_verbatim(source.path, lake_path)
        log.debug("Copie brute : %s", source.label)
    else:
        rows = collector(source.path, lake_path, config)
        log.debug("Copie pseudonymisée : %s (%s lignes)", source.label, rows)

    return CollectResult(source=source, lake_path=lake_path, rows=rows)


def lake_relative_path(source: SourceFile) -> str:
    """Chemin du fichier tel que ClickHouse le voit sous `user_files/`."""
    return f"lake/{source.domain}/{source.ingest_date}/{source.relative_name}"
