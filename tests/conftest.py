"""Fixtures partagées : jeu de données miniature, entièrement inventé.

Aucune donnée réelle n'entre dans les tests (et donc dans le dépôt Git).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eds.config import Config

SALT = "0123456789abcdef0123456789abcdef"

PATIENTS_CSV = """patient_id,nir,nom,prenom,birth_date,sex,region_code
IPP0000001,199017512345678,MARTIN,Claire,1990-01-15,F,75
IPP0000002,185039923456789,BERNARD,Paul,1985-03-22,m,92
IPP0000003,201126734567890,PETIT,Lina,2011-12-05,F,93
"""

SEJOURS_CSV = """\
stay_id,patient_id,service_code,admission_ts,discharge_ts,admission_mode,discharge_mode
S00000001,IPP0000001,CARDIO,2026-08-26 08:00:00,2026-08-28 14:00:00,urgence,domicile
S00000002,IPP0000002,REA,2026-08-26 09:30:00,,programme,
S00000003,IPP0000003,PEDIA,2026-08-26 10:15:00,2026-08-25 10:15:00,mutation,domicile
"""


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Simule un dépôt du CHU pour un jour."""
    day = "2026-08-26"
    patients = tmp_path / "source" / "patients" / day
    sejours = tmp_path / "source" / "sejours" / day
    patients.mkdir(parents=True)
    sejours.mkdir(parents=True)
    (patients / "patients.csv").write_text(PATIENTS_CSV, encoding="utf-8")
    (sejours / "sejours.csv").write_text(SEJOURS_CSV, encoding="utf-8")
    return tmp_path / "source"


@pytest.fixture
def config(source_dir: Path, tmp_path: Path) -> Config:
    return Config(
        salt=SALT,
        source_dir=source_dir,
        lake_dir=tmp_path / "lake",
        clickhouse_host="localhost",
        clickhouse_port=8123,
        clickhouse_user="chu_etl",
        clickhouse_password="x",
        pilotage_password="x",
        recherche_password="x",
        metabase_url="http://localhost:3000",
        metabase_clickhouse_host="clickhouse",
        metabase_clickhouse_port=8123,
        admin_email="admin@chu.local",
        admin_password="x",
        pilotage_email="pilotage@chu.local",
        metabase_pilotage_password="x",
        recherche_email="recherche@chu.local",
        metabase_recherche_password="x",
    )
