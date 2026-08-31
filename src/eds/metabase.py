"""Provisionnement automatique de Metabase par son API REST.

Objectif : après un `git clone`, `make demo` doit suffire à obtenir deux
dashboards prêts à l'emploi et un cloisonnement démontrable — sans le moindre
clic dans l'interface.

Tout est idempotent : chaque objet est recherché par son nom avant d'être créé,
si bien qu'on peut rejouer le provisionnement autant de fois qu'on veut.

Le cloisonnement est double :
  * dans Metabase, chaque groupe n'a accès qu'à une connexion ;
  * dans ClickHouse, chaque connexion utilise un compte SQL distinct qui ne
    possède le droit SELECT que sur sa propre base gold.
Le second niveau est celui qui compte : même une requête SQL écrite à la main
ne peut pas franchir la frontière.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests
from rich.console import Console

from eds.config import Config
from eds.logging_setup import get_logger
from eds.metabase_content import DASHBOARDS

log = get_logger(__name__)
console = Console()

_TIMEOUT = 30
_STARTUP_TIMEOUT = 300


class MetabaseError(RuntimeError):
    """Échec d'un appel à l'API Metabase."""


@dataclass(frozen=True, slots=True)
class Usage:
    """Un usage métier : une connexion, un groupe, un utilisateur, un dashboard."""

    key: str
    database_name: str
    clickhouse_db: str
    clickhouse_user: str
    group_name: str


USAGES = (
    Usage(
        key="pilotage",
        database_name="EDS — Pilotage hospitalier",
        clickhouse_db="eds_gold_pilotage",
        clickhouse_user="chu_pilotage",
        group_name="Pilotage hospitalier",
    ),
    Usage(
        key="recherche",
        database_name="EDS — Recherche clinique",
        clickhouse_db="eds_gold_recherche",
        clickhouse_user="chu_recherche",
        group_name="Recherche clinique",
    ),
)


class MetabaseClient:
    """Client minimal de l'API Metabase, authentifié par jeton de session."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    # ── Transport ───────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method, f"{self.base_url}{path}", timeout=_TIMEOUT, **kwargs
        )
        if not response.ok:
            raise MetabaseError(f"{method} {path} → {response.status_code} : {response.text[:500]}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict | None = None) -> Any:
        return self._request("POST", path, json=payload or {})

    def put(self, path: str, payload: dict | None = None) -> Any:
        return self._request("PUT", path, json=payload or {})

    # ── Cycle de vie ────────────────────────────────────────────────────────
    def wait_until_ready(self) -> None:
        """Metabase met une bonne minute à démarrer : on attend son API."""
        deadline = time.time() + _STARTUP_TIMEOUT
        while time.time() < deadline:
            try:
                if self.session.get(f"{self.base_url}/api/health", timeout=5).ok:
                    log.info("Metabase répond.")
                    return
            except requests.RequestException:
                pass
            time.sleep(3)
        raise MetabaseError(
            f"Metabase n'a pas démarré en {_STARTUP_TIMEOUT} s. "
            "Vérifiez `docker compose ps` et `docker compose logs metabase`."
        )

    def authenticate(self, email: str, password: str) -> None:
        """Réalise le setup initial, ou se connecte si l'instance existe déjà.

        Le jeton de setup n'est délivré qu'une fois par instance : on bascule
        donc sur une authentification classique dès le second passage.
        """
        properties = self.get("/api/session/properties") or {}
        setup_token = properties.get("setup-token")
        # `setup-token` reste exposé après coup : c'est `has-user-setup` qui dit
        # si l'instance a déjà son premier utilisateur.
        deja_configure = bool(properties.get("has-user-setup"))

        if setup_token and not deja_configure:
            log.info("Première configuration de Metabase…")
            session = self.post(
                "/api/setup",
                {
                    "token": setup_token,
                    "user": {
                        "first_name": "Administrateur",
                        "last_name": "EDS",
                        "email": email,
                        "password": password,
                        "site_name": "EDS CHU",
                    },
                    "prefs": {
                        "site_name": "EDS CHU",
                        "site_locale": "fr",
                        "allow_tracking": False,
                    },
                    "database": None,
                },
            )
            token = session.get("id") if isinstance(session, dict) else None
        else:
            log.info("Instance déjà configurée : connexion.")
            token = self.post("/api/session", {"username": email, "password": password})["id"]

        if not token:
            raise MetabaseError("Authentification Metabase impossible (aucun jeton de session).")
        self.session.headers["X-Metabase-Session"] = token


# ── Objets Metabase, tous créés de façon idempotente ────────────────────────
def _find_by(items: list[dict], field: str, value: str) -> dict | None:
    return next((item for item in items if item.get(field) == value), None)


def ensure_database(client: MetabaseClient, usage: Usage, config: Config) -> int:
    """Crée (ou met à jour) la connexion ClickHouse dédiée à un usage."""
    password = config.pilotage_password if usage.key == "pilotage" else config.recherche_password
    details = {
        "host": config.metabase_clickhouse_host,
        "port": config.metabase_clickhouse_port,
        "user": usage.clickhouse_user,
        "password": password,
        "dbname": usage.clickhouse_db,
        "scan-all-databases": False,
        "ssl": False,
    }

    databases = (client.get("/api/database") or {}).get("data", [])
    existing = _find_by(databases, "name", usage.database_name)

    if existing:
        client.put(f"/api/database/{existing['id']}", {"details": details, "engine": "clickhouse"})
        log.info("Connexion mise à jour : %s", usage.database_name)
        return existing["id"]

    created = client.post(
        "/api/database",
        {
            "name": usage.database_name,
            "engine": "clickhouse",
            "details": details,
            "is_full_sync": True,
        },
    )
    log.info("Connexion créée : %s", usage.database_name)
    return created["id"]


def ensure_group(client: MetabaseClient, name: str) -> int:
    groups = client.get("/api/permissions/group") or []
    existing = _find_by(groups, "name", name)
    if existing:
        return existing["id"]
    created = client.post("/api/permissions/group", {"name": name})
    log.info("Groupe créé : %s", name)
    return created["id"]


def ensure_user(
    client: MetabaseClient, email: str, password: str, group_id: int, label: str
) -> int:
    """Crée l'utilisateur d'un usage et l'affecte à son groupe."""
    users = (client.get("/api/user") or {}).get("data", [])
    existing = _find_by(users, "email", email)

    if existing:
        client.put(
            f"/api/user/{existing['id']}",
            {"user_group_memberships": _memberships(group_id)},
        )
        return existing["id"]

    created = client.post(
        "/api/user",
        {
            "first_name": label,
            "last_name": "CHU",
            "email": email,
            "password": password,
            "user_group_memberships": _memberships(group_id),
        },
    )
    log.info("Utilisateur créé : %s", email)
    return created["id"]


def _memberships(group_id: int) -> list[dict]:
    """Appartenance au groupe métier, plus « All Users » (obligatoire)."""
    return [{"id": 1, "is_group_manager": False}, {"id": group_id, "is_group_manager": False}]


def ensure_collection(client: MetabaseClient, name: str, description: str) -> int:
    """Crée l'espace de contenu d'un usage (dashboard et questions associées)."""
    collections = client.get("/api/collection") or []
    existing = _find_by(collections, "name", name)
    if existing:
        return existing["id"]
    created = client.post("/api/collection", {"name": name, "description": description})
    log.info("Collection créée : %s", name)
    return created["id"]


def apply_data_permissions(client: MetabaseClient, mapping: dict[int, int]) -> None:
    """Restreint la construction de requêtes à la connexion de chaque groupe.

    Le graphe est versionné : Metabase refuse un PUT dont la `revision` n'est
    plus la dernière. On le relit donc juste avant d'écrire.

    Limite de l'édition open source : le blocage complet de la lecture
    (`view-data: blocked`) est réservé aux éditions payantes. On retire donc le
    droit de créer des requêtes sur les autres connexions, et c'est ClickHouse
    qui porte l'interdiction réelle — un compte SQL ne possède le droit SELECT
    que sur sa propre base gold.
    """
    graph = client.get("/api/permissions/graph")
    groups: dict[str, Any] = graph["groups"]
    known_databases = {db_id for entry in groups.values() for db_id in entry}
    known_databases |= {str(db_id) for db_id in mapping.values()}

    for group_id, database_id in mapping.items():
        entry = groups.setdefault(str(group_id), {})
        for db_id in known_databases:
            autorise = db_id == str(database_id)
            entry[db_id] = {
                "view-data": "unrestricted",
                "create-queries": "query-builder-and-native" if autorise else "no",
            }

    # « All Users » ne doit ouvrir aucun droit : tout utilisateur en fait partie.
    tous = groups.setdefault("1", {})
    for db_id in known_databases:
        tous[db_id] = {"view-data": "unrestricted", "create-queries": "no"}

    client.put("/api/permissions/graph", {"revision": graph["revision"], "groups": groups})
    log.info("Permissions données : chaque groupe ne peut interroger que sa connexion.")


def apply_collection_permissions(client: MetabaseClient, mapping: dict[int, int]) -> None:
    """Donne à chaque groupe l'accès à sa seule collection.

    C'est le mécanisme de cloisonnement du *contenu* disponible en édition open
    source : un utilisateur « recherche » ne voit tout simplement pas le
    dashboard de pilotage dans son interface.
    """
    graph = client.get("/api/collection/graph")
    groups: dict[str, Any] = graph["groups"]
    collection_ids = {str(collection_id) for collection_id in mapping.values()}

    for group_id, collection_id in mapping.items():
        entry = groups.setdefault(str(group_id), {})
        entry["root"] = "none"
        for other in collection_ids:
            entry[other] = "read" if other == str(collection_id) else "none"

    tous = groups.setdefault("1", {})
    tous["root"] = "none"
    for collection_id in collection_ids:
        tous[collection_id] = "none"

    client.put("/api/collection/graph", {"revision": graph["revision"], "groups": groups})
    log.info("Permissions contenu : chaque groupe ne voit que son propre dashboard.")


def ensure_card(
    client: MetabaseClient,
    database_id: int,
    collection_id: int,
    spec: dict,
    existing: dict[str, dict],
) -> int:
    """Crée ou met à jour une question SQL native.

    Les requêtes restent de simples SELECT sur les tables gold : toute la
    logique métier vit dans l'entrepôt, pas dans l'outil de restitution.
    """
    payload = {
        "name": spec["name"],
        "description": spec.get("description"),
        "display": spec["display"],
        "collection_id": collection_id,
        "visualization_settings": spec.get("visualization_settings", {}),
        "dataset_query": {
            "type": "native",
            "database": database_id,
            "native": {"query": spec["sql"], "template-tags": {}},
        },
    }

    previous = existing.get(spec["name"])
    if previous:
        client.put(f"/api/card/{previous['id']}", payload)
        return previous["id"]
    return client.post("/api/card", payload)["id"]


def ensure_dashboard(
    client: MetabaseClient, database_id: int, collection_id: int, spec: dict
) -> int:
    """Construit un dashboard complet : cartes, disposition, titres."""
    dashboards = client.get("/api/dashboard") or []
    existing = _find_by(dashboards, "name", spec["name"])

    payload = {
        "name": spec["name"],
        "description": spec["description"],
        "collection_id": collection_id,
    }
    if existing:
        dashboard_id = existing["id"]
        client.put(f"/api/dashboard/{dashboard_id}", payload)
    else:
        dashboard_id = client.post("/api/dashboard", payload)["id"]

    cards_by_name = {
        card["name"]: card
        for card in (client.get("/api/card") or [])
        if card.get("database_id") == database_id
    }

    dashcards = []
    for index, item in enumerate(spec["cards"], start=1):
        if item.get("kind") == "text":
            dashcards.append(
                {
                    "id": -index,
                    "card_id": None,
                    "row": item["row"],
                    "col": item["col"],
                    "size_x": item["size_x"],
                    "size_y": item["size_y"],
                    "visualization_settings": {
                        "virtual_card": {
                            "name": None,
                            "display": "text",
                            "visualization_settings": {},
                            "dataset_query": {},
                            "archived": False,
                        },
                        "text": item["text"],
                        "dashcard.background": False,
                    },
                    "parameter_mappings": [],
                }
            )
            continue

        card_id = ensure_card(client, database_id, collection_id, item, cards_by_name)
        dashcards.append(
            {
                "id": -index,
                "card_id": card_id,
                "row": item["row"],
                "col": item["col"],
                "size_x": item["size_x"],
                "size_y": item["size_y"],
                "visualization_settings": {},
                "parameter_mappings": [],
            }
        )

    # L'ancien endpoint `/api/dashboard/:id/cards` est déprécié : la disposition
    # complète se pousse en une fois via le champ `dashcards`.
    client.put(f"/api/dashboard/{dashboard_id}", {"dashcards": dashcards})
    log.info("Dashboard prêt : %s (%d éléments)", spec["name"], len(dashcards))
    return dashboard_id


def provision(config: Config) -> None:
    """Provisionne Metabase de bout en bout et affiche les accès."""
    client = MetabaseClient(config.metabase_url)
    client.wait_until_ready()
    client.authenticate(config.admin_email, config.admin_password)

    credentials = {
        "pilotage": (config.pilotage_email, config.metabase_pilotage_password),
        "recherche": (config.recherche_email, config.metabase_recherche_password),
    }

    database_ids: dict[str, int] = {}
    collection_ids: dict[str, int] = {}
    group_to_database: dict[int, int] = {}
    group_to_collection: dict[int, int] = {}

    for usage in USAGES:
        database_id = ensure_database(client, usage, config)
        group_id = ensure_group(client, usage.group_name)
        collection_id = ensure_collection(
            client, usage.group_name, DASHBOARDS[usage.key]["description"]
        )
        email, password = credentials[usage.key]
        ensure_user(client, email, password, group_id, usage.group_name)

        database_ids[usage.key] = database_id
        collection_ids[usage.key] = collection_id
        group_to_database[group_id] = database_id
        group_to_collection[group_id] = collection_id

    apply_data_permissions(client, group_to_database)
    apply_collection_permissions(client, group_to_collection)

    # Metabase doit avoir parcouru le schéma avant que les cartes s'affichent.
    for database_id in database_ids.values():
        client.post(f"/api/database/{database_id}/sync_schema")
    time.sleep(5)

    for usage in USAGES:
        ensure_dashboard(
            client, database_ids[usage.key], collection_ids[usage.key], DASHBOARDS[usage.key]
        )

    console.print("[green]✓[/] Metabase provisionné.")
    console.print(f"  [bold]{config.metabase_url}[/]")
    console.print(f"  pilotage   {config.pilotage_email} / {config.metabase_pilotage_password}")
    console.print(f"  recherche  {config.recherche_email} / {config.metabase_recherche_password}")
    console.print(f"  admin      {config.admin_email} / {config.admin_password}")
