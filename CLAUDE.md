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
6. **Cloisonnement au niveau du warehouse.** Deux users ClickHouse (`chu_pilotage`, `chu_recherche`) avec des GRANT SELECT distincts sur `eds_gold_pilotage` / `eds_gold_recherche` ; Metabase a deux connexions séparées (une par user SQL) et deux groupes. Jamais un seul user SQL partagé. Les deux comptes héritent du profil `restitution` (`readonly = 2`, temps/mémoire bornés) et d'un quota horaire : le GRANT protège la confidentialité, ces bornes la **disponibilité** face au SQL libre de Metabase.
7. **Petits effectifs : k ≥ 5, et suppression complémentaire.** Toute table/vue de la base recherche applique `HAVING uniqExact(patient_pseudo) >= 5` (y compris par cellule de croisement pathologie × sexe × tranche d'âge). **Le seuil seul ne suffit pas** : publier une marge ET sa décomposition laisse retrouver la cellule cachée par soustraction (`marge − somme des cellules diffusées`). Une marge n'est donc diffusée que si TOUTE sa décomposition l'est. La table de travail qui porte les effectifs sous le seuil (`cellules_demographie`) vit en `eds_silver`, hors de portée des comptes de restitution. Les âges sont diffusés en tranches, jamais en valeur exacte.
8. **Traçabilité systématique.** Chaque ligne bronze/silver porte `_source_file`, `_ingest_date`, `_loaded_at`. Chaque run écrit dans `ops.pipeline_runs` et produit un rapport qualité chiffré dans `ops.quality_report` : lignes **lues / conservées / écartées / signalées** par règle. Ne jamais confondre écartées (retirées, dans une table `*_rejets`) et signalées (conservées mais marquées) — c'est ce qui rend le rapport lisible.

## Pièges connus des données (issus du profilage — détail dans PLAN.md §2)

- `patients/` est **cumulatif** : chaque jour re-contient tous les patients des jours précédents (4800 → 5400 → 6000) — c'est le test de déduplication.
- ~2 % du monitoring a FC **et** SpO2 aberrantes sur les mêmes lignes (0/500 bpm, 0/120 %) — panne de capteur ; `temp_c` est toujours valide.
- Le monitoring ne couvre que les services **REA** et **CARDIO**, et chaque fichier quotidien couvre J → J+2 (sans doublons inter-fichiers).
- 1 992 séjours (brut) ont une sortie datée mais `discharge_mode` vide → à conserver (valeur NULL), pas à rejeter. Attendu **1 975** sur les séjours conservés — l'écart, ce sont les séjours écartés par Q2.
- Anomalie « bonus » : 220 séjours (brut) admis après un décès antérieur du patient → flag `is_post_mortem_anomaly` (attendu **192** sur les séjours conservés), signalé au rapport qualité, pas rejeté.
- Les 520 relevés monitoring « post-sortie » appartiennent **tous** aux 136 séjours invalides (sortie < admission) : ils partent en **cascade** dans `monitoring_rejets` (`parent_stay_rejected`) et le flag `is_after_discharge` vaut **0** après nettoyage (contrôle actif). Invariants post-nettoyage à respecter : fact_sejour 14 864 · fact_diagnostic 37 040 · fact_monitoring 64 799 (cf. PLAN.md §2.6).
- Les séjours qui se chevauchent pour un même patient (~8 300) sont un artefact des données synthétiques : **ne pas** les rejeter, le documenter en limite.
- Les diagnostics sont tirés au hasard : les 10 pathologies ont chacune ~51 % de prévalence, somme **508,9 %** (≈ 5 diagnostics par patient, sans corrélation avec le service, l'âge ou le sexe). Les cohortes valident la chaîne de traitement, **pas** une conclusion épidémiologique — l'avertissement figure en tête du dashboard recherche et en §8.1 du rapport.

## Pièges techniques rencontrés à l'implémentation

- **Volumes Docker nommés obligatoires pour ClickHouse.** Un bind mount macOS ne garantit pas les renommages atomiques exigés par `CREATE OR REPLACE TABLE` (échec `filesystem error: in rename`). Seul le lake reste un dossier de l'hôte, monté en lecture seule.
- **Le lake doit exister avant `docker compose up`** : supprimer `data/lake` conteneur allumé casse le montage (`FILE_DOESNT_EXIST`) — remède : `docker compose restart clickhouse`. Le chargement tolère une visibilité retardée du fichier par quelques tentatives espacées.
- **Alias SQL** : `max(_ingest_date) AS _ingest_date` rend les autres `argMax(…, _ingest_date)` récursifs (`ILLEGAL_AGGREGATION`). Nommer les alias de lignage différemment (`last_ingest_date`, `source_file`).
- **`LowCardinality`** : comparer une telle colonne produit un `LowCardinality(UInt8)` que ClickHouse refuse de matérialiser → `CAST(… AS Bool)`.
- **Clés de tri non nullables** : `assumeNotNull()` après le filtre qui garantit la valeur.
- **Metabase** : le jeton de setup reste exposé après configuration — se fier à `has-user-setup`. Le blocage complet des données (`view-data: blocked`) est payant ; en OSS on combine `create-queries: "no"` et les permissions de collection, l'interdiction réelle venant des GRANT ClickHouse.
- **Réadmission** : ne jamais utiliser `leadInFrame` ici (cf. PLAN.md §9.1).
- **Découpage SQL** : le découpeur respecte les chaînes — un `;` dans un libellé métier ne sépare pas deux instructions. Ne pas revenir à un `split(";")` naïf.
- **Ordre du gold** : `05_pilotage_qualite.sql` s'exécute en dernier car il recopie `ops.quality_report`, alimenté par `04_quality.sql`. Le placer plus tôt n'exposerait que les règles silver.
- **Mesures non additives** : `nb_patients` ne se somme jamais hors de son grain. La pyramide des âges lit `cohorte_demographie_globale` (grain sexe × tranche), pas `cohorte_demographie` (grain CIM-10 × sexe × tranche) — sinon un patient à 5 diagnostics est compté 5 fois.
- **Provisionnement convergent** : `CREATE USER OR REPLACE` côté ClickHouse et réalignement du mot de passe côté Metabase. `IF NOT EXISTS` ne met pas à jour un compte existant, donc changer `.env` n'aurait aucun effet. Même logique pour le schéma : `CREATE TABLE IF NOT EXISTS` ne rejoue pas une évolution, d'où les `ALTER … ADD COLUMN IF NOT EXISTS` / `MODIFY TTL` explicites dans `02_ops.sql`.
- **Secrets hors des logs** : ne jamais imprimer un mot de passe sur stdout — la sortie du provisionnement finit dans `logs/cron.log`. Corollaire : tout secret d'exemple porte la marque `change_me`, seul motif que `Config.weak_password_settings` sait détecter. Ne jamais mettre dans `.env.example` une valeur qui *ressemble* à un vrai mot de passe : elle passerait le contrôle en silence.
- **`readonly = 2`, jamais `1`** sur les comptes de restitution : le niveau 1 interdit aussi de changer un paramètre de session, ce que le pilote JDBC de Metabase fait à la connexion.
- **Pas de produit croisé jour × ligne de fait.** `kpi_activite_service` compte les séjours ouverts par cumul (`sum(...) OVER` sur le calendrier), pas en confrontant chaque jour à chaque séjour : ce dernier coûte O(jours × séjours) et devient quadratique avec l'historique.
- **Déduplication au grain, dans les trois faits.** `fact_monitoring` déduplique sur `(stay_id, ts)` comme les autres sur leur clé. Aujourd'hui sans effet, mais un redépôt corrigé sous un autre `_ingest_date` doublerait relevés et alertes.
- **`ifNotFinite(…, 0)`** sur les moyennes et les taux de `kpi_synthese` : sur un entrepôt vide, une division 0/0 afficherait `nan` dans une tuile de direction.
- **Mise en page des dashboards** — quatre défauts que seul l'écran révèle, tous vérifiés par `tests/test_dashboards.py` : cartes qui se chevauchent (Metabase les repousse dans un ordre que le code ne décide pas), ligne de grille n'occupant pas les 24 colonnes, titre trop long pour sa carte (~3,4 caractères par colonne : 13 sur une tuile de 4, 17 sur une de 5), requête visant une table absente d'`EXPECTED_TABLES`. Dimensionner aussi les cartes pour leur contenu : un graphique respire sur 8 unités, une table de 18 lignes en demande 12.
- **`width: "full"` sur les dashboards** : le défaut `fixed` enferme la grille dans ~1 000 px et laisse deux marges vides. Posé dans `ensure_dashboard`, jamais à la main dans l'UI. ⚠ `POST /api/dashboard` **ignore silencieusement `width`** : le `PUT` du payload doit être appliqué aussi après une création, sinon un tableau de bord neuf reste en `fixed` alors qu'un tableau de bord reprovisionné passe en `full` — le rendu dépend alors de l'historique de l'instance et le défaut ne se voit qu'après un `make reset`. Un test d'intégration vérifie la largeur réelle.
- **`MB_LOAD_SAMPLE_CONTENT: "false"`** dans `docker-compose.yml` : sans cela Metabase installe une base et un tableau de bord de démonstration e-commerce, invisibles des comptes de restitution mais présents dans la vue d'administration.
- **Barres horizontales (`display: "row"`)** : Metabase pivote le graphique mais pas les clés de réglage. `graph.x_axis.title_text` titre l'axe des **catégories** (vertical) et `graph.y_axis.title_text` celui des **valeurs** (horizontal) — l'inverse de l'intuition. Les quatre cartes en barres horizontales avaient leurs titres d'axes intervertis à l'écran.
- **Deux séries d'ordres de grandeur différents** : sans `graph.y_axis.auto_split: False`, Metabase les place sur deux axes Y distincts et des barres de hauteur comparable représentent des effectifs dans un rapport de 1 à 10.
- **Format des nombres** : `custom-formatting` (`type/Number.number_separators = ", "`) est posé au provisionnement, sinon l'interface française affiche « 14,864 ». Inutile d'y ajouter `date_style` : Metabase ne l'applique pas aux colonnes des requêtes SQL natives.
- **Le refus doit être un vrai refus** : `check-cloisonnement` ne compte comme preuve qu'un échec portant `ACCESS_DENIED` ou `NOT_ENOUGH_PRIVILEGES`. Un `except Exception` nu ferait passer au vert une base absente ou un moteur arrêté.

## État livré — chiffres de référence

Le projet est **complet et fonctionnel**. Ces valeurs sont ancrées par `make test-e2e` : si
l'une d'elles change, c'est qu'une règle a été modifiée, et cela doit être délibéré.

| Couche | Valeurs attendues |
|---|---|
| bronze | patients 16 200 · sejours 15 000 · diagnostics 37 380 · monitoring 66 677 |
| silver | dim_patient 6 000 · fact_sejour 14 864 (rejets 136) · fact_diagnostic 37 040 (cascade 340) · fact_monitoring 64 799 (rejets 1 878) |
| flags | post_mortem 192 · after_discharge **0** (contrôle) · is_alert 3 053 · is_ongoing 1 190 |
| KPI | DMS 6,08 j (6,01 → 6,23 par service) · patients 5 358 · réadmission **687 / 1 421 observables = 48,3 %** (couverture 12,2 %) |
| RGPD | k-anonymat 4 cellules retirées / 1 600 · marges 3 / 200 · 0 cellule reconstructible |
| qualité | **18 règles** = 14 silver + 4 gold |
| tests | **127** = 64 unitaires + 63 d'intégration |

⚠ **Le taux de réadmission ne se lit jamais sur les 11 678 sorties éligibles** : seules
1 421 ont une fenêtre d'observation non vide. Le rapport aux 11 678 donnerait 5,9 %, exact
et trompeur (cf. `docs/RAPPORT.md` §5.3).

## Commandes de référence

```bash
make demo        # démo complète de zéro (up + pipeline + provision) — ~30 s
make pipeline    # pipeline incrémental (jours non encore ingérés)
make quality     # les 18 contrôles qualité du dernier traitement
make test        # 64 tests unitaires ; make test-e2e pour les 63 invariants
make provision   # recrée connexions, permissions et dashboards Metabase
uv run eds run --rebuild          # reconstruit silver+gold après modification du SQL
uv run eds run --date 2026-08-27  # rejeu forcé d'un jour (reprise sur incident)
uv run eds check-cloisonnement    # prouve le cloisonnement aux deux niveaux
```

**Après toute modification** : `uv run ruff check src tests && uv run ruff format src tests`,
puis `uv run eds run --rebuild` (si le SQL a changé) ou `uv run eds provision-metabase` (si
les dashboards ont changé), puis `uv run pytest -q`. Une modification du provisionnement
Metabase se valide sur une instance **neuve** (`make reset && make demo`) : plusieurs
défauts ne se voient que là (cf. `width` ci-dessus).
