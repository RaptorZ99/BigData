"""Journalisation du pipeline : console lisible + fichier rotatif traçable.

Le run_id est injecté dans chaque ligne pour relier les logs aux tables `ops`.
Aucune donnée patient ni sel de pseudonymisation ne doit transiter par les logs.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from eds.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "pipeline.log"

_CONSOLE_FORMAT = "%(asctime)s  %(levelname)-7s %(message)s"
_FILE_FORMAT = "%(asctime)s  %(levelname)-7s [%(run_id)s] %(name)s: %(message)s"


class _RunIdFilter(logging.Filter):
    """Ajoute le run_id courant à chaque enregistrement (vide hors pipeline)."""

    def __init__(self) -> None:
        super().__init__()
        self.run_id = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


_run_id_filter = _RunIdFilter()


def setup_logging(verbose: bool = False) -> None:
    """Configure la journalisation globale. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    file_handler.addFilter(_run_id_filter)
    root.addHandler(file_handler)

    # clickhouse-connect et urllib3 sont bavards en DEBUG.
    logging.getLogger("clickhouse_connect").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def bind_run_id(run_id: str) -> None:
    """Associe les logs suivants à un run du pipeline."""
    _run_id_filter.run_id = run_id


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_file_path() -> Path:
    return LOG_FILE
