# EDS CHU — Entrepôt de Données de Santé

Projet fil rouge M2 Big Data (épreuve E05) : construire l'Entrepôt de Données de Santé d'un CHU à partir de dépôts quotidiens de fichiers hétérogènes (`source-filestorage/`), selon une architecture médaillon **Filestorage → Lake → Bronze → Silver → Gold → Dashboards**, avec ClickHouse (Docker) comme entrepôt, Python comme orchestrateur et Metabase (Docker) pour la restitution.

**Silver est modélisé en constellation Kimball : 3 étoiles, une par fait** — exigence pédagogique validée avec le professeur : `fact_sejour` ⋆ (dim_patient, dim_service), `fact_monitoring` ⋆ (dim_service), `fact_diagnostic` ⋆ (dim_patient, dim_cim10), au grain déclaré, sur dimensions conformées. Chaque fait porte les FK directes de **ses** dimensions (propagées au build silver) — **aucune jointure fact-to-fact** dans le modèle ni dans les requêtes gold ; `stay_id` est la **dimension dégénérée** commune aux 3 faits (drill-across). Les libellés restent dans les dimensions ; chaque besoin métier mappe sur un fait (cf. PLAN.md §9.0). Le diagramme de référence est `docs/data-model.puml` (rendu : `docs/img/eds-data-model.png`) — il fait foi pour les DDL.

Le plan d'implémentation complet et autosuffisant est dans **`PLAN.md`** — le lire intégralement avant toute implémentation. Le sujet officiel est dans `FICHE-SUJET.md`.

## Règles impératives du projet

1. **RGPD — aucune donnée identifiante n'entre dans l'entrepôt.** `nir`, `nom`, `prenom` sont supprimés et `patient_id` est pseudonymisé (**HMAC-SHA256** avec le sel `EDS_SALT`, jamais commité) **dès la copie vers le lake**, dans `patients` ET `sejours` (même pseudonyme → jointures préservées). `birth_date` est généralisée en `birth_year`. Aucun code ne doit jamais charger l'identité en clair dans ClickHouse, un log, un dashboard ou un commit.
2. **Les transformations bronze→silver→gold s'exécutent en SQL dans ClickHouse.** Python ne fait que copier des fichiers et envoyer des requêtes. Interdiction de sortir les données du moteur pour les transformer en pandas — c'est l'anti-pattern explicitement sanctionné par le sujet. L'étape de pseudonymisation à l'entrée du lake se fait en **stdlib pure** (`csv`, `json`, `hmac`), en streaming ligne à ligne.
3. **`source-filestorage/` est en lecture seule.** Ne jamais le modifier, le déplacer ou y écrire. Il est gitignoré (il contient l'identité en clair), tout comme `data/` (lake + volumes) et `.env`.
4. **Idempotence obligatoire.** Bronze est partitionné par jour d'ingestion ; rejouer un jour = `DROP PARTITION` puis rechargement. Relancer le pipeline deux fois ne doit jamais dupliquer une ligne. L'état d'ingestion vit dans `ops.ingest_log` (checksum des fichiers).
5. **On écarte, on ne corrige pas.** Les lignes en anomalie (séjour avec `discharge_ts < admission_ts`, constantes hors plage physiologique) partent dans des tables `*_rejets` avec une colonne `reject_reason` — jamais supprimées silencieusement. Exception métier : `discharge_ts` vide = séjour en cours, **légitime**, à conserver. Les patients rejoués chaque jour (fichiers cumulatifs) se dédupliquent par `argMax` sur le jour d'ingestion dans `dim_patient`.
6. **Cloisonnement au niveau du warehouse.** Deux users ClickHouse (`chu_pilotage`, `chu_recherche`) avec des GRANT SELECT distincts sur `eds_gold_pilotage` / `eds_gold_recherche` ; Metabase a deux connexions séparées (une par user SQL) et deux groupes. Jamais un seul user SQL partagé.
7. **Petits effectifs : k ≥ 5.** Toute table/vue de la base recherche applique `HAVING uniqExact(patient_pseudo) >= 5` (y compris par cellule de croisement pathologie × sexe × tranche d'âge). Les âges sont diffusés en tranches, jamais en valeur exacte.
8. **Traçabilité systématique.** Chaque ligne bronze/silver porte `_source_file`, `_ingest_date`, `_loaded_at`. Chaque run écrit dans `ops.pipeline_runs` et produit un rapport qualité chiffré dans `ops.quality_report` : lignes **lues / conservées / écartées / signalées** par règle. Ne jamais confondre écartées (retirées, dans une table `*_rejets`) et signalées (conservées mais marquées) — c'est ce qui rend le rapport lisible.

## Pièges connus des données (issus du profilage — détail dans PLAN.md §2)

- `patients/` est **cumulatif** : chaque jour re-contient tous les patients des jours précédents (4800 → 5400 → 6000) — c'est le test de déduplication.
- ~2 % du monitoring a FC **et** SpO2 aberrantes sur les mêmes lignes (0/500 bpm, 0/120 %) — panne de capteur ; `temp_c` est toujours valide.
- Le monitoring ne couvre que les services **REA** et **CARDIO**, et chaque fichier quotidien couvre J → J+2 (sans doublons inter-fichiers).
- 1992 séjours ont une sortie datée mais `discharge_mode` vide → à conserver (valeur NULL), pas à rejeter.
- Anomalie « bonus » : 220 séjours (brut) admis après un décès antérieur du patient → flag `is_post_mortem_anomaly` (attendu **192** sur les séjours conservés), signalé au rapport qualité, pas rejeté.
- Les 520 relevés monitoring « post-sortie » appartiennent **tous** aux 136 séjours invalides (sortie < admission) : ils partent en **cascade** dans `monitoring_rejets` (`parent_stay_rejected`) et le flag `is_after_discharge` vaut **0** après nettoyage (contrôle actif). Invariants post-nettoyage à respecter : fact_sejour 14 864 · fact_diagnostic 37 040 · fact_monitoring 64 799 (cf. PLAN.md §2.6).
- Les séjours qui se chevauchent pour un même patient (~8 300) sont un artefact des données synthétiques : **ne pas** les rejeter, le documenter en limite.

## Pièges techniques rencontrés à l'implémentation

- **Volumes Docker nommés obligatoires pour ClickHouse.** Un bind mount macOS ne garantit pas les renommages atomiques exigés par `CREATE OR REPLACE TABLE` (échec `filesystem error: in rename`). Seul le lake reste un dossier de l'hôte, monté en lecture seule.
- **Le lake doit exister avant `docker compose up`** : supprimer `data/lake` conteneur allumé casse le montage (`FILE_DOESNT_EXIST`) — remède : `docker compose restart clickhouse`. Le chargement tolère une visibilité retardée du fichier par quelques tentatives espacées.
- **Alias SQL** : `max(_ingest_date) AS _ingest_date` rend les autres `argMax(…, _ingest_date)` récursifs (`ILLEGAL_AGGREGATION`). Nommer les alias de lignage différemment (`last_ingest_date`, `source_file`).
- **`LowCardinality`** : comparer une telle colonne produit un `LowCardinality(UInt8)` que ClickHouse refuse de matérialiser → `CAST(… AS Bool)`.
- **Clés de tri non nullables** : `assumeNotNull()` après le filtre qui garantit la valeur.
- **Metabase** : le jeton de setup reste exposé après configuration — se fier à `has-user-setup`. Le blocage complet des données (`view-data: blocked`) est payant ; en OSS on combine `create-queries: "no"` et les permissions de collection, l'interdiction réelle venant des GRANT ClickHouse.
- **Réadmission** : ne jamais utiliser `leadInFrame` ici (cf. PLAN.md §9.1).

## Commandes de référence

```bash
make demo        # démo complète de zéro (up + pipeline + provision) — ~30 s
make pipeline    # pipeline incrémental (jours non encore ingérés)
make test        # tests unitaires ; make test-e2e pour les invariants de l'entrepôt
uv run eds run --rebuild          # reconstruit silver+gold après modification du SQL
uv run eds run --date 2026-08-27  # rejeu forcé d'un jour (reprise sur incident)
uv run eds check-cloisonnement    # vérifie les droits d'accès ClickHouse
```
