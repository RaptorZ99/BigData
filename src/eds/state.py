"""État de l'ingestion : ce qui a déjà été chargé, et ce qu'il reste à faire.

L'incrémentalité repose sur `ops.ingest_log` : un fichier déjà ingéré avec le
même checksum est sauté ; un fichier modifié, un jour nouveau ou un échec
précédent sont retraités. Aucun état n'est stocké sur le disque local — la
source de vérité est l'entrepôt lui-même, donc `eds status` dit la vérité même
après un `git clone` sur une autre machine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from clickhouse_connect.driver.client import Client

from eds.collect import SourceFile
from eds.logging_setup import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestedFile:
    """Ligne du journal d'ingestion, telle que relue depuis l'entrepôt."""

    domain: str
    ingest_date: str
    source_file: str
    sha256: str
    status: str


# Colonnes de ops.pipeline_runs. `updated_at` porte la version : la clôture
# d'un run doit toujours l'emporter sur son ouverture.
_RUN_COLUMNS = [
    "run_id",
    "started_at",
    "finished_at",
    "status",
    "days_processed",
    "files_ok",
    "files_failed",
    "error",
    "updated_at",
]


def new_run_id() -> str:
    """Identifiant court et lisible, repris dans les logs et les tables ops."""
    return uuid.uuid4().hex[:12]


def load_ingest_log(client: Client) -> dict[tuple[str, str, str], IngestedFile]:
    """Relit le journal d'ingestion, indexé par (domaine, jour, fichier).

    `FINAL` force la fusion du ReplacingMergeTree : on lit l'état courant, pas
    l'historique des versions.
    """
    rows = client.query(
        """
        SELECT domain, toString(ingest_date), source_file, sha256, toString(status)
        FROM ops.ingest_log FINAL
        """
    ).result_rows

    return {
        (domain, day, source_file): IngestedFile(domain, day, source_file, sha256, status)
        for domain, day, source_file, sha256, status in rows
    }


def needs_ingestion(
    source: SourceFile,
    checksum: str,
    journal: dict[tuple[str, str, str], IngestedFile],
) -> tuple[bool, str]:
    """Décide si un fichier doit être (re)chargé, et pourquoi.

    La raison est journalisée : elle rend l'incrémentalité vérifiable plutôt que
    magique.
    """
    key = (source.domain, source.ingest_date, source.relative_name)
    previous = journal.get(key)

    if previous is None:
        return True, "nouveau ou rejeu demandé"
    if previous.status != "success":
        return True, f"reprise après échec ({previous.status})"
    if previous.sha256 != checksum:
        return True, "fichier modifié à la source"
    return False, "déjà ingéré"


def record_ingestion(
    client: Client,
    *,
    run_id: str,
    source: SourceFile,
    checksum: str,
    rows_source: int,
    rows_loaded: int,
    status: str,
    error: str = "",
    started_at: datetime,
) -> None:
    """Écrit (ou remplace) l'entrée du journal pour un fichier."""
    client.insert(
        "ops.ingest_log",
        [
            [
                source.domain,
                _as_date(source.ingest_date),
                source.relative_name,
                checksum,
                rows_source,
                rows_loaded,
                status,
                error[:2000],
                run_id,
                started_at,
                datetime.now(),
            ]
        ],
        column_names=[
            "domain",
            "ingest_date",
            "source_file",
            "sha256",
            "rows_source",
            "rows_loaded",
            "status",
            "error",
            "run_id",
            "started_at",
            "finished_at",
        ],
    )


def start_run(client: Client, run_id: str) -> datetime:
    started_at = datetime.now()
    client.insert(
        "ops.pipeline_runs",
        [[run_id, started_at, None, "running", "", 0, 0, "", datetime.now()]],
        column_names=_RUN_COLUMNS,
    )
    return started_at


def finish_run(
    client: Client,
    *,
    run_id: str,
    started_at: datetime,
    status: str,
    days: list[str],
    files_ok: int,
    files_failed: int,
    error: str = "",
) -> None:
    """Clôt le run. La ligne remplace la précédente (ReplacingMergeTree)."""
    fin = datetime.now()
    client.insert(
        "ops.pipeline_runs",
        [
            [
                run_id,
                started_at,
                fin,
                status,
                ", ".join(sorted(days)),
                files_ok,
                files_failed,
                error[:2000],
                fin,
            ]
        ],
        column_names=_RUN_COLUMNS,
    )


def last_quality_run_id(client: Client) -> str | None:
    """Dernier run ayant réellement produit un rapport qualité.

    Un run incrémental sans nouveau fichier ne reconstruit rien, donc n'écrit
    aucun contrôle. Le rapport pertinent reste alors celui du dernier
    traitement effectif : c'est lui qui justifie les chiffres actuellement
    publiés dans les tableaux de bord.
    """
    rows = client.query(
        """
        SELECT q.run_id
        FROM ops.quality_report AS q
        INNER JOIN (
            SELECT run_id, started_at FROM ops.pipeline_runs FINAL
        ) AS r ON r.run_id = q.run_id
        GROUP BY q.run_id, r.started_at
        ORDER BY r.started_at DESC
        LIMIT 1
        """
    ).result_rows
    return rows[0][0] if rows else None


def _as_date(day: str):
    from datetime import date

    return date.fromisoformat(day)
