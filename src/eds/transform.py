"""Transformations bronze → silver → gold, exécutées dans ClickHouse.

Python n'orchestre que l'ordre des scripts : aucune ligne de données métier ne
remonte côté client. Les couches silver et gold sont reconstruites intégralement
à chaque run (`CREATE OR REPLACE TABLE … AS SELECT`), ce qui les rend
déterministes et rejouables — à ce volume le coût est négligeable, et le gain en
reproductibilité est ce qu'on veut pour un entrepôt évalué sur la fiabilité de
ses chiffres.
"""

from __future__ import annotations

from clickhouse_connect.driver.client import Client

from eds.logging_setup import get_logger
from eds.warehouse import execute_directory

log = get_logger(__name__)


# Tables que les couches dérivées doivent contenir après un run réussi.
# Sert de contrôle de complétude : une table manquante signale une
# transformation interrompue.
EXPECTED_TABLES: dict[str, tuple[str, ...]] = {
    "eds_silver": (
        "dim_patient",
        "dim_service",
        "dim_cim10",
        "fact_sejour",
        "fact_diagnostic",
        "fact_monitoring",
        "sejours_rejets",
        "monitoring_rejets",
        "cellules_demographie",
    ),
    "eds_gold_pilotage": (
        "kpi_dms_service",
        "kpi_urgences_jour",
        "kpi_readmissions_30j",
        "kpi_activite_service",
        "kpi_flux",
        "kpi_alertes_monitoring",
        "kpi_synthese",
        "kpi_qualite_pipeline",
        "kpi_ingestion",
    ),
    "eds_gold_recherche": (
        "cohorte_pathologie",
        "prevalence_pathologie",
        "cohorte_demographie_globale",
        "cohorte_demographie",
        "cohorte_demographie_region",
        "k_anonymat_controle",
    ),
}


def missing_tables(client: Client) -> list[str]:
    """Tables attendues mais absentes des couches dérivées."""
    existing = {
        f"{database}.{name}"
        for database, name in client.query(
            "SELECT database, name FROM system.tables WHERE database IN %(dbs)s",
            parameters={"dbs": tuple(EXPECTED_TABLES)},
        ).result_rows
    }
    return [
        f"{database}.{table}"
        for database, tables in EXPECTED_TABLES.items()
        for table in tables
        if f"{database}.{table}" not in existing
    ]


def is_stale(client: Client) -> bool:
    """Indique si les couches dérivées ne reflètent plus l'état de bronze.

    Cas typique : un run où le chargement bronze a réussi mais la transformation
    a échoué. Sans ce contrôle, le run suivant conclurait « aucun nouveau
    fichier » et laisserait l'entrepôt avec des tables absentes ou périmées. Le
    pipeline se répare donc tout seul au run d'après.
    """
    absentes = missing_tables(client)
    if absentes:
        log.warning("Tables manquantes : %s", ", ".join(absentes))
        return True

    silver_at = _scalar(client, "SELECT max(_built_at) FROM eds_silver.fact_sejour")
    if silver_at is None:
        return True

    # Gold est-elle en retard sur silver ? Ce contrôle attrape le cas où la
    # construction de silver a réussi puis celle de gold a échoué : sans lui, le
    # run suivant conclurait « tout est à jour » et les tableaux de bord
    # figeraient les chiffres de l'avant-dernier traitement.
    gold_at = _scalar(client, "SELECT max(_built_at) FROM eds_gold_pilotage.kpi_synthese")
    if gold_at is None or gold_at < silver_at:
        log.warning("Couche gold en retard sur silver : reconstruction.")
        return True

    loaded_at = _scalar(
        client,
        """
        SELECT max(_loaded_at) FROM (
            SELECT max(_loaded_at) AS _loaded_at FROM eds_bronze.sejours
            UNION ALL SELECT max(_loaded_at) FROM eds_bronze.patients
            UNION ALL SELECT max(_loaded_at) FROM eds_bronze.diagnostics
            UNION ALL SELECT max(_loaded_at) FROM eds_bronze.monitoring
        )
        """,
    )
    return loaded_at is not None and loaded_at > silver_at


def _scalar(client: Client, query: str):
    """Exécute une requête scalaire ; renvoie None si la table n'existe pas encore."""
    try:
        rows = client.query(query).result_rows
    except Exception:
        return None
    return rows[0][0] if rows and rows[0] else None


def build_silver(client: Client, run_id: str) -> None:
    """Reconstruit la constellation silver et son rapport qualité.

    L'ordre des scripts porte les dépendances : dimensions, puis fact_sejour
    (dont dérivent les rejets), puis les deux autres faits qui en propagent les
    clés dimensionnelles.
    """
    log.info("Construction de la couche silver…")
    execute_directory(client, "20_silver", {"run_id": run_id})
    log.info("Silver construite.")


def build_gold(client: Client, run_id: str) -> None:
    """Reconstruit les deux bases gold, une par usage."""
    log.info("Construction des couches gold…")
    execute_directory(client, "30_gold", {"run_id": run_id})
    log.info("Gold construites.")


def quality_report(client: Client, run_id: str) -> list[tuple]:
    """Relit le rapport qualité d'un run, pour affichage."""
    return client.query(
        """
        SELECT
            layer,
            table_name,
            rule_label,
            multiIf(rows_rejected > 0, 'rejet',
                    rows_flagged  > 0, 'signalement',
                    'conforme')  AS nature,
            rows_in,
            rows_kept,
            rows_rejected,
            rows_flagged
        FROM ops.quality_report
        WHERE run_id = %(run_id)s
        ORDER BY layer, table_name, rule
        """,
        parameters={"run_id": run_id},
    ).result_rows
