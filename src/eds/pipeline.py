"""Orchestration d'un run : collecte → bronze → silver → gold, avec traçabilité.

Principes d'exploitation (partie « automatisation » du sujet) :

* **Incrémental** — seuls les fichiers nouveaux, modifiés ou en échec sont
  retraités ; le journal `ops.ingest_log` fait foi.
* **Robuste** — l'échec d'un fichier n'interrompt pas le run : les autres
  domaines continuent, l'erreur est journalisée, et le code de sortie est non
  nul pour qu'un cron puisse alerter.
* **Rejouable** — grâce au `DROP PARTITION`, relancer suffit à reprendre ; il
  n'y a jamais d'état intermédiaire à nettoyer à la main.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from clickhouse_connect.driver.client import Client

from eds import collect as collect_module
from eds import load_bronze, state, transform
from eds.config import Config
from eds.logging_setup import bind_run_id, get_logger
from eds.warehouse import execute_directory

log = get_logger(__name__)


@dataclass
class RunReport:
    """Résultat d'une exécution, tel que rapporté à l'utilisateur."""

    run_id: str
    days: set[str] = field(default_factory=set)
    files_ok: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    rebuilt: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.files_failed and self.files_ok:
            return "partial"
        if self.files_failed:
            return "failed"
        return "success"

    @property
    def has_changes(self) -> bool:
        return self.files_ok > 0


def provision_warehouse(client: Client, config: Config) -> None:
    """Crée bases, tables d'exploitation et comptes cloisonnés. Idempotent."""
    log.info("Provisionnement de l'entrepôt…")
    execute_directory(
        client,
        "00_init",
        {
            "pilotage_password": config.pilotage_password,
            "recherche_password": config.recherche_password,
        },
    )
    execute_directory(client, "10_bronze")
    log.info("Entrepôt prêt : bases, tables bronze, journal ops et comptes cloisonnés.")


def run(
    client: Client,
    config: Config,
    *,
    only_date: str | None = None,
    full_refresh: bool = False,
    force_rebuild: bool = False,
) -> RunReport:
    """Exécute un cycle complet d'ingestion et de transformation.

    `force_rebuild` reconstruit silver et gold sans réingérer : c'est le geste à
    faire après avoir modifié un script de transformation.
    """
    run_id = state.new_run_id()
    bind_run_id(run_id)
    report = RunReport(run_id=run_id)

    started_at = state.start_run(client, run_id)
    log.info("Run %s démarré (mode : %s)", run_id, _mode_label(only_date, full_refresh))

    try:
        # `--full-refresh` et `--date` sont des demandes explicites de rejeu :
        # on ignore alors le journal, sans quoi un fichier inchangé serait sauté
        # — précisément le cas d'une reprise après incident.
        journal = {} if (full_refresh or only_date) else state.load_ingest_log(client)
        _ingest(client, config, journal, report, only_date=only_date)

        # On reconstruit s'il y a du nouveau, mais aussi si les couches dérivées
        # sont en retard sur bronze : un run précédent a pu charger bronze puis
        # échouer en transformation. Le pipeline se remet ainsi d'aplomb seul.
        if report.has_changes or force_rebuild:
            _rebuild(client, run_id, report)
        elif transform.is_stale(client):
            log.warning("Couches dérivées en retard sur bronze : reconstruction.")
            _rebuild(client, run_id, report)
        else:
            log.info("Aucun nouveau fichier : les couches silver et gold sont à jour.")

    except Exception as exc:
        report.errors.append(str(exc))
        report.files_failed += 1
        state.finish_run(
            client,
            run_id=run_id,
            started_at=started_at,
            status="failed",
            days=sorted(report.days),
            files_ok=report.files_ok,
            files_failed=report.files_failed,
            error=str(exc),
        )
        log.exception("Run %s interrompu", run_id)
        raise

    state.finish_run(
        client,
        run_id=run_id,
        started_at=started_at,
        status=report.status,
        days=sorted(report.days),
        files_ok=report.files_ok,
        files_failed=report.files_failed,
        error=" | ".join(report.errors),
    )
    log.info(
        "Run %s terminé : %s (%d fichiers chargés, %d ignorés, %d en échec)",
        run_id,
        report.status,
        report.files_ok,
        report.files_skipped,
        report.files_failed,
    )
    return report


def _rebuild(client: Client, run_id: str, report: RunReport) -> None:
    """Reconstruit silver puis gold, et note que le run a produit des tables."""
    transform.build_silver(client, run_id)
    transform.build_gold(client, run_id)
    report.rebuilt = True


def _ingest(
    client: Client,
    config: Config,
    journal: dict,
    report: RunReport,
    *,
    only_date: str | None,
) -> None:
    """Collecte puis charge chaque fichier à traiter, en isolant les échecs."""
    fichiers = list(collect_module.discover(config))

    if only_date:
        fichiers = [f for f in fichiers if f.ingest_date == only_date]
        if not fichiers:
            # Le rejeu d'un jour est un geste de reprise sur incident : une faute
            # de frappe dans la date ne doit pas ressembler à une reprise réussie.
            jours = sorted({f.ingest_date for f in collect_module.discover(config)})
            raise ValueError(
                f"Aucun fichier déposé le {only_date}. "
                f"Jours disponibles : {', '.join(jours) or 'aucun'}"
            )

    for source in fichiers:
        file_started = datetime.now()
        try:
            # L'empreinte est calculée sur le fichier source, donc avant toute
            # copie : un fichier inchangé n'est ni recopié ni repseudonymisé.
            # Sur un dépôt volumineux, c'est ce qui rend le run à vide gratuit.
            empreinte = collect_module.checksum(source)

            do_load, reason = state.needs_ingestion(source, empreinte, journal)
            if not do_load:
                report.files_skipped += 1
                log.debug("%s : %s", source.label, reason)
                continue

            log.info("%s : %s", source.label, reason)
            result = collect_module.collect(source, config)
            rows_loaded = load_bronze.load(client, source)

            state.record_ingestion(
                client,
                run_id=report.run_id,
                source=source,
                checksum=empreinte,
                rows_source=result.rows,
                rows_loaded=rows_loaded,
                status="success",
                started_at=file_started,
            )
            report.files_ok += 1
            report.days.add(source.ingest_date)

        except Exception as exc:
            message = f"{source.label} : {exc}"
            report.errors.append(message)
            report.files_failed += 1
            log.error("Échec de chargement — %s", message)
            _record_failure(client, report.run_id, source, exc, file_started)


def _record_failure(client: Client, run_id: str, source, exc: Exception, started_at) -> None:
    """Journalise l'échec sans masquer l'erreur d'origine."""
    try:
        state.record_ingestion(
            client,
            run_id=run_id,
            source=source,
            checksum="",
            rows_source=-1,
            rows_loaded=-1,
            status="failed",
            error=str(exc),
            started_at=started_at,
        )
    except Exception:
        log.warning("Impossible de journaliser l'échec de %s", source.label)


def _mode_label(only_date: str | None, full_refresh: bool) -> str:
    if only_date:
        return f"rejeu du {only_date}"
    return "rechargement complet" if full_refresh else "incrémental"
