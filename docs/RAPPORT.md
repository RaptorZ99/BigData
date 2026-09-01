# Entrepôt de Données de Santé du CHU — dossier de conception

**M2 Big Data · épreuve E05** — de dépôts quotidiens de fichiers hétérogènes à deux
tableaux de bord cloisonnés, avec pseudonymisation dès l'entrée de la zone de travail.

> Tous les chiffres de ce dossier sont ceux de la dernière exécution, et chacun est
> reproductible en une commande (§5.3). La mise en service et l'exploitation sont dans le
> [README](../README.md).

| § | Question |
|---|---|
| [1](#1-le-besoin) | Que veut l'hôpital ? |
| [2](#2-les-données-sources) | Qu'y a-t-il dans les fichiers — et qu'y a-t-il de cassé ? |
| [3](#3-architecture) | Quelle chaîne, et pourquoi celle-là ? |
| [4](#4-qualité-des-données) | Qu'a-t-on écarté, et sur quelle règle ? |
| [5](#5-les-indicateurs) | Que valent les chiffres publiés ? |
| [6](#6-restitution-et-cloisonnement) | Qui voit quoi ? |
| [7](#7-gouvernance-rgpd) | Comment tient la conformité ? |
| [8](#8-limites-et-recommandations) | Ce qu'il ne faut pas conclure de ces données |

---

## 1. Le besoin

Deux publics, deux besoins incompatibles — et c'est précisément ce qui structure le projet.

| Public | Besoin | Ce qu'il obtient | Ce qu'il ne doit **pas** voir |
|---|---|---|---|
| **Direction & cadres** | Piloter l'activité | DMS par service, urgences, réadmissions, alertes de constantes, flux | Rien de nominatif ; pas les cohortes de recherche |
| **Chercheurs cliniciens** | Constituer des cohortes | Prévalence, taille de cohorte, distribution par âge et sexe | Le détail individuel, et **toute cellule < 5 patients** |

Contrainte transverse : les données de santé relèvent de l'**article 9 du RGPD**. La
conformité n'est pas une couche ajoutée à la fin — elle décide de l'architecture. Deux
conséquences structurantes, prises dès le premier jour :

1. **L'identité est détruite avant l'entrepôt**, pas masquée dedans. Le NIR, le nom et le
   prénom ne sont jamais copiés ; l'IPP est remplacé par un pseudonyme au moment même de la
   copie depuis le dépôt du CHU.
2. **Le cloisonnement est porté par le moteur**, pas par l'interface. Deux bases gold, deux
   comptes SQL. Une requête hors périmètre est refusée par ClickHouse, pas cachée par Metabase.

---

## 2. Les données sources

### 2.1 Ce que le CHU dépose

Trois jours de dépôt, cinq domaines, quatre formats — en lecture seule.

| Fichier | Format | Contenu | Volume brut |
|---|---|---|---:|
| `patients/<jour>/patients.csv` | CSV | ⚠ **identité en clair** : IPP, NIR, nom, prénom, date de naissance, sexe, département | 16 200 |
| `sejours/<jour>/sejours.csv` | CSV | Séjour : `stay_id`, patient, service, admission, sortie, modes | 15 000 |
| `diagnostics/<jour>/diagnostics.json` | JSON imbriqué | 1..n codes CIM-10 par séjour | 37 380 |
| `monitoring/<jour>/monitoring.parquet` | Parquet | Constantes au chevet : FC, SpO2, température | 66 677 |
| `referentiels/<jour>/{services,cim10}.csv` | CSV | Nomenclatures, déposées le premier jour | 15 + 10 |

### 2.2 Ce que le profilage a révélé

Explorer avant de coder a évité quatre erreurs de conception. Chacune de ces observations a
une conséquence directe dans la chaîne.

| Observation | Conséquence retenue |
|---|---|
| `patients/` est **cumulatif** — 4 800 → 5 400 → 6 000, chaque jour re-contient les précédents | Déduplication par `argMax` sur le jour d'ingestion : **16 200 lignes → 6 000 patients** |
| ~2 % du monitoring porte FC **et** SpO2 aberrantes **sur les mêmes lignes** (0/500 bpm, 0/120 %), la température restant toujours valide | Signature d'un **capteur en panne**, pas d'un patient en détresse → rejet, et non alerte clinique |
| 1 992 séjours ont une sortie datée mais un mode de sortie vide | Valeur manquante légitime → conservée en `NULL`, signalée, jamais rejetée |
| 220 séjours admis **après un décès antérieur** du même patient | Anomalie de source → conservée et **marquée**, pour ne pas masquer un problème amont |
| 520 relevés horodatés **après la sortie** du patient | Tous rattachés aux 136 séjours à sortie antérieure à l'admission → rejet **en cascade** (§4) |
| 8 362 séjours **chevauchent** le précédent du même patient — plus de la moitié | Artefact du jeu synthétique. Les rejeter viderait l'entrepôt → conservés et documentés. **Mais cela casse un calcul de réadmission naïf** (§5.2) |
| Le monitoring ne couvre que **REA** et **CARDIO** | Les alertes de constantes ne concernent que ces deux services — ce n'est pas une lacune de la chaîne |

---

## 3. Architecture

### 3.1 Vue d'ensemble et justification

```
source-filestorage/   ──▶   data/lake/   ──▶   bronze   ──▶   silver   ──▶   gold ×2   ──▶   Metabase
 dépôt du CHU               copie              tables         constellation   indicateurs      deux tableaux
 (lecture seule)            PSEUDONYMISÉE      typées         Kimball         par usage        cloisonnés
 CSV · JSON · Parquet       HMAC-SHA256 salé
                                               └───────────────────────────────────┘
                                                SQL dans ClickHouse, piloté par dbt

        ops · journal d'ingestion, historique des runs, rapport qualité chiffré
```

| Choix | Alternative écartée | Raison |
|---|---|---|
| **ClickHouse** comme entrepôt | PostgreSQL | Colonne, compressé, conçu pour l'agrégation. Le monitoring seul justifie ce choix ; il lit le Parquet directement, sans passer par Python |
| **Pseudonymiser au lake**, pas en bronze | Charger puis anonymiser | Un chargement intermédiaire laisserait l'identité dans le moteur, ne serait-ce qu'un instant. Ici elle ne l'atteint jamais |
| **dbt** pour silver et gold | SQL ordonné à la main | dbt déduit l'ordre d'exécution du graphe des `ref()` — plus aucune convention de nommage à respecter — et exécute **78 tests pendant** le run, pas après |
| **Python n'orchestre que** | pandas | Sortir les données du moteur pour les transformer ne passe pas à l'échelle. Seuls les deux CSV à pseudonymiser traversent Python, en flux ligne à ligne, à mémoire constante |
| **Deux bases gold** | Une base + des vues | Le cloisonnement devient un `GRANT`, donc une propriété du moteur, et non une règle applicative |
| **Partition bronze par jour** | Table unique | Rejouer un jour = `DROP PARTITION` + rechargement. L'idempotence est structurelle, pas défendue par du code |

ClickHouse et dbt ne sont pas concurrents : **ClickHouse stocke et calcule ; dbt envoie le
SQL dans le bon ordre et teste le résultat.** dbt ne stocke rien et ne calcule rien.

### 3.2 Le modèle de données

Silver est modélisé en **constellation Kimball : trois étoiles, une par fait**, sur
dimensions conformées.

![Modèle de données de l'entrepôt](img/eds-data-model.png)

| Fait | Grain | Dimensions | Lignes |
|---|---|---|---:|
| `fact_sejour` | un séjour | `dim_patient`, `dim_service` | 14 864 |
| `fact_diagnostic` | un code CIM-10 par séjour | `dim_patient`, `dim_cim10` | 37 040 |
| `fact_monitoring` | un relevé (`stay_id`, `ts`) | `dim_service` | 64 799 |

Trois propriétés à retenir :

- **Chaque fait porte les clés de ses propres dimensions**, propagées au build silver. Il
  n'y a donc **aucune jointure fait-à-fait** dans le modèle ni dans les requêtes gold — un
  produit croisé entre deux tables de faits gonflerait silencieusement tous les comptages.
- **`stay_id` est la dimension dégénérée** commune aux trois faits : c'est elle qui permet
  le *drill-across* (partir d'une alerte de constante et remonter au séjour).
- **Les mesures non additives sont isolées.** `nb_patients` ne se somme jamais hors de son
  grain : la pyramide des âges lit une table au grain sexe × tranche, pas la table au grain
  CIM-10 × sexe × tranche — sinon un patient à cinq diagnostics serait compté cinq fois.

Source PlantUML : [`data-model.puml`](data-model.puml). Un test
(`tests/test_data_model.py`) échoue si une table est ajoutée sans figurer au diagramme : le
schéma ne peut pas se périmer en silence.

### 3.3 Déploiement cloud

La même chaîne tourne sur Azure, décrite en Terraform, et **les invariants ne bougent pas
d'une unité** — c'était le critère d'acceptation. Le stockage objet remplace le dossier
local, un job planifié remplace cron, ClickHouse lit le lake par `azureBlobStorage()`.

Le cloud ajoute un **quatrième niveau de cloisonnement** que le local ne peut pas offrir :
les droits IAM sont attribués **par conteneur de stockage**. La machine qui héberge
l'entrepôt n'a aucun droit sur le conteneur contenant les noms et les NIR. Ce n'est plus une
règle de code — c'est une propriété de l'infrastructure, et `terraform plan` doit rester
vide pour qu'elle le demeure. Détail : [`terraform/README.md`](../terraform/README.md).

Coût mesuré : ~30 €/mois allumé, ~5 € en pause.

---

## 4. Qualité des données

Principe constant : **on écarte, on trace, on ne corrige jamais en silence.** Toute ligne
rejetée part dans une table `*_rejets` avec son motif, et reste consultable.

Trois natures de règles, à ne pas confondre :

- **Rejet** — la ligne quitte l'entrepôt ;
- **Signalement** — la ligne est **conservée** mais marquée (anomalie légitime, ou de la source) ;
- **Contrôle** — vérification attendue à zéro, dont le passage au vert est l'information.

| Règle | Nature | Lues | Conservées | Écartées | Signalées |
|---|---|---:|---:|---:|---:|
| **Q1** Patients redéposés chaque jour | Déduplication | 16 200 | 6 000 | 10 200 | — |
| **Q2** Sortie antérieure à l'admission | Rejet | 15 000 | 14 864 | 136 | — |
| **Q4** Constantes hors plage physiologique | Rejet | 66 677 | 64 799 | 1 369 | — |
| **C1** Relevé dont le séjour est écarté | Cascade | 66 677 | 64 799 | 520 | — |
| **C2** Diagnostic dont le séjour est écarté | Cascade | 37 380 | 37 040 | 340 | — |
| **Q3** Séjour sans date de sortie | Signalement | 14 864 | 14 864 | 0 | 1 190 |
| **Q5** Sortie datée, mode non renseigné | Signalement | 14 864 | 14 864 | 0 | 1 975 |
| **Q7** Admission après un décès antérieur | Signalement | 14 864 | 14 864 | 0 | 192 |
| **Q8** Relevé postérieur à la sortie | Contrôle | 64 799 | 64 799 | 0 | **0** |
| **Q6** Formats et intégrité référentielle (5 règles) | Contrôle | — | — | 0 | **0** |

Avec les quatre contrôles RGPD de la couche gold (§7), `ops.quality_report` compte
**dix-huit règles**, recalculées à chaque run et affichées au bas du tableau de bord de
pilotage.

Trois décisions à défendre :

- **Une sortie non renseignée n'est pas une anomalie** — c'est un patient encore
  hospitalisé. Les 1 190 séjours concernés sont conservés, marqués, et exclus du seul calcul
  où ils fausseraient le résultat : la DMS.
- **Les cascades ne sont pas cosmétiques.** Un relevé dont le séjour parent est écarté ne
  peut pas recevoir son code de service — ce code vient du séjour. Le garder produirait une
  ligne inexploitable.
- **Q8 est passé de 520 à zéro, et c'est un résultat.** Ces 520 relevés « post-sortie »
  appartenaient **tous** aux 136 séjours dont la sortie précède l'admission : une telle
  sortie rend mécaniquement tout relevé postérieur à la sortie. Q8 n'était qu'un symptôme de
  Q2. Le contrôle est conservé, désormais attendu à zéro.

**Traçabilité.** Chaque ligne de bronze et de silver porte son fichier d'origine, son jour
de dépôt et son horodatage de traitement. Chaque exécution est enregistrée dans
`ops.pipeline_runs` ; `ops.ingest_log` relie chaque fichier au run qui l'a chargé.

---

## 5. Les indicateurs

Tous sont calculés dans l'entrepôt et exposés en tables agrégées. Les requêtes des tableaux
de bord se réduisent à des `SELECT` : aucun calcul métier n'est enfoui dans Metabase.

### 5.1 Définitions et résultats

| Indicateur | Définition retenue | Résultat |
|---|---|---|
| **DMS par service** | Moyenne de `sortie − admission`, par service et jour de sortie. **Séjours en cours exclus** — une durée partielle tirerait la moyenne vers le bas et simulerait une amélioration | **6,08 j** (6,01 cardio → 6,23 urgences) |
| **Activité des urgences** | Deux acceptions légitimes, **publiées côte à côte** : séjours dont le *service* est URGENCES, et admissions en *mode* urgence tous services. La seconde vaut 2,7× la première | 581→639 /j et 1 627→1 721 /j |
| **Réadmission à 30 j** | Existe-t-il, pour le même patient, **une** admission dans les 30 jours suivant sa sortie ? Dénominateur : sorties **vivantes** — un patient décédé ne peut pas être réadmis | **687 / 1 421 = 48,3 %** (§5.2) |
| **Alertes de constantes** | FC hors [40 ; 130] **ou** SpO2 < 90 % **ou** T ≥ 38,5 °C. Distinct des rejets : une FC à 500 bpm est un capteur en panne, écartée en amont | **3 053 / 64 799 = 4,7 %** |
| **Taille de cohorte** | Nombre de **patients distincts** portant un diagnostic — pas de séjours. Un patient hospitalisé trois fois compte une fois | 2 689 → 2 764 |
| **Prévalence** | Part des 5 358 patients ayant au moins un séjour. Dénominateur calculé comme scalaire indépendant, **jamais par jointure** entre deux faits | cf. §8 |

Les seuils d'alerte sont des **hypothèses de travail**, à valider avec les équipes
soignantes avant tout usage réel.

### 5.2 Le taux de réadmission : l'indicateur qui demandait le plus de soin

Deux pièges, dont un qui aurait produit un chiffre faux publié en toute confiance.

**Piège 1 — la fonction de fenêtrage.** La première implémentation regardait l'admission
chronologiquement *suivante*. Sur des données normales, c'est équivalent. Ici, avec 8 362
séjours qui se chevauchent (§2.2), l'admission « suivante » est souvent un séjour concurrent
commencé **avant** la sortie considérée, qui masque la réadmission réelle survenue plus
tard. Le comptage tombait de **687 à 370** — près de la moitié perdue. Correction : tester
**l'ensemble** des admissions du patient. C'est aussi la définition cliniquement correcte.

**Piège 2 — la fenêtre d'observation, et c'est celui qui commande le chiffre publié.** Nos
admissions s'arrêtent au 28 août ; les sorties s'étalent jusqu'au 9 septembre.

| Jour de sortie | Sorties | Réadmissions | Taux | Fenêtre observable |
|---|---:|---:|---:|---:|
| 26 août | 133 | 115 | 86,5 % | 3 j sur 30 |
| 27 août | 474 | 323 | 68,1 % | 2 j sur 30 |
| 28 août | 814 | 249 | 30,6 % | 1 j sur 30 |
| 29 août → 9 septembre | 10 257 | 0 | 0 % | **aucune** |

Agréger ces lignes donnerait **5,9 %** — arithmétiquement exact, et parfaitement trompeur :
**88 % du dénominateur ne mesure rien.** Nous publions donc **687 / 1 421 sorties
observables = 48,3 %**, avec la couverture affichée à côté (12,2 % des sorties ; aucune ne
dispose des 30 jours complets), et l'avertissement placé **au-dessus** des graphiques qu'il
qualifie — un avertissement sous le chiffre qu'il corrige n'est pas lu.

![Réadmissions et couverture de l'indicateur](img/pilotage-readmissions.jpg)

Ce 48,3 % n'est pas non plus un taux de réadmission à 30 jours au sens clinique : il porte
sur une fenêtre de un à trois jours. Il est publié parce qu'il mesure quelque chose de réel,
accompagné de sa portée, plutôt que dilué dans un chiffre qui n'en mesure aucun.

### 5.3 Retrouver n'importe quel chiffre

| Chiffre affiché | Valeur | Table gold | Expression déterminante |
|---|---:|---|---|
| Séjours pris en charge | 14 864 | `kpi_synthese` | `count()` sur `fact_sejour` |
| Patients suivis | 5 358 | `kpi_synthese` | `uniqExact(patient_pseudo)` |
| DMS globale | 6,08 j | `kpi_synthese` | `avg(duree_jours)` **où** `discharge_ts IS NOT NULL` |
| DMS par service | 6,01 → 6,23 j | `kpi_dms_service` | `sum(dms × nb_sorties) / sum(nb_sorties)` — moyenne **repondérée** ; une moyenne de moyennes serait fausse |
| Réadmissions | 687 / 1 421 | `kpi_readmissions_30j` | `arrayExists(adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY, admissions_du_patient)` |
| Relevés en alerte | 3 053 / 64 799 | `kpi_alertes_monitoring` | `countIf(is_alert)` |
| Séjours en cours | 1 190 | `kpi_synthese` | `countIf(is_ongoing)` |
| Pyramide des âges | total 5 358 | `cohorte_demographie_globale` | grain sexe × tranche : un patient compté **une** fois |
| Cellules supprimées (k<5) | 4 / 1 600 | `k_anonymat_controle` | cellules calculées − cellules diffusées |

Trois commandes rejouent l'ensemble : `make quality` (les 18 règles), `make test-e2e` (les
63 invariants, dont chacun de ces chiffres), `uv run eds check-cloisonnement`. **La suite
d'intégration ancre ces valeurs** : modifier une règle sans le vouloir fait échouer un test
nommé, cela ne fait pas dériver un chiffre en silence.

---

## 6. Restitution et cloisonnement

**🏥 Pilotage** se lit par bandes : chiffres clés → activité → surveillance → réadmissions →
flux → **fiabilité**. Cette dernière bande distingue ce tableau de bord d'un tableau de bord
ordinaire : un utilisateur qui doute d'un chiffre voit, sans quitter l'interface et sans
accès à la base d'exploitation, combien de lignes ont été écartées et par quelle règle.

![Rapport qualité et journal d'ingestion](img/rapport-qualite-dashboard.jpg)

**🔬 Recherche** présente cohortes, prévalence, distribution par âge et sexe. L'en-tête porte
deux avertissements d'égale importance : le seuil de cinq patients, et le fait que ces
prévalences n'ont **aucune valeur clinique** (§8).

![Tableau de bord de recherche](img/dashboard-recherche.jpg)

La mise en page est **du code**, pas un réglage d'interface : quatre défauts que seul l'écran
révèle (chevauchement, grille incomplète, titre trop long, requête visant une table absente)
sont vérifiés par des tests avant même de provisionner.

### Le cloisonnement, à quatre niveaux

| Niveau | Mécanisme | Effet |
|---|---|---|
| **Infrastructure** *(Azure)* | Droits IAM par **conteneur**, pas par compte | La machine de l'entrepôt n'a aucun droit sur le conteneur contenant les NIR |
| **Base de données** | Deux comptes SQL, chacun `SELECT` sur sa seule base gold | Un accès hors périmètre est refusé **par le moteur** |
| **Connexion Metabase** | Une connexion par usage, avec le compte SQL correspondant | Aucune requête ne peut viser l'autre base |
| **Contenu Metabase** | Une collection par usage, visible du seul groupe concerné | Chaque utilisateur ne voit qu'un tableau de bord |

Les deux derniers organisent l'interface ; les deux premiers opposent un refus réel.

Ce que voit un utilisateur **pilotage** — une seule collection, une seule base. Il n'y a
**pas de contenu grisé** : l'autre usage n'existe pas de son point de vue.

![Ce que voit un utilisateur pilotage](img/cloisonnement-vue-pilotage.jpg)

S'il devine l'adresse de l'espace de recherche, il est refusé. Metabase répond « page
introuvable » et non « accès refusé » : un refus explicite confirmerait l'existence de la
ressource et permettrait de l'énumérer par essais successifs.

![Accès refusé hors périmètre](img/cloisonnement-acces-refuse.jpg)

**Une capture se périme et ne prouve rien.** La démonstration qui compte est
`uv run eds check-cloisonnement` : elle se connecte réellement avec chaque compte et rejoue
**9 scénarios** aux deux niveaux, sur l'installation de celui qui la lance. Les mêmes 9 sont
exécutés par `make test-e2e` — une régression du cloisonnement ne peut pas passer inaperçue.

Dernière précaution, de disponibilité et non de confidentialité : les deux comptes
autorisent le SQL libre. Un profil (`readonly = 2`, temps et mémoire bornés) et un quota
horaire empêchent une requête emballée de priver l'autre usage de son tableau de bord.

---

## 7. Gouvernance RGPD

### 7.1 Minimisation

| Donnée source | Traitement | Motif |
|---|---|---|
| `nir`, `nom`, `prenom` | **Jamais copiés** | Directement identifiants, et aucun indicateur n'en a besoin |
| `patient_id` (IPP) | `HMAC-SHA256(sel, IPP)` dès la copie vers le lake | Stable — les jointures tiennent — et non réversible sans le sel, qui n'est ni versionné ni journalisé |
| `birth_date` | Généralisée en `birth_year` | Suffit à l'âge en tranches ; le jour et le mois sont ré-identifiants |
| Constantes (`fact_monitoring`) | Ne porte **même pas** le pseudonyme | Le service et le séjour suffisent aux alertes |

Un test d'intégration vérifie qu'aucune colonne nommée `nir`, `nom`, `prenom`,
`birth_date` ou `patient_id` n'existe dans **aucune** base de l'entrepôt.

### 7.2 Petits effectifs : le seuil ne suffit pas

Toute table diffusée à la recherche applique `HAVING uniqExact(patient_pseudo) >= 5`, et les
âges sont publiés en tranches de dix ans. Aux grains courants, les cohortes comptent des
centaines de patients : le mécanisme resterait invisible. D'où une vue au grain le plus fin
— pathologie × sexe × tranche × département — où la règle mord réellement.

**Et c'est là que le piège classique apparaît.** Publier une vue agrégée **et** sa
décomposition, en appliquant le seuil séparément aux deux, laisse fuiter les cellules
supprimées :

```
   total de la marge  −  somme des cellules fines diffusées  =  cellule cachée
```

Une simple jointure entre nos deux tables, **avec le seul compte chercheur et sans aucun
privilège particulier**, reconstituait la pathologie, le sexe, la tranche d'âge, le
département et l'effectif exact des patients censés être protégés.

Parade appliquée : la **suppression complémentaire** — une marge n'est diffusée que si toute
sa décomposition l'est. Dès qu'une cellule fine tombe sous le seuil, la ligne agrégée
disparaît aussi ; il n'y a plus rien à soustraire.

| Vue | Calculées | Diffusées | Supprimées | Motif |
|---|---:|---:|---:|---|
| Grain fin (× département) | 1 600 | 1 596 | **4** | seuil k ≥ 5 |
| Marge (pathologie × sexe × âge) | 200 | 197 | **3** | décomposition incomplète |

Coût assumé : trois lignes agrégées sur deux cents. Une donnée dont la diffusion permettrait
d'en déduire une autre ne se diffuse pas, même agrégée.

![Protection des petits effectifs et son effet mesuré](img/recherche-k-anonymat.jpg)

Deux précautions en découlent : la table de travail qui porte les effectifs sous le seuil vit
en `eds_silver`, **hors de portée des comptes de restitution** ; et **l'attaque est rejouée à
chaque exécution** de la suite d'intégration, qui exige qu'elle ne rende rien.

### 7.3 Contrôles automatiques

Quatre règles RGPD tournent à chaque run, chiffrées dans `ops.quality_report` au même titre
que les contrôles de qualité :

| Règle | Ce qu'elle mesure | Attendu |
|---|---|---|
| `RGPD_k_anonymat` | Cellules retirées par le seuil, au grain le plus fin | 4 / 1 600 |
| `RGPD_suppression_complementaire` | Marges retirées, décomposition incomplète | 3 / 200 |
| `RGPD_cohortes_diffusees` | Cohortes par pathologie effectivement diffusées | 10 / 10 |
| `RGPD_minimisation` | Colonnes identifiantes **ou pseudonyme** dans la base recherche | **0** |

### 7.4 Registre des hypothèses

Ce que nous avons tranché sans que le sujet le fasse, et qu'il faudrait valider :

1. Les seuils d'alerte des constantes (§5.1) ;
2. l'exclusion des patients décédés du dénominateur des réadmissions ;
3. l'exclusion des séjours en cours du calcul de la DMS ;
4. le maintien des séjours chevauchants, jugés artefacts du jeu de données ;
5. le seuil k = 5, retenu d'après l'énoncé — certaines autorités en recommandent un plus élevé.

---

## 8. Limites et recommandations

**⚠ La limite qui prime toutes les autres.** Les diagnostics du jeu de données sont tirés au
hasard : les dix pathologies ont chacune ~51 % de prévalence, pour une somme de **508,9 %**
(≈ 5 diagnostics par patient), **sans corrélation** avec le service, l'âge ou le sexe. Les
cohortes valident la chaîne de traitement, **pas** une conclusion épidémiologique. Cet
avertissement figure en tête du tableau de bord de recherche, pas seulement ici.

| Limite | Portée | Recommandation |
|---|---|---|
| Fenêtre d'observation de 1 à 3 jours | Le taux de réadmission ne couvre que 12,2 % des sorties | Attendre **60 jours d'historique** avant de publier cet indicateur en production |
| 8 362 séjours chevauchants | Artefact synthétique, mais il a déjà cassé un calcul (§5.2) | Vérifier sur données réelles ; si le chevauchement persiste, c'est un problème du système source |
| Âge dérivé de la seule année | Approximation d'un an au plus | Conséquence assumée de la minimisation — ne pas revenir sur `birth_year` pour la corriger |
| Monitoring limité à REA et CARDIO | Les alertes ne couvrent pas tout l'hôpital | Étendre l'équipement, ou afficher la couverture à côté du taux |
| Trois jours de dépôt | Volumétrie de démonstration | Le banc d'essai (`benchmarks/`) valide 20 M de relevés par le chemin réel du pipeline |
| Seuils d'alerte non validés cliniquement | Le nombre d'alertes en dépend directement | Faire arbitrer par les équipes soignantes avant tout usage |

**Trois recommandations de gouvernance**, qui relèvent de l'organisation et non du code :

1. Conserver le sel de pseudonymisation dans un coffre, avec une procédure de rotation
   documentée — le changer casse toutes les jointures historiques : c'est une décision, pas
   une manipulation.
2. Faire valider le seuil k = 5 par le délégué à la protection des données.
3. Revoir les hypothèses de §7.4 à chaque évolution du besoin métier.

---

*Énoncé de l'épreuve : [`FICHE-SUJET.md`](FICHE-SUJET.md) · Mise en service et exploitation :
[`README`](../README.md) · Infrastructure Azure : [`terraform/README.md`](../terraform/README.md)*
