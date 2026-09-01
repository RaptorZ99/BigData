# dbt — couches silver et gold de l'EDS

La transformation de l'entrepôt vit ici. Bronze reste en dehors : charger un fichier
n'est pas une transformation, et dbt ne sait pas le faire.

## Pourquoi dbt, et ce qu'il ne remplace pas

Trois gains concrets, au-delà de l'effet vitrine :

1. **L'ordre d'exécution cesse d'être une convention de nommage.** Il reposait sur le
   préfixe numérique des fichiers, au point qu'il fallait écrire dans les conventions
   du projet que `05_pilotage_qualite.sql` devait s'exécuter en dernier « car il
   recopie `ops.quality_report` ». Avec `ref()`, dbt **déduit** cet ordre. Le piège
   disparaît, et le test qui interdit d'écrire une base en dur l'empêche de revenir.
2. **La déduplication n'est plus copiée-collée.** La CTE `argMax` des séjours était
   écrite deux fois — dans `fact_sejour` et dans `sejours_rejets` — et celle du
   monitoring aussi. Ce sont maintenant deux modèles **éphémères**, écrits une fois,
   que dbt inline dans chaque consommateur.
3. **Les tests entrent dans le pipeline.** `dbt build` construit et teste en une
   passe : un `fact_sejour` dont la clé n'est plus unique fait échouer le run, donc
   suspend la publication — exactement comme un fichier en échec.

Ce que dbt **ne remplace pas** : `ops.quality_report`. Un test répond « ça passe ou ça
casse » ; le rapport qualité répond « 15 000 lues, 14 864 conservées, 136 écartées par
la règle Q2 ». Le rapport est donc lui-même un modèle dbt — ce qui lui vaut, au
passage, d'être ordonné par le graphe plutôt qu'à la main.

## Organisation

```
models/
├── sources.yml            eds_bronze.* et ops.ingest_log
├── silver/                9 tables + 2 modèles éphémères (déduplication)
├── gold_pilotage/         9 indicateurs
├── gold_recherche/        6 tables k-anonymisées
└── ops/quality_report.sql 18 règles, incrémental en ajout
tests/                     9 tests singuliers — les propriétés qui font le projet
macros/                    surcharge du nommage de schéma, tranches d'âge
```

**27 modèles matérialisés, 2 éphémères, 78 tests.** Le graphe complet se visualise
avec `make dbt-docs`.

## Lancer

```bash
make dbt-build      # via le pipeline : eds run --rebuild
make dbt-test       # rejoue les seuls tests sur l'entrepôt en place
make dbt-docs       # documentation autonome (graphe, colonnes, tests)
```

À la main, en cas de besoin :

```bash
set -a && . ./.env && set +a
uv run dbt build --project-dir dbt --profiles-dir dbt --vars '{"run_id":"manuel"}'
uv run dbt build --project-dir dbt --profiles-dir dbt --select fact_sejour+
```

## Conventions

| Règle | Pourquoi |
|---|---|
| Jamais de base en dur (`eds_silver.x`) — `ref()` ou `source()` | Sinon le graphe ignore la dépendance et le modèle s'exécute avant ce qu'il lit. `tests/test_dbt_project.py` le refuse |
| Tout modèle a une `description` | `persist_docs` la recopie en `COMMENT` dans ClickHouse : c'est ce qu'un analyste lit dans Metabase |
| Tout modèle figure dans `EXPECTED_TABLES` | C'est ce qui permet au pipeline de détecter une transformation interrompue |
| `engine` et `order_by` explicites | Une table sans clé de tri se comporte mal à la lecture, et ClickHouse ne devine pas |
| Compteurs castés en `toInt64()` dans les `UNION ALL` | Réconcilier `count()` (UInt64) et une soustraction (Int64) produit un `Variant`, sur lequel un simple `sum()` échoue |
| Le seuil de k-anonymat passe par `var('seuil_k')` | Une constante nommée plutôt que six « 5 » disséminés |

## Deux cibles, un projet

`local` (poste) et `azure` (VM), choisies par `DBT_TARGET`. Les deux profils ne
diffèrent que par les variables d'environnement de connexion : les modèles sont
strictement identiques, et les invariants chiffrés **le sont aussi** — vérifié sur le
déploiement réel, table par table.

dbt ne remplace pas ClickHouse : il lui envoie du SQL. Sans moteur, il n'a rien à
piloter — c'est vrai des deux côtés.

## Pièges rencontrés

- **`--full-refresh` de dbt n'est pas celui d'`eds`.** `eds run --full-refresh`
  signifie « ré-ingérer tous les jours depuis la source » ; passer l'option à dbt
  détruirait l'historique de `ops.quality_report`, seul modèle incrémental. Le
  pipeline ne la transmet jamais.
- **La base cible doit être forcée.** Sans la surcharge de `generate_schema_name`,
  dbt crée `<schéma du profil>_<schéma du modèle>` : l'entrepôt se construirait
  ailleurs que là où Metabase le lit, sans la moindre erreur.
- **`ops.quality_report` appartient à dbt**, plus à `sql/00_init/02_ops.sql`. Sur un
  entrepôt antérieur à la migration, un `DROP TABLE ops.quality_report` unique est
  nécessaire avant le premier `dbt build`.
- **Deux règles gold lisent `system.columns`** : aucune dépendance déductible, d'où
  les commentaires `-- depends_on:` qui forcent l'ordre.
- **`DBT_TARGET_PATH` doit être honoré.** L'image du pipeline redirige les artefacts
  vers `/tmp` — le répertoire applicatif n'y est pas garanti inscriptible. Chercher
  `static_index.html` dans `dbt/target/` en dur faisait échouer la publication de la
  documentation alors que dbt avait réussi.
- **dbt ne démarre pas sur Python 3.14** (`mashumaro : UnserializableField`). Le dépôt
  est figé sur 3.13 par `.python-version` et `requires-python = ">=3.12,<3.14"`.
