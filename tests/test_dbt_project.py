"""Cohérence du projet dbt — vérifiée sans dbt, sans Docker, sans entrepôt.

Ces contrôles sont volontairement statiques : ils lisent les fichiers. Ils
attrapent en une seconde les erreurs qui, sinon, ne se verraient qu'au milieu
d'un `dbt build` sur une base réelle — un modèle ajouté mais absent de
`EXPECTED_TABLES`, une base écrite en dur au lieu d'un `ref()`, un modèle sans
description (donc sans commentaire dans ClickHouse ni dans la documentation).
"""

from __future__ import annotations

import re

from eds.config import PROJECT_ROOT
from eds.transform import DBT_DIR, EXPECTED_TABLES

MODELS_DIR = DBT_DIR / "models"

# Modèles éphémères : dbt les inline comme CTE, ils ne produisent aucune table.
# Les exiger dans `EXPECTED_TABLES` reviendrait à attendre une table qui n'existe
# pas — et ne pas les déclarer ici les ferait passer pour un oubli.
EPHEMERES = {"stg_sejours", "stg_monitoring", "stg_actes", "readmission_sejour"}

# Modèles hors des bases de l'entrepôt : le rapport qualité vit dans `ops`, base
# d'exploitation à laquelle aucun compte de restitution n'a accès.
HORS_ENTREPOT = {"quality_report"}


def _modeles() -> dict[str, str]:
    """Nom du modèle → dossier de couche."""
    return {chemin.stem: chemin.parent.name for chemin in MODELS_DIR.rglob("*.sql")}


def _noms_documentes() -> set[str]:
    """Modèles portant une entrée `- name:` dans un fichier de propriétés."""
    documentes: set[str] = set()
    for chemin in MODELS_DIR.rglob("_*__models.yml"):
        documentes |= set(re.findall(r"^  - name: ([a-z0-9_]+)$", chemin.read_text("utf-8"), re.M))
    return documentes


def test_chaque_modele_produit_une_table_attendue():
    """Un modèle qui n'est pas dans `EXPECTED_TABLES` échapperait au contrôle de complétude.

    `missing_tables()` est ce qui permet au pipeline de détecter une
    transformation interrompue : une table qu'il ignore ne serait jamais
    signalée comme absente.
    """
    attendues = {table for tables in EXPECTED_TABLES.values() for table in tables}
    inconnus = set(_modeles()) - attendues - EPHEMERES - HORS_ENTREPOT
    assert not inconnus, f"modèles dbt absents d'EXPECTED_TABLES : {sorted(inconnus)}"


def test_chaque_table_attendue_a_son_modele():
    """L'inverse : une table déclarée mais que plus aucun modèle ne construit.

    Le pipeline la réclamerait indéfiniment et se reconstruirait à chaque run.
    """
    modeles = set(_modeles())
    manquants = {
        f"{base}.{table}"
        for base, tables in EXPECTED_TABLES.items()
        for table in tables
        if table not in modeles
    }
    assert not manquants, f"tables attendues sans modèle dbt : {sorted(manquants)}"


def test_chaque_modele_est_documente():
    """Sans description, ni la documentation dbt ni les COMMENT de ClickHouse.

    `persist_docs` recopie ces descriptions dans l'entrepôt : elles ne sont pas
    de la décoration, elles sont ce qu'un analyste lit dans Metabase.
    """
    non_documentes = set(_modeles()) - _noms_documentes() - EPHEMERES
    assert not non_documentes, f"modèles dbt sans description : {sorted(non_documentes)}"


def test_aucun_modele_ne_code_une_base_en_dur():
    """Une base écrite en dur casserait le graphe de dépendances.

    dbt ordonne les modèles à partir des `ref()` et `source()` : un
    `FROM eds_silver.fact_sejour` compilerait, puis s'exécuterait un jour avant la
    table qu'il lit. C'est exactement le piège que la migration devait supprimer.

    `system.columns` et les bases citées dans une chaîne de caractères — un
    libellé de contrôle qualité — sont hors sujet : on ne vise que les clauses FROM
    et JOIN.
    """
    motif = re.compile(r"\b(?:FROM|JOIN)\s+(eds_bronze|eds_silver|eds_gold_\w+|ops)\.", re.I)
    fautifs = {
        f"{chemin.relative_to(DBT_DIR)} → {motif.search(chemin.read_text('utf-8')).group(1)}"
        for chemin in MODELS_DIR.rglob("*.sql")
        if motif.search(chemin.read_text("utf-8"))
    }
    assert not fautifs, f"bases codées en dur au lieu de ref()/source() : {sorted(fautifs)}"


def test_la_base_cible_n_est_pas_prefixee():
    """dbt concatène par défaut schéma du profil et schéma du modèle.

    Sans la surcharge, `eds_silver` deviendrait `eds_silver_eds_gold_pilotage` :
    l'entrepôt se construirait ailleurs que là où Metabase le lit, sans erreur.
    """
    macro = (DBT_DIR / "macros" / "generate_schema_name.sql").read_text("utf-8")
    assert "generate_schema_name" in macro
    assert "custom_schema_name | trim" in macro
    assert "{{ target.schema }}_" not in macro, "la surcharge concatène encore"


def test_le_rapport_qualite_est_incremental():
    """Un `table` écraserait le rapport du run précédent.

    L'historique des contrôles est ce qui permet de comparer deux traitements ;
    il porte un TTL d'un an plutôt qu'une remise à zéro quotidienne.
    """
    modele = (MODELS_DIR / "ops" / "quality_report.sql").read_text("utf-8")
    assert "materialized='incremental'" in modele
    assert "incremental_strategy='append'" in modele


def test_les_anciens_scripts_sql_ont_disparu():
    """Deux définitions de la même table finiraient par diverger.

    La migration vers dbt n'est complète que si les scripts qu'elle remplace ont
    été supprimés — un `sql/30_gold/` oublié serait exécuté par
    `execute_directory` et écraserait les modèles.
    """
    for ancien in ("sql/20_silver", "sql/30_gold"):
        assert not (PROJECT_ROOT / ancien).exists(), f"{ancien} subsiste après la migration dbt"
