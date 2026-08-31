"""Chargement du lake vers la couche bronze.

Le moteur lit les fichiers lui-même (`file()` sur le lake monté sous
`user_files/`) : Python n'ouvre aucun fichier de données, il envoie du SQL.

L'idempotence tient en deux instructions : `DROP PARTITION` du jour concerné,
puis `INSERT`. Rejouer un jour ne duplique donc jamais rien, et un échec en
cours de route ne laisse pas de demi-partition — le prochain run la reprend
depuis zéro.
"""

from __future__ import annotations

import time

from clickhouse_connect.driver.client import Client

from eds.collect import SourceFile, lake_relative_path
from eds.logging_setup import get_logger
from eds.warehouse import SQL_DIR, WarehouseError, execute_script

log = get_logger(__name__)

_LOAD_ATTEMPTS = 4
_LOAD_RETRY_DELAY = 0.5

# Domaine → (table bronze, script de chargement).
# Les référentiels partagent le domaine `referentiels` : on distingue au fichier.
_TARGETS: dict[str, tuple[str, str]] = {
    "patients": ("patients", "02_load_patients.sql"),
    "sejours": ("sejours", "03_load_sejours.sql"),
    "diagnostics": ("diagnostics", "04_load_diagnostics.sql"),
    "monitoring": ("monitoring", "05_load_monitoring.sql"),
    "services.csv": ("services", "06_load_services.sql"),
    "cim10.csv": ("cim10", "07_load_cim10.sql"),
}


def target_for(source: SourceFile) -> tuple[str, str]:
    """Table bronze et script de chargement associés à un fichier source."""
    # Les référentiels partagent un domaine mais visent deux tables distinctes :
    # c'est le nom du fichier qui tranche.
    key = source.relative_name if source.domain == "referentiels" else source.domain

    target = _TARGETS.get(key)
    if target is None:
        raise WarehouseError(f"Aucun chargement défini pour {source.label}")
    return target


def _insert_with_retry(client: Client, script_name: str, lake_path: str, ingest_date: str) -> None:
    """Exécute l'INSERT, en tolérant une visibilité retardée du fichier.

    Le lake est un dossier de l'hôte monté dans le conteneur. Sur macOS, la
    propagation d'un fichier fraîchement écrit vers le montage n'est pas
    instantanée : le moteur peut le déclarer absent une fraction de seconde
    après sa création. Quelques tentatives espacées suffisent, et une vraie
    absence finit malgré tout par remonter l'erreur.
    """
    script = SQL_DIR / "15_bronze_load" / script_name
    params = {"source_file": lake_path, "ingest_date": ingest_date}

    for tentative in range(_LOAD_ATTEMPTS):
        try:
            execute_script(client, script, params)
            return
        except WarehouseError as exc:
            derniere = tentative == _LOAD_ATTEMPTS - 1
            if derniere or "FILE_DOESNT_EXIST" not in str(exc):
                raise
            log.debug("Fichier pas encore visible côté moteur, nouvelle tentative : %s", lake_path)
            time.sleep(_LOAD_RETRY_DELAY)


def drop_partition(client: Client, table: str, ingest_date: str) -> None:
    """Vide la partition du jour : sans effet si elle n'existe pas encore."""
    client.command(
        f"ALTER TABLE eds_bronze.{table} DROP PARTITION %(day)s", parameters={"day": ingest_date}
    )


def load(client: Client, source: SourceFile) -> int:
    """Charge un fichier du lake dans bronze, de façon idempotente.

    Renvoie le nombre de lignes présentes dans la partition après chargement.
    """
    table, script_name = target_for(source)
    lake_path = lake_relative_path(source)

    drop_partition(client, table, source.ingest_date)
    _insert_with_retry(client, script_name, lake_path, source.ingest_date)

    rows = client.query(
        f"SELECT count() FROM eds_bronze.{table} WHERE _ingest_date = %(day)s",
        parameters={"day": source.ingest_date},
    ).result_rows[0][0]

    log.info(
        "bronze.%-12s %s → %s lignes", table, source.ingest_date, f"{rows:,}".replace(",", " ")
    )
    return int(rows)
