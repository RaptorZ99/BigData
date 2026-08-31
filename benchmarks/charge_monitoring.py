# /// script
# requires-python = ">=3.12"
# dependencies = ["clickhouse-connect>=0.8", "pyarrow>=18", "numpy>=2"]
# ///
"""Banc d'essai : le chargement du monitoring tient-il la charge ?

Le sujet impose que « l'architecture tienne la charge » pour le flux de
monitoring. Ce script le mesure plutôt que de l'affirmer : il fabrique des
fichiers Parquet de taille croissante, les charge **par le chemin réel du
pipeline** (`INSERT … SELECT FROM file()`), et chronomètre.

Ce qu'il cherche à établir :
  * le temps de chargement croît linéairement avec le volume ;
  * la mémoire du client Python reste constante, puisque le moteur lit le
    fichier lui-même — c'est tout l'intérêt de ne pas passer par pandas ;
  * les agrégations restent instantanées sur des dizaines de millions de lignes.

Usage (l'entrepôt doit tourner) :

    uv run benchmarks/charge_monitoring.py

Le script crée une table temporaire dans `eds_bronze`, la supprime en sortant,
et n'écrit rien dans les couches silver ou gold : l'entrepôt de démonstration
n'est pas affecté.

Les dépendances (pyarrow, numpy) ne servent qu'à *fabriquer* le jeu de test.
Elles sont déclarées en tête de fichier et installées à la volée par uv : le
pipeline lui-même n'en dépend pas.
"""

from __future__ import annotations

import time
from pathlib import Path

import clickhouse_connect
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

RACINE = Path(__file__).resolve().parent.parent
LAKE_BENCH = RACINE / "data" / "lake" / "bench"
TABLE = "eds_bronze.bench_monitoring"
PALIERS = (1_000_000, 5_000_000, 20_000_000)

# Délai laissé au montage Docker pour rendre le fichier visible côté moteur.
DELAI_PROPAGATION = 1.0


def lire_env() -> dict[str, str]:
    valeurs: dict[str, str] = {}
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, _, valeur = ligne.partition("=")
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def fabriquer(n: int, chemin: Path) -> float:
    """Écrit un Parquet de `n` relevés plausibles ; renvoie sa taille en Mo."""
    rng = np.random.default_rng(42)
    depart = np.datetime64("2026-08-26T00:00:00")
    table = pa.table(
        {
            "stay_id": pa.array([f"S{i % 200_000:08d}" for i in range(n)]),
            "ts": pa.array(depart + rng.integers(0, 30 * 86_400, n).astype("timedelta64[s]")),
            "heart_rate": pa.array(rng.integers(45, 130, n, dtype=np.int32)),
            "spo2": pa.array(rng.integers(88, 100, n, dtype=np.int32)),
            "temp_c": pa.array(rng.uniform(36.0, 39.5, n).astype(np.float32)),
        }
    )
    pq.write_table(table, chemin, compression="snappy")
    return chemin.stat().st_size / 1024 / 1024


def main() -> None:
    env = lire_env()
    client = clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "localhost"),
        port=int(env.get("CLICKHOUSE_PORT", "8123")),
        username=env["CLICKHOUSE_ETL_USER"],
        password=env["CLICKHOUSE_ETL_PASSWORD"],
        send_receive_timeout=1800,
    )

    LAKE_BENCH.mkdir(parents=True, exist_ok=True)
    client.command(f"""
        CREATE OR REPLACE TABLE {TABLE}
        (stay_id String, ts DateTime, heart_rate Int32, spo2 Int32, temp_c Float32,
         _source_file String, _ingest_date Date, _loaded_at DateTime DEFAULT now())
        ENGINE = MergeTree PARTITION BY _ingest_date ORDER BY (stay_id, ts)
    """)

    print(f"{'lignes':>12} {'fichier':>10} {'écriture':>10} {'chargement':>11} {'lignes/s':>12}")
    print("-" * 60)

    try:
        for n in PALIERS:
            chemin = LAKE_BENCH / f"monitoring_{n}.parquet"
            debut = time.perf_counter()
            taille = fabriquer(n, chemin)
            duree_ecriture = time.perf_counter() - debut
            time.sleep(DELAI_PROPAGATION)

            client.command(f"ALTER TABLE {TABLE} DROP PARTITION '2026-08-26'")
            debut = time.perf_counter()
            client.command(f"""
                INSERT INTO {TABLE}
                SELECT stay_id, ts, toInt32(heart_rate), toInt32(spo2), toFloat32(temp_c),
                       'benchmark' AS _source_file, toDate('2026-08-26') AS _ingest_date, now()
                FROM file('lake/bench/{chemin.name}', 'Parquet')
            """)
            duree_chargement = time.perf_counter() - debut

            charge = client.query(f"SELECT count() FROM {TABLE}").result_rows[0][0]
            if charge != n:
                raise SystemExit(f"Chargement incomplet : {charge} lignes sur {n}")

            print(
                f"{n:>12,} {taille:>9.0f}M {duree_ecriture:>9.1f}s "
                f"{duree_chargement:>10.1f}s {n / duree_chargement:>11,.0f}"
            )
            chemin.unlink()

        print("\nRequêtes analytiques sur le plus gros palier :")
        mesures = [
            ("comptage total", f"SELECT count() FROM {TABLE}"),
            (
                "détection des alertes",
                f"SELECT countIf(heart_rate < 40 OR heart_rate > 130 OR spo2 < 90 "
                f"OR temp_c >= 38.5) FROM {TABLE}",
            ),
            (
                "agrégation par jour",
                f"SELECT toDate(ts) AS jour, count(), avg(heart_rate) FROM {TABLE} "
                f"GROUP BY jour ORDER BY jour",
            ),
        ]
        for libelle, requete in mesures:
            debut = time.perf_counter()
            client.query(requete)
            print(f"  {libelle:<24} {time.perf_counter() - debut:>6.2f} s")

        occupation = client.query(
            "SELECT formatReadableSize(sum(bytes_on_disk)) FROM system.parts "
            "WHERE table = 'bench_monitoring' AND active"
        ).result_rows[0][0]
        print(f"\n  {PALIERS[-1]:,} lignes occupent {occupation} sur disque.")

    finally:
        client.command(f"DROP TABLE IF EXISTS {TABLE}")
        for reste in LAKE_BENCH.glob("*.parquet"):
            reste.unlink()
        LAKE_BENCH.rmdir()
        print("\n✓ Table temporaire et fichiers de test supprimés.")


if __name__ == "__main__":
    main()
