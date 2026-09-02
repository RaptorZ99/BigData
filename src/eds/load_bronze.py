"""Chargement du lake vers la couche bronze.

Le moteur lit les fichiers **lui-même** : Python n'ouvre aucun fichier de données,
il envoie du SQL. C'est vrai des deux côtés — `file()` sur le lake monté en local,
`azureBlobStorage()` sur le conteneur en cible cloud. Le script de chargement est
le même : il ne contient qu'un `FROM {lake_source}`, et c'est le `Storage` qui
sait rendre l'expression.

L'idempotence tient en deux instructions : `DROP PARTITION` du jour concerné, puis
`INSERT`. Rejouer un jour ne duplique donc jamais rien, et un échec en cours de
route ne laisse pas de demi-partition — le prochain run la reprend depuis zéro.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from clickhouse_connect.driver.client import Client

from eds.logging_setup import get_logger
from eds.storage import SourceFile, Storage
from eds.warehouse import SQL_DIR, Sql, WarehouseError, execute_script

log = get_logger(__name__)

_LOAD_ATTEMPTS = 4
_LOAD_RETRY_DELAY = 0.5


@dataclass(frozen=True, slots=True)
class LakeFile:
    """Comment un fichier du lake est lu, et où il atterrit.

    `format` et `structure` décrivent le **fichier**, pas la table : ce sont des
    colonnes brutes, toutes en `String`, telles que le moteur doit les décoder.
    Le typage réel — `toUInt16OrZero`, `parseDateTimeBestEffort` — reste en SQL,
    dans le script de chargement, parce que c'est la logique de la couche bronze.

    Les mettre ici plutôt que dans le SQL permet aux deux cibles de partager un
    script unique : `file()` prend (chemin, format, structure) et
    `azureBlobStorage()` des arguments nommés — aucune formulation ne convient
    aux deux, mais le `Storage` sait produire l'une comme l'autre.
    """

    table: str
    script: str
    format: str
    structure: str | None = None


# Domaine → description du fichier du lake.
# Les référentiels partagent le domaine `referentiels` : on distingue au fichier.
_TARGETS: dict[str, LakeFile] = {
    "patients": LakeFile(
        table="patients",
        script="02_load_patients.sql",
        format="CSVWithNames",
        structure="patient_pseudo String, birth_year String, sex String, region_code String",
    ),
    "sejours": LakeFile(
        table="sejours",
        script="03_load_sejours.sql",
        format="CSVWithNames",
        structure=(
            "stay_id String, patient_pseudo String, service_code String, "
            "admission_ts String, discharge_ts String, admission_mode String, "
            "discharge_mode String"
        ),
    ),
    "diagnostics": LakeFile(
        table="diagnostics",
        script="04_load_diagnostics.sql",
        # `JSONAsString` lit un tableau JSON de premier niveau comme une ligne par
        # objet ; le script déplie ensuite le tableau `diagnostics` de chaque séjour.
        format="JSONAsString",
        structure="json String",
    ),
    "monitoring": LakeFile(
        table="monitoring",
        script="05_load_monitoring.sql",
        # Parquet porte son propre schéma : l'imposer serait redondant, et le
        # figer ferait échouer le chargement au moindre ajout de colonne.
        format="Parquet",
    ),
    "services.csv": LakeFile(
        table="services",
        script="06_load_services.sql",
        format="CSVWithNames",
        structure="service_code String, service_label String",
    ),
    "cim10.csv": LakeFile(
        table="cim10",
        script="07_load_cim10.sql",
        format="CSVWithNames",
        structure="code_cim10 String, libelle String",
    ),
    # ── Évolution du 29 août 2026 : actes médicaux et description des services ──
    "actes": LakeFile(
        table="actes",
        script="08_load_actes.sql",
        format="Parquet",
    ),
    "description_service.csv": LakeFile(
        table="description_service",
        script="09_load_description_service.sql",
        format="CSVWithNames",
        structure="service_code String, categorie String, capacite_lits String, pole String",
    ),
    "ccam.csv": LakeFile(
        table="ccam",
        script="10_load_ccam.sql",
        format="CSVWithNames",
        structure="code_ccam String, libelle String, tarif_euros String",
    ),
}


def target_for(source: SourceFile) -> LakeFile:
    """Description du fichier du lake associée à un fichier source."""
    # Les référentiels partagent un domaine mais visent chacun leur table :
    # c'est le nom du fichier qui tranche.
    key = source.relative_name if source.domain == "referentiels" else source.domain

    target = _TARGETS.get(key)
    if target is None:
        raise WarehouseError(f"Aucun chargement défini pour {source.label}")
    return target


def _insert_with_retry(client: Client, script_name: str, params: dict[str, str]) -> None:
    """Exécute l'INSERT, en tolérant une visibilité retardée du fichier.

    En cible locale, le lake est un dossier de l'hôte monté dans le conteneur. Sur
    macOS, la propagation d'un fichier fraîchement écrit vers le montage n'est pas
    instantanée : le moteur peut le déclarer absent une fraction de seconde après
    sa création. Quelques tentatives espacées suffisent, et une vraie absence finit
    malgré tout par remonter l'erreur.
    """
    script = SQL_DIR / "15_bronze_load" / script_name

    for tentative in range(_LOAD_ATTEMPTS):
        try:
            execute_script(client, script, params)
            return
        except WarehouseError as exc:
            derniere = tentative == _LOAD_ATTEMPTS - 1
            if derniere or "FILE_DOESNT_EXIST" not in str(exc):
                raise
            log.debug("Fichier pas encore visible côté moteur, nouvelle tentative.")
            time.sleep(_LOAD_RETRY_DELAY)


def drop_partition(client: Client, table: str, ingest_date: str) -> None:
    """Vide la partition du jour : sans effet si elle n'existe pas encore."""
    client.command(
        f"ALTER TABLE eds_bronze.{table} DROP PARTITION %(day)s", parameters={"day": ingest_date}
    )


def load(client: Client, source: SourceFile, lake: Storage) -> int:
    """Charge un fichier du lake dans bronze, de façon idempotente.

    Renvoie le nombre de lignes présentes dans la partition après chargement.
    """
    spec = target_for(source)

    drop_partition(client, spec.table, source.ingest_date)
    _insert_with_retry(
        client,
        spec.script,
        {
            # `Sql` : c'est une expression, pas une valeur — elle ne doit pas être échappée.
            "lake_source": Sql(lake.table_function(source, spec.format, spec.structure)),
            "source_file": source.key,
            "ingest_date": source.ingest_date,
        },
    )

    rows = client.query(
        f"SELECT count() FROM eds_bronze.{spec.table} WHERE _ingest_date = %(day)s",
        parameters={"day": source.ingest_date},
    ).result_rows[0][0]

    log.info(
        "bronze.%-12s %s → %s lignes",
        spec.table,
        source.ingest_date,
        f"{rows:,}".replace(",", " "),
    )
    return int(rows)
