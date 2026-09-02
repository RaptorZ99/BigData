"""Transformations bronze → silver → gold, exécutées dans ClickHouse par dbt.

Python n'orchestre que l'invocation : aucune ligne de données métier ne remonte
côté client. Les couches silver et gold sont reconstruites intégralement à chaque
run (matérialisation `table`), ce qui les rend déterministes et rejouables — à ce
volume le coût est négligeable, et le gain en reproductibilité est ce qu'on veut
d'un entrepôt évalué sur la fiabilité de ses chiffres.

Pourquoi dbt plutôt que des scripts SQL numérotés :

* l'ordre d'exécution découle des `ref()` au lieu d'un préfixe de fichier — la
  règle « ce script en dernier car il recopie le rapport qualité » disparaît ;
* la déduplication des séjours et du monitoring est écrite **une** fois, en
  modèle éphémère, au lieu d'être copiée dans le fait et dans ses rejets ;
* `dbt build` construit **et** teste : une règle métier violée fait échouer le
  run, donc suspend la publication, exactement comme un fichier en échec.

Ce que dbt ne remplace pas : `ops.quality_report`. Un test répond « ça passe ou
ça casse » ; le rapport qualité répond « 6 797 lues, 6 729 conservées, 68
écartées par Q2 ». Le rapport est donc lui-même un modèle dbt (`models/ops/`).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from clickhouse_connect.driver.client import Client

from eds.config import PROJECT_ROOT
from eds.logging_setup import get_logger

log = get_logger(__name__)

DBT_DIR = PROJECT_ROOT / "dbt"

# dbt écrit ses artefacts dans `target/` du projet, sauf si `DBT_TARGET_PATH` en
# décide autrement — ce que fait l'image du pipeline, dont le répertoire applicatif
# n'est pas garanti inscriptible. Chercher le fichier produit au mauvais endroit
# faisait échouer la publication de la documentation alors que dbt avait réussi.
DBT_TARGET_DIR = Path(os.environ.get("DBT_TARGET_PATH") or DBT_DIR / "target")

# Événements dbt jugés dignes de la console : la version de l'adaptateur et la
# ligne de synthèse finale. Le détail modèle par modèle part en DEBUG — visible
# avec `eds run --verbose`, et de toute façon conservé par dbt dans
# `dbt/logs/dbt.log`. Sans ce filtre, un run afficherait deux fois quatre-vingt-dix
# lignes : celles de dbt et leur copie relayée.
_EVENEMENTS_NOTABLES = {"MainReportVersion", "StatsLine", "FinishedRunningStats"}

_NIVEAUX = {"info": log.info, "warn": log.warning, "error": log.error}

# Séquences de couleur ANSI : lisibles dans un terminal, illisibles dans un
# fichier de log ou dans Log Analytics.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class TransformError(RuntimeError):
    """Échec de la construction des couches dérivées."""


# Tables que les couches dérivées doivent contenir après un run réussi.
# Sert de contrôle de complétude : une table manquante signale une
# transformation interrompue. La liste est vérifiée contre les modèles dbt par
# `tests/test_dbt_project.py` — elles ne peuvent pas diverger en silence.
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
    ),
    "eds_gold_pilotage": (
        "kpi_dms_service",
        "kpi_urgences_jour",
        "kpi_readmissions_30j",
        "kpi_readmissions_service",
        "kpi_alertes_jour",
        "kpi_alertes_service",
        "kpi_activite_service",
        "kpi_flux",
        "kpi_synthese",
        "kpi_qualite_pipeline",
        "kpi_ingestion",
    ),
    "eds_gold_recherche": (
        "prevalence_pathologie",
        "cohorte_demographie",
        "cohorte_demographie_globale",
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

    Ce contrôle porte sur l'entrepôt réel, pas sur le manifeste dbt : c'est
    l'état des données qui décide, pas ce que dbt croit avoir construit.
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


def _relay(event: Any) -> None:
    """Reverse un événement dbt dans le journal du pipeline.

    Les deux systèmes partagent ainsi un seul fichier de log, et le `run_id`
    injecté par `logging_setup` relie la sortie de dbt à `ops.pipeline_runs` —
    y compris dans Log Analytics une fois le pipeline en exécution planifiée.
    """
    message = _ANSI.sub("", event.info.msg or "").strip()
    if not message:
        return
    if event.info.level in ("warn", "error"):
        _NIVEAUX[event.info.level]("dbt · %s", message)
    elif event.info.name in _EVENEMENTS_NOTABLES:
        log.info("dbt · %s", message)
    else:
        log.debug("dbt · %s", message)


def _echecs(resultat: Any) -> list[str]:
    """Nœuds dbt en erreur, sous une forme lisible dans un message d'exception."""
    noeuds = getattr(resultat.result, "results", None) or []
    return [
        f"{noeud.node.name} ({noeud.status}) : {(noeud.message or '').splitlines()[0][:200]}"
        for noeud in noeuds
        if str(noeud.status) in ("error", "fail")
    ]


def build(run_id: str, target: str = "local", *, select: str | None = None) -> None:
    """Construit et teste silver, gold et le rapport qualité, en une passe.

    `dbt build` entrelace modèles et tests selon le graphe : un test qui échoue
    empêche la construction de ce qui en dépend. C'est ce qui fait de la qualité
    une condition de publication, et non un contrôle a posteriori.

    ⚠ On ne passe **jamais** `--full-refresh` à dbt. `eds run --full-refresh`
    signifie « ré-ingérer tous les jours depuis la source » ; côté dbt, la même
    option détruirait l'historique de `ops.quality_report`, seul modèle
    incrémental du projet. Les 26 autres sont matérialisés en `table` et donc
    reconstruits de toute façon.
    """
    # Import local : dbt est un extra (`uv sync --extra dbt`). Le socle de
    # `make demo` n'a pas à le tirer tant qu'aucune transformation n'est lancée.
    from dbt.cli.main import dbtRunner

    log.info("Construction des couches dérivées (dbt · cible %s)…", target)

    arguments = [
        "build",
        # dbt n'imprime plus lui-même : c'est `_relay` qui décide ce qui remonte,
        # et à quel niveau. Sans cela chaque ligne apparaîtrait en double.
        "--quiet",
        "--no-use-colors",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--target",
        target,
        "--vars",
        json.dumps({"run_id": run_id}),
    ]
    if select:
        arguments += ["--select", select]

    resultat = dbtRunner(callbacks=[_relay]).invoke(arguments)

    if not resultat.success:
        details = _echecs(resultat) or [str(resultat.exception or "cause inconnue")]
        raise TransformError(
            "dbt a échoué — les couches dérivées conservent leur état précédent. "
            + " | ".join(details)
        )

    log.info("Couches silver, gold et rapport qualité construits et testés.")


def dbt_docs(target: str = "local") -> Path:
    """Génère la documentation dbt en un fichier HTML autonome.

    `--static` produit un `static_index.html` unique, sans dépendance externe :
    un seul objet à publier, et il s'ouvre depuis un disque comme depuis un
    site statique.
    """
    from dbt.cli.main import dbtRunner

    resultat = dbtRunner(callbacks=[_relay]).invoke(
        [
            "docs",
            "generate",
            "--static",
            "--quiet",
            "--no-use-colors",
            "--project-dir",
            str(DBT_DIR),
            "--profiles-dir",
            str(DBT_DIR),
            "--target",
            target,
        ]
    )
    if not resultat.success:
        raise TransformError(
            f"Génération de la documentation dbt impossible : {resultat.exception}"
        )

    page = DBT_TARGET_DIR / "static_index.html"
    if not page.is_file():
        raise TransformError(f"dbt n'a pas produit {page}")
    return page


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
