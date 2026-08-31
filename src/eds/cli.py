"""Interface en ligne de commande du pipeline EDS.

Point d'entrée unique pour l'exploitation : ingestion, état, provisionnement et
rapport qualité. Toutes les commandes sont rejouables sans effet de bord.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from eds import pipeline, transform
from eds.config import ConfigError, load_config
from eds.logging_setup import get_logger, log_file_path, setup_logging
from eds.warehouse import connect, table_counts

app = typer.Typer(
    help="EDS CHU — pipeline d'ingestion et de restitution.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
log = get_logger(__name__)


def _bootstrap(verbose: bool = False):
    """Charge la configuration et prépare la journalisation, ou sort proprement."""
    setup_logging(verbose)
    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[bold red]Configuration invalide[/] : {exc}")
        raise typer.Exit(code=2) from exc

    if config.uses_demo_salt:
        console.print(
            "[yellow]⚠ Sel de démonstration utilisé.[/] Pour un usage réel : "
            "openssl rand -hex 32 → EDS_SALT dans .env"
        )
    return config


@app.command("run")
def run_command(
    date: Annotated[
        str | None,
        typer.Option(
            "--date", help="Rejoue un jour précis (AAAA-MM-JJ), pour reprise sur incident."
        ),
    ] = None,
    full_refresh: Annotated[
        bool, typer.Option("--full-refresh", help="Recharge tous les jours depuis la source.")
    ] = False,
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Reconstruit silver et gold sans réingérer (après modification du SQL).",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Journalisation détaillée.")
    ] = False,
) -> None:
    """Exécute le pipeline (incrémental par défaut)."""
    config = _bootstrap(verbose)
    client = connect(config)

    report = pipeline.run(
        client, config, only_date=date, full_refresh=full_refresh, force_rebuild=rebuild
    )

    if report.files_ok:
        console.print(
            f"[green]✓[/] {report.files_ok} fichier(s) chargé(s) · "
            f"jours : {', '.join(sorted(report.days))}"
        )
    if report.files_skipped:
        console.print(f"[dim]↷ {report.files_skipped} fichier(s) déjà ingéré(s), ignoré(s).[/]")
    if report.files_failed:
        console.print(f"[bold red]✗ {report.files_failed} fichier(s) en échec :[/]")
        for error in report.errors:
            console.print(f"  • {error}")
        console.print(f"[dim]Détails : {log_file_path()}[/]")
        raise typer.Exit(code=1)

    console.print(f"[green]Run {report.run_id} terminé ({report.status}).[/]")


@app.command("status")
def status_command() -> None:
    """Affiche l'état de l'ingestion et les volumétries par couche."""
    config = _bootstrap()
    client = connect(config)

    runs = client.query(
        """
        SELECT run_id, started_at, toString(status), days_processed, files_ok, files_failed
        FROM ops.pipeline_runs FINAL
        ORDER BY started_at DESC
        LIMIT 5
        """
    ).result_rows

    if runs:
        table = Table(title="Derniers runs", header_style="bold")
        for column in ("Run", "Démarré", "Statut", "Jours", "OK", "Échecs"):
            table.add_column(column)
        for run_id, started, status, days, ok, failed in runs:
            colour = {"success": "green", "failed": "red", "partial": "yellow"}.get(status, "white")
            table.add_row(
                run_id,
                str(started),
                f"[{colour}]{status}[/]",
                days or "-",
                str(ok),
                str(failed),
            )
        console.print(table)

    ingest = client.query(
        """
        SELECT domain, toString(ingest_date), source_file, rows_loaded, toString(status)
        FROM ops.ingest_log FINAL
        ORDER BY ingest_date, domain
        """
    ).result_rows

    if ingest:
        table = Table(title="Journal d'ingestion", header_style="bold")
        for column in ("Domaine", "Jour", "Fichier", "Lignes", "Statut"):
            table.add_column(column)
        for domain, day, source_file, rows, status in ingest:
            colour = "green" if status == "success" else "red"
            table.add_row(
                domain, day, source_file, f"{rows:,}".replace(",", " "), f"[{colour}]{status}[/]"
            )
        console.print(table)
    else:
        console.print("[yellow]Aucune ingestion enregistrée. Lancez `make pipeline`.[/]")
        return

    table = Table(title="Volumétrie par couche", header_style="bold")
    for column in ("Base", "Table", "Lignes"):
        table.add_column(column)
    for database in ("eds_bronze", "eds_silver", "eds_gold_pilotage", "eds_gold_recherche"):
        for entry in table_counts(client, database):
            table.add_row(entry.database, entry.table, f"{entry.rows:,}".replace(",", " "))
    console.print(table)


@app.command("quality")
def quality_command(
    run_id: Annotated[
        str | None, typer.Option("--run-id", help="Run à inspecter (dernier run par défaut).")
    ] = None,
) -> None:
    """Affiche le rapport qualité : lignes lues, conservées, écartées, par règle."""
    from eds.state import last_run_id

    config = _bootstrap()
    client = connect(config)

    target = run_id or last_run_id(client)
    if not target:
        console.print("[yellow]Aucun run enregistré.[/]")
        raise typer.Exit(code=1)

    rows = transform.quality_report(client, target)
    if not rows:
        console.print(f"[yellow]Aucun contrôle enregistré pour le run {target}.[/]")
        raise typer.Exit(code=1)

    table = Table(title=f"Rapport qualité — run {target}", header_style="bold")
    for column, justify in (
        ("Couche", "left"),
        ("Table", "left"),
        ("Contrôle", "left"),
        ("Entrées", "right"),
        ("Conservées", "right"),
        ("Écartées", "right"),
    ):
        table.add_column(column, justify=justify)

    for layer, table_name, _rule, label, rows_in, rows_kept, rows_rejected, _details in rows:
        rejected = f"[red]{rows_rejected:,}[/]" if rows_rejected else "[green]0[/]"
        table.add_row(
            layer,
            table_name,
            label,
            f"{rows_in:,}".replace(",", " "),
            f"{rows_kept:,}".replace(",", " "),
            rejected.replace(",", " "),
        )
    console.print(table)


@app.command("provision-warehouse")
def provision_warehouse_command() -> None:
    """Crée bases, tables et comptes cloisonnés dans ClickHouse. Idempotent."""
    config = _bootstrap()
    client = connect(config)
    pipeline.provision_warehouse(client, config)
    console.print("[green]✓[/] Entrepôt provisionné (bases, tables bronze, ops, RBAC).")


@app.command("provision-metabase")
def provision_metabase_command() -> None:
    """Crée connexions, groupes, utilisateurs, permissions et dashboards Metabase."""
    from eds import metabase

    config = _bootstrap()
    metabase.provision(config)


@app.command("check-cloisonnement")
def check_cloisonnement_command() -> None:
    """Vérifie que chaque compte de restitution ne voit que sa propre base."""
    config = _bootstrap()

    scenarios = [
        ("chu_pilotage", config.pilotage_password, "eds_gold_pilotage", True),
        ("chu_pilotage", config.pilotage_password, "eds_gold_recherche", False),
        ("chu_recherche", config.recherche_password, "eds_gold_recherche", True),
        ("chu_recherche", config.recherche_password, "eds_gold_pilotage", False),
        ("chu_recherche", config.recherche_password, "eds_silver", False),
    ]

    table = Table(title="Cloisonnement des accès (ClickHouse)", header_style="bold")
    for column in ("Compte", "Base cible", "Attendu", "Résultat"):
        table.add_column(column)

    all_ok = True
    for user, password, database, should_read in scenarios:
        client = connect(config, user=user, password=password)
        try:
            client.query(f"SELECT count() FROM {database}.{_first_table(config, database)} LIMIT 1")
            granted = True
        except Exception:
            granted = False

        ok = granted == should_read
        all_ok &= ok
        table.add_row(
            user,
            database,
            "lecture" if should_read else "refus",
            f"[green]✓ {'lecture' if granted else 'refusé'}[/]"
            if ok
            else f"[bold red]✗ {'lecture' if granted else 'refusé'}[/]",
        )

    console.print(table)
    if not all_ok:
        console.print("[bold red]Cloisonnement non conforme.[/]")
        raise typer.Exit(code=1)
    console.print("[green]✓ Cloisonnement conforme : chaque usage ne voit que ses données.[/]")


def _first_table(config, database: str) -> str:
    """Première table d'une base, pour tester un accès en lecture."""
    client = connect(config)
    rows = client.query(
        "SELECT name FROM system.tables WHERE database = %(db)s ORDER BY name LIMIT 1",
        parameters={"db": database},
    ).result_rows
    return rows[0][0] if rows else "unknown"


@app.command("reset")
def reset_command(
    yes: Annotated[bool, typer.Option("--yes", help="Confirme la suppression.")] = False,
) -> None:
    """Vide l'entrepôt et la zone de travail (le dépôt du CHU reste intact)."""
    if not yes:
        console.print("[yellow]Ajoutez --yes pour confirmer.[/]")
        raise typer.Exit(code=1)

    import shutil

    config = _bootstrap()
    client = connect(config)
    for database in (
        "eds_bronze",
        "eds_silver",
        "eds_gold_pilotage",
        "eds_gold_recherche",
        "ops",
    ):
        client.command(f"DROP DATABASE IF EXISTS {database}")
    shutil.rmtree(config.lake_dir, ignore_errors=True)

    console.print("[green]✓[/] Entrepôt et zone de travail réinitialisés.")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompu.[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()
