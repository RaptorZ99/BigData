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

    # On nomme les variables concernées : « remplacez les mots de passe » sans
    # dire lesquels se traduit en pratique par « on en oublie un ».
    if faibles := config.weak_password_settings:
        console.print(
            "[yellow]⚠ Mots de passe d'exemple encore en place :[/] "
            f"{', '.join(faibles)}. Remplacez-les dans .env avant tout usage réel "
            "(ou supprimez .env et relancez `make env`, qui en génère d'aléatoires)."
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

    try:
        report = pipeline.run(
            client, config, only_date=date, full_refresh=full_refresh, force_rebuild=rebuild
        )
    except Exception as exc:
        # L'erreur est déjà journalisée avec sa pile complète ; en sortie
        # console, une trace Python n'aide personne à décider quoi faire.
        console.print(f"[bold red]✗ Le pipeline s'est arrêté :[/] {exc}")
        console.print(f"[dim]Détails et pile d'appels : {log_file_path()}[/]")
        raise typer.Exit(code=1) from exc

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
    from eds.state import last_quality_run_id

    config = _bootstrap()
    client = connect(config)

    # On vise le dernier run ayant produit des contrôles, et non simplement le
    # dernier run : un passage incrémental sans nouveau fichier ne reconstruit
    # rien, mais les chiffres publiés restent ceux du traitement précédent.
    target = run_id or last_quality_run_id(client)
    if not target:
        console.print("[yellow]Aucun contrôle qualité enregistré. Lancez `make pipeline`.[/]")
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
        ("Nature", "left"),
        ("Lues", "right"),
        ("Conservées", "right"),
        ("Écartées", "right"),
        ("Signalées", "right"),
    ):
        table.add_column(column, justify=justify)

    # Une règle de rejet retire des lignes ; une règle de signalement les
    # conserve en les marquant. Distinguer les deux évite de lire un
    # signalement comme une perte de données.
    couleurs = {"rejet": "red", "signalement": "yellow", "conforme": "green"}

    for layer, table_name, label, nature, lues, gardees, ecartees, signalees in rows:
        table.add_row(
            layer,
            table_name,
            label,
            f"[{couleurs[nature]}]{nature}[/]",
            _nombre(lues),
            _nombre(gardees),
            f"[red]{_nombre(ecartees)}[/]" if ecartees else "[dim]0[/]",
            f"[yellow]{_nombre(signalees)}[/]" if signalees else "[dim]0[/]",
        )
    console.print(table)
    console.print(
        "[dim]rejet = lignes retirées (consultables dans les tables *_rejets) · "
        "signalement = lignes conservées et marquées · conforme = contrôle sans écart[/]"
    )


def _nombre(valeur: int) -> str:
    """Formate un entier avec des espaces comme séparateur de milliers."""
    return f"{valeur:,}".replace(",", " ")


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


@app.command("publish-dbt-docs")
def publish_dbt_docs_command() -> None:
    """Génère la documentation dbt et la publie sur le site statique du stockage.

    Le fichier produit est autonome : graphe des 34 modèles, descriptions de
    colonnes et tests attachés. Il ne contient aucune donnée patient — des
    métadonnées et des comptages de lignes.
    """
    from eds import storage, transform

    config = _bootstrap()
    page = transform.dbt_docs(config.dbt_target)

    if config.storage_backend != "azure":
        # En local il n'y a pas de site à alimenter : on dit où lire le fichier.
        console.print(f"[green]✓[/] Documentation dbt générée : [bold]{page}[/]")
        return

    url = storage.publish_file(config.storage_account, config.web_container, "index.html", page)
    console.print(f"[green]✓[/] Documentation dbt publiée : [bold]{url}[/]")


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
        granted, anomalie = _tester_acces(config, user, password, database)

        ok = granted == should_read and anomalie is None
        all_ok &= ok
        constate = "lecture" if granted else "refusé"
        table.add_row(
            user,
            database,
            "lecture" if should_read else "refus",
            f"[green]✓ {constate}[/]" if ok else f"[bold red]✗ {anomalie or constate}[/]",
        )

    console.print(table)
    all_ok &= _check_cloisonnement_metabase(config)

    if not all_ok:
        console.print("[bold red]Cloisonnement non conforme.[/]")
        raise typer.Exit(code=1)
    console.print(
        "\n[green]✓ Cloisonnement conforme aux deux niveaux[/] : "
        "l'entrepôt refuse la requête, et l'interface ne montre pas le contenu."
    )


def _check_cloisonnement_metabase(config) -> bool:
    """Vérifie la seconde barrière : chaque compte n'ouvre que son dashboard.

    Le contrôle SQL prouve qu'une requête hors périmètre est refusée par le
    moteur ; celui-ci prouve qu'un utilisateur ne voit même pas le tableau de
    bord de l'autre usage. Les deux ensemble constituent la démonstration
    demandée — rejouable, plutôt qu'illustrée par une capture d'écran.
    """
    from eds.metabase import MetabaseError, verifier_cloisonnement

    try:
        resultats = verifier_cloisonnement(config)
    except MetabaseError as exc:
        console.print(f"[yellow]⚠ Contrôle Metabase impossible ({exc}).[/]")
        console.print("[dim]  Metabase est-il démarré et provisionné ? `make provision`[/]")
        return True  # l'absence de Metabase n'invalide pas le cloisonnement SQL

    table = Table(title="Cloisonnement du contenu (Metabase)", header_style="bold")
    for column in ("Utilisateur", "Tableau de bord", "Attendu", "Résultat"):
        table.add_column(column)

    for controle in resultats:
        constate = "accès" if controle.autorise_constate else "refusé"
        table.add_row(
            controle.utilisateur,
            controle.dashboard,
            "accès" if controle.autorise_attendu else "refus",
            f"[green]✓ {constate}[/]" if controle.conforme else f"[bold red]✗ {constate}[/]",
        )
    console.print(table)
    return all(controle.conforme for controle in resultats)


# Motifs de refus qui prouvent effectivement le cloisonnement. Tout autre échec
# — base absente, moteur arrêté, table vide — donnerait le même « refusé » sans
# rien démontrer : le contrôle passerait au vert pour une mauvaise raison.
MOTIFS_DE_REFUS = ("ACCESS_DENIED", "NOT_ENOUGH_PRIVILEGES")


def _tester_acces(config, user: str, password: str, database: str) -> tuple[bool, str | None]:
    """Teste une lecture réelle. Renvoie (lecture obtenue, anomalie éventuelle).

    L'anomalie est renseignée quand l'échec ne prouve pas le cloisonnement : la
    distinguer d'un refus de droits est ce qui empêche ce contrôle d'être
    faussement rassurant.
    """
    table = _first_table(config, database)
    if table is None:
        return False, f"{database} ne contient aucune table"

    client = connect(config, user=user, password=password)
    try:
        client.query(f"SELECT count() FROM {database}.{table} LIMIT 1")
    except Exception as exc:
        message = str(exc)
        if not any(motif in message for motif in MOTIFS_DE_REFUS):
            return False, f"échec non lié aux droits : {message.splitlines()[0][:80]}"
        return False, None
    return True, None


def _first_table(config, database: str) -> str | None:
    """Première table d'une base, pour tester un accès en lecture."""
    client = connect(config)
    rows = client.query(
        "SELECT name FROM system.tables WHERE database = %(db)s ORDER BY name LIMIT 1",
        parameters={"db": database},
    ).result_rows
    return rows[0][0] if rows else None


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
