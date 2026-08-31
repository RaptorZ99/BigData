"""Accès à ClickHouse : c'est le seul endroit qui parle au moteur.

Le pipeline envoie du SQL et récupère des comptages ; il ne rapatrie jamais les
données métier côté Python. Toute la transformation reste dans l'entrepôt.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from eds.config import PROJECT_ROOT, Config
from eds.logging_setup import get_logger

log = get_logger(__name__)

SQL_DIR = PROJECT_ROOT / "sql"

# Découpage naïf mais suffisant : nos scripts n'utilisent ni chaîne contenant un
# point-virgule ni bloc procédural. On retire d'abord les commentaires de ligne.
_LINE_COMMENT = re.compile(r"--[^\n]*")


class WarehouseError(RuntimeError):
    """Erreur d'exécution côté entrepôt."""


@dataclass(frozen=True, slots=True)
class TableCount:
    database: str
    table: str
    rows: int


def connect(config: Config, *, user: str | None = None, password: str | None = None) -> Client:
    """Ouvre une connexion HTTP à ClickHouse.

    `user` / `password` permettent de se connecter avec un compte restreint —
    utile pour prouver le cloisonnement dans les tests.
    """
    return clickhouse_connect.get_client(
        host=config.clickhouse_host,
        port=config.clickhouse_port,
        username=user or config.clickhouse_user,
        password=password if password is not None else config.clickhouse_password,
        connect_timeout=10,
        send_receive_timeout=300,
    )


def split_statements(script: str) -> Iterator[str]:
    """Découpe un script SQL en instructions exécutables."""
    for raw in _LINE_COMMENT.sub("", script).split(";"):
        statement = raw.strip()
        if statement:
            yield statement


def render(script: str, params: dict[str, str] | None = None) -> str:
    """Substitue les paramètres `{nom}` d'un script.

    Les valeurs proviennent de la configuration ou de chemins internes, jamais
    d'une saisie utilisateur : le risque d'injection est nul ici, mais on
    échappe tout de même les apostrophes par principe.
    """
    if not params:
        return script
    safe = {key: str(value).replace("'", "''") for key, value in params.items()}
    return script.format(**safe)


def execute_script(client: Client, path: Path, params: dict[str, str] | None = None) -> None:
    """Exécute un fichier SQL, instruction par instruction."""
    script = render(path.read_text(encoding="utf-8"), params)
    for statement in split_statements(script):
        try:
            client.command(statement)
        except Exception as exc:
            raise WarehouseError(f"Échec dans {path.name} : {exc}") from exc
    log.debug("Script exécuté : %s", path.relative_to(SQL_DIR))


def execute_directory(client: Client, name: str, params: dict[str, str] | None = None) -> None:
    """Exécute tous les scripts d'un dossier `sql/`, dans l'ordre alphabétique.

    Le préfixe numérique des fichiers porte donc l'ordre des dépendances.
    """
    directory = SQL_DIR / name
    if not directory.is_dir():
        raise WarehouseError(f"Dossier SQL introuvable : {directory}")

    for path in sorted(directory.glob("*.sql")):
        execute_script(client, path, params)


def scalar(client: Client, query: str) -> Any:
    """Renvoie la première colonne de la première ligne (ou None)."""
    result = client.query(query).result_rows
    return result[0][0] if result and result[0] else None


def count_rows(client: Client, database: str, table: str) -> int:
    value = scalar(client, f"SELECT count() FROM {database}.{table}")
    return int(value or 0)


def table_counts(client: Client, database: str) -> list[TableCount]:
    """Comptages de toutes les tables d'une base, pour `eds status`."""
    rows = client.query(
        "SELECT name FROM system.tables WHERE database = %(db)s AND engine NOT LIKE '%%View' "
        "ORDER BY name",
        parameters={"db": database},
    ).result_rows
    return [TableCount(database, name, count_rows(client, database, name)) for (name,) in rows]
