"""Configuration du pipeline, lue depuis .env avec validation fail-fast.

Une configuration invalide (sel absent ou trop court, source introuvable) doit
échouer immédiatement avec un message actionnable : mieux vaut ne rien ingérer
que d'ingérer avec un sel de pseudonymisation faible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Longueur minimale du sel HMAC. 32 caractères ≈ 128 bits d'entropie si le sel
# est généré aléatoirement (openssl rand -hex 32 en produit 64).
MIN_SALT_LENGTH = 32

# Sel de démonstration livré dans .env.example : accepté (le projet doit tourner
# après un simple `make demo`) mais signalé, car il n'est pas secret.
DEMO_SALT = "demo-salt-a-remplacer-par-openssl-rand-hex-32"


class ConfigError(RuntimeError):
    """Configuration absente ou invalide."""


@dataclass(frozen=True, slots=True)
class Config:
    """Paramètres du pipeline pour une exécution."""

    salt: str
    source_dir: Path
    lake_dir: Path
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    pilotage_password: str
    recherche_password: str
    metabase_url: str
    metabase_clickhouse_host: str
    metabase_clickhouse_port: int
    admin_email: str
    admin_password: str
    pilotage_email: str
    metabase_pilotage_password: str
    recherche_email: str
    metabase_recherche_password: str

    @property
    def uses_demo_salt(self) -> bool:
        """Vrai si le sel livré en exemple est utilisé tel quel."""
        return self.salt == DEMO_SALT


def load_dotenv(path: Path | None = None) -> None:
    """Charge un fichier .env dans l'environnement, sans écraser l'existant.

    Implémentation volontairement minimale (pas de dépendance) : le format
    attendu est `CLE=valeur`, avec `#` en commentaire de ligne.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _require(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Variable {name} manquante. {hint}")
    return value


def _resolve(raw_path: str) -> Path:
    """Résout un chemin relatif par rapport à la racine du projet."""
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_config() -> Config:
    """Construit la configuration et valide ses invariants critiques."""
    load_dotenv()

    hint = "Lancez `cp .env.example .env` puis renseignez-la."
    salt = _require("EDS_SALT", f"{hint} Générez-la avec : openssl rand -hex 32")
    if len(salt) < MIN_SALT_LENGTH:
        raise ConfigError(
            f"EDS_SALT trop court ({len(salt)} caractères, minimum {MIN_SALT_LENGTH}). "
            "Générez un sel robuste : openssl rand -hex 32"
        )

    source_dir = _resolve(os.environ.get("EDS_SOURCE_DIR", "./source-filestorage"))
    if not source_dir.is_dir():
        raise ConfigError(
            f"Dépôt source introuvable : {source_dir}. "
            "Vérifiez EDS_SOURCE_DIR (le dossier du CHU est en lecture seule)."
        )

    return Config(
        salt=salt,
        source_dir=source_dir,
        lake_dir=_resolve(os.environ.get("EDS_LAKE_DIR", "./data/lake")),
        clickhouse_host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        clickhouse_port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        clickhouse_user=os.environ.get("CLICKHOUSE_ETL_USER", "chu_etl"),
        clickhouse_password=_require("CLICKHOUSE_ETL_PASSWORD", hint),
        pilotage_password=_require("CLICKHOUSE_PILOTAGE_PASSWORD", hint),
        recherche_password=_require("CLICKHOUSE_RECHERCHE_PASSWORD", hint),
        metabase_url=os.environ.get("MB_URL", "http://localhost:3000").rstrip("/"),
        metabase_clickhouse_host=os.environ.get("MB_CLICKHOUSE_HOST", "clickhouse"),
        metabase_clickhouse_port=int(os.environ.get("MB_CLICKHOUSE_PORT", "8123")),
        admin_email=os.environ.get("MB_ADMIN_EMAIL", "admin@chu.local"),
        admin_password=_require("MB_ADMIN_PASSWORD", hint),
        pilotage_email=os.environ.get("MB_PILOTAGE_EMAIL", "pilotage@chu.local"),
        metabase_pilotage_password=_require("MB_PILOTAGE_PASSWORD", hint),
        recherche_email=os.environ.get("MB_RECHERCHE_EMAIL", "recherche@chu.local"),
        metabase_recherche_password=_require("MB_RECHERCHE_PASSWORD", hint),
    )
