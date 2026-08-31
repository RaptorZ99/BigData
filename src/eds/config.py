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

# Valeur de remplissage de .env.example. Elle est publique, donc inutilisable :
# un sel connu rend le HMAC réversible par simple force brute sur l'espace des
# identifiants patients. `make env` en génère un aléatoire à la création du
# fichier ; ce garde-fou couvre le cas d'un .env recopié à la main.
PLACEHOLDER_SALT = "remplace-moi-par-openssl-rand-hex-32"

# Marque commune à tous les mots de passe d'exemple de .env.example. `make env`
# les remplace par des valeurs aléatoires à la création du fichier ; ce garde-fou
# couvre le cas d'un .env recopié à la main. Le marqueur est unique **pour que la
# détection ne puisse pas rater un secret** : un mot de passe d'exemple qui aurait
# l'air d'un vrai (« AdminChu2026! ») passerait inaperçu et finirait en production.
PLACEHOLDER_PASSWORD_MARKER = "change_me"


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
    def weak_password_settings(self) -> tuple[str, ...]:
        """Variables dont le mot de passe est encore celui de l'exemple.

        Les six secrets sont couverts, y compris ceux de Metabase : un compte
        d'administration laissé à sa valeur d'exemple ouvre l'accès à toutes les
        données de restitution.
        """
        secrets = {
            "CLICKHOUSE_ETL_PASSWORD": self.clickhouse_password,
            "CLICKHOUSE_PILOTAGE_PASSWORD": self.pilotage_password,
            "CLICKHOUSE_RECHERCHE_PASSWORD": self.recherche_password,
            "MB_ADMIN_PASSWORD": self.admin_password,
            "MB_PILOTAGE_PASSWORD": self.metabase_pilotage_password,
            "MB_RECHERCHE_PASSWORD": self.metabase_recherche_password,
        }
        return tuple(
            nom
            for nom, valeur in secrets.items()
            if PLACEHOLDER_PASSWORD_MARKER in valeur.casefold()
        )

    @property
    def uses_weak_passwords(self) -> bool:
        """Vrai si des mots de passe d'exemple subsistent dans la configuration."""
        return bool(self.weak_password_settings)


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
    if salt == PLACEHOLDER_SALT:
        raise ConfigError(
            "EDS_SALT vaut encore la valeur d'exemple, qui est publique : "
            "les pseudonymes seraient réversibles. "
            "Générez un sel propre à votre installation : openssl rand -hex 32"
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
