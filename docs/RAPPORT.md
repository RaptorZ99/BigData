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

Vingt-huit jours de dépôt (1er → 28 août), cinq domaines, quatre formats — en lecture
seule. Tout n'arrive pas tous les jours : les référentiels une fois, le premier jour ; les
patients trois fois, en fin de période, et à chaque fois en intégralité.

| Fichier | Format | Contenu | Jours | Volume brut |
|---|---|---|---:|---:|
| `patients/<jour>/patients.csv` | CSV | ⚠ **identité en clair** : IPP, NIR, nom, prénom, date de naissance, sexe, département | 3 | 18 000 (3 × 6 000) |
| `sejours/<jour>/sejours.csv` | CSV | Séjour : `stay_id`, patient, service, admission, sortie, modes | 28 | 6 797 |
| `diagnostics/<jour>/diagnostics.json` | JSON imbriqué | 1..n codes CIM-10 par séjour | 28 | 12 720 |
| `monitoring/<jour>/monitoring.parquet` | Parquet | Constantes au chevet : FC, SpO2, température | 28 | 41 778 |
| `referentiels/<jour>/{services,cim10}.csv` | CSV | Nomenclatures | 1 | 8 + 13 |

Le jeu est **synthétique** — c'est celui de l'épreuve — et il est versionné avec le code
pour que le projet se lance après un simple clone. Dans un déploiement réel, ce dépôt ne
serait jamais dans Git.

### 2.2 Ce que le profilage a révélé

Explorer avant de coder a évité plusieurs erreurs de conception. Chacune de ces
observations a une conséquence directe dans la chaîne.

| Observation | Conséquence retenue |
|---|---|
| `patients/` est redéposé **en intégralité** à chaque fois — 6 000 lignes, trois fois — et **118 patients changent de département** d'un dépôt à l'autre | Déduplication par `argMax` sur le jour d'ingestion : **18 000 lignes → 6 000 patients**, chacun dans sa version la plus récente. Un test vérifie que la dimension ne porte aucune version périmée |
| ~2 % du monitoring porte FC **et** SpO2 aberrantes **sur les mêmes lignes** (0/500 bpm, 0/120 %), la température restant toujours valide | Signature d'un **capteur en panne**, pas d'un patient en détresse → rejet, et non alerte clinique |
| 683 séjours sans date de sortie — et le mode de sortie n'est vide **que** dans ce cas | Patient encore hospitalisé → conservé, signalé, exclu de la seule DMS |
| 68 séjours dont la sortie **précède** l'admission | Incohérence temporelle → rejet, et avec eux 528 relevés et 127 diagnostics, **en cascade** (§4) |
| 136 séjours admis **après un décès antérieur** du même patient | Anomalie de source → conservée et **marquée**, pour ne pas masquer un problème amont |
| Aucun séjour ne chevauche le précédent du même patient ; 1,13 séjour par patient, 3 au plus | Le calcul de réadmission est néanmoins écrit pour résister aux chevauchements (§5.2) : la bonne définition ne dépend pas de la propreté du jeu |
| 13 codes CIM-10, dont trois maladies rares portées par 8, 4 et 3 patients | Le seuil de 5 patients **retire deux pathologies entières** de la base de recherche (§7.2) |
| Activité **inégale** entre services — 1 615 séjours en cardiologie, 212 en oncologie — et 49 % des admissions en mode urgence | Les indicateurs par service discriminent réellement : la DMS va de 2 à 9 jours (§5.1) |
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
| **dbt** pour silver et gold | SQL ordonné à la main | dbt déduit l'ordre d'exécution du graphe des `ref()` — plus aucune convention de nommage à respecter — et exécute **72 tests pendant** le run, pas après |
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
| `fact_sejour` | un séjour | `dim_patient`, `dim_service` | 6 729 |
| `fact_diagnostic` | un code CIM-10 par séjour | `dim_patient`, `dim_cim10` | 12 593 |
| `fact_monitoring` | un relevé (`stay_id`, `ts`) | `dim_service` | 40 400 |

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
| **Q1** Patients redéposés à chaque dépôt | Déduplication | 18 000 | 6 000 | 12 000 | — |
| **Q2** Sortie antérieure à l'admission | Rejet | 6 797 | 6 729 | 68 | — |
| **Q4** Constantes hors plage physiologique | Rejet | 41 778 | 40 400 | 858 | — |
| **C1** Relevé dont le séjour est écarté | Cascade | 41 778 | 40 400 | 528 | — |
| **C2** Diagnostic dont le séjour est écarté | Cascade | 12 720 | 12 593 | 127 | — |
| **Q3** Séjour sans date de sortie | Signalement | 6 729 | 6 729 | 0 | 683 |
| **Q5** Sortie datée, mode non renseigné | Signalement | 6 729 | 6 729 | 0 | 0 |
| **Q7** Admission après un décès antérieur | Signalement | 6 729 | 6 729 | 0 | 136 |
| **Q8** Relevé postérieur à la sortie | Contrôle | 40 400 | 40 400 | 0 | **0** |
| **Q6** Formats et intégrité référentielle (5 règles) | Contrôle | — | — | 0 | **0** |

Q4 et C1 se recoupent sur 8 relevés, qui portent les deux motifs : 1 378 lignes de monitoring
écartées au total, chacune avec **tous** ses motifs.

Avec les quatre contrôles RGPD de la couche gold (§7), `ops.quality_report` compte
**dix-huit règles**, recalculées à chaque run et affichées au bas du tableau de bord de
pilotage.

Trois décisions à défendre :

- **Une sortie non renseignée n'est pas une anomalie** — c'est un patient encore
  hospitalisé. Les 683 séjours concernés sont conservés, marqués, et exclus du seul calcul
  où ils fausseraient le résultat : la DMS.
- **Les cascades ne sont pas cosmétiques.** Un relevé dont le séjour parent est écarté ne
  peut pas recevoir son code de service — ce code vient du séjour. Le garder produirait une
  ligne inexploitable.
- **Q8 vaut zéro, et c'est un résultat.** Les relevés postérieurs à la sortie appartiennent
  tous aux 68 séjours dont la sortie précède l'admission — une telle sortie rend
  mécaniquement tout relevé « postérieur ». Q8 n'est qu'un symptôme de Q2 : une fois ceux-ci
  écartés en cascade, le contrôle passe au vert, et il est conservé pour cette raison. Même
  logique pour Q5, à zéro sur ce jeu : c'est la règle qui fait l'entrepôt, pas le jeu de
  données.

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
| **DMS par service** | Moyenne de `sortie − admission`, par service et jour de sortie. **Séjours en cours exclus** — une durée partielle tirerait la moyenne vers le bas et simulerait une amélioration | **5,15 j** — de 2,15 aux urgences à 9,05 en réanimation |
| **Activité des urgences** | Deux acceptions légitimes, **publiées côte à côte** : séjours dont le *service* est URGENCES, et admissions en *mode* urgence tous services. La seconde vaut 2,3× la première | 9 → 82 passages/j ; 18 → 158 admissions/j |
| **Réadmission à 30 j** | Existe-t-il, pour le même patient, **une** admission dans les 30 jours suivant sa sortie ? Dénominateur : sorties **vivantes** — un patient décédé ne peut pas être réadmis | **647 / 4 499 = 14,4 %**, sur 89 % des sorties (§5.2) |
| **Alertes de constantes** | FC hors [40 ; 130] **ou** SpO2 < 90 % **ou** T ≥ 38,5 °C. Distinct des rejets : une FC à 500 bpm est un capteur en panne, écartée en amont | **1 939 / 40 400 = 4,8 %** |
| **Taille de cohorte** | Nombre de **patients distincts** portant un diagnostic — pas de séjours. Un patient hospitalisé trois fois compte une fois | de 8 (amyotrophie spinale) à 2 219 (infections urinaires) — 11 pathologies diffusées sur 13 |
| **Prévalence** | Part des 5 949 patients ayant au moins un séjour. Dénominateur calculé comme scalaire indépendant, **jamais par jointure** entre deux faits | 37,3 % → 0,13 % |

La DMS est ordonnée comme on l'attend cliniquement — urgences courtes, réanimation longue —
et ne l'est que parce que les séjours en cours en sont exclus. Les seuils d'alerte sont des
**hypothèses de travail**, à valider avec les équipes soignantes avant tout usage réel.

### 5.2 Le taux de réadmission : l'indicateur qui demandait le plus de soin

**Définition robuste.** On teste **toutes** les admissions du patient, pas seulement la
suivante. Sur ce jeu, aucun séjour ne se chevauche et les deux écritures donnent le même
compte ; sur des données réelles, l'admission « suivante » est souvent un séjour concurrent
commencé avant la sortie, qui masque la réadmission réelle. La bonne définition ne doit pas
dépendre de la propreté du jeu.

**Le piège : la fenêtre d'observation.** Une réadmission ne peut être constatée que si
l'entrepôt couvre la période où elle surviendrait. Les admissions s'arrêtent au 28 août ;
les sorties s'étalent du 2 août au 14 septembre. Une sortie du 2 août dispose de 27 jours
d'observation, une sortie du 27 août d'un seul, une sortie de septembre d'**aucun**.

| Fenêtre observable | Sorties | Réadmissions | Taux |
|---|---:|---:|---:|
| 22 à 27 jours | 471 | 120 | 25,5 % |
| 15 à 21 jours | 1 306 | 287 | 22,0 % |
| 8 à 14 jours | 1 406 | 194 | 13,8 % |
| 1 à 7 jours | 1 316 | 46 | 3,5 % |
| aucune — sortie après le 28 août | 552 | 0 | 0 % |

Le taux **croît avec la fenêtre** : c'est la signature d'une censure à droite, pas d'une
tendance. Agréger tout donnerait 12,8 % ; publier un « taux à 30 jours » alors qu'aucune
sortie n'a trente jours serait arithmétiquement exact et faux.

**Ce que nous publions** : **647 réadmissions sur 4 499 sorties observables, soit 14,4 %**,
avec la couverture affichée à côté (89,1 % des sorties ; fenêtre maximale 27 jours) et
l'avertissement placé **au-dessus** des graphiques qu'il qualifie — un avertissement sous le
chiffre qu'il corrige n'est pas lu. Ce 14,4 % est une **borne basse** : les sorties les mieux
observées tournent autour de 25 %, et soixante jours d'historique permettraient de le
confirmer (§8).

![Réadmissions et couverture de l'indicateur](img/pilotage-readmissions.jpg)

Par service, le taux va de 10,7 % en réanimation à 18 % en oncologie et en pédiatrie — un
classement à lire avec la même précaution, les services n'ayant pas le même profil de sortie
dans la fenêtre observable.

### 5.3 Retrouver n'importe quel chiffre

| Chiffre affiché | Valeur | Table gold | Expression déterminante |
|---|---:|---|---|
| Séjours pris en charge | 6 729 | `kpi_synthese` | `count()` sur `fact_sejour` |
| Patients suivis | 5 949 | `kpi_synthese` | `uniqExact(patient_pseudo)` |
| DMS globale | 5,15 j | `kpi_synthese` | `avg(duree_jours)` **où** `discharge_ts IS NOT NULL` |
| DMS par service | 2,15 → 9,05 j | `kpi_dms_service` | `sum(dms × nb_sorties) / sum(nb_sorties)` — moyenne **repondérée** ; une moyenne de moyennes serait fausse |
| Réadmissions | 647 / 4 499 | `kpi_readmissions_30j` | `arrayExists(adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY, admissions_du_patient)` |
| Relevés en alerte | 1 939 / 40 400 | `kpi_alertes_monitoring` | `countIf(is_alert)` |
| Séjours en cours | 683 | `kpi_synthese` | `countIf(is_ongoing)` |
| Pyramide des âges | total 5 949 | `cohorte_demographie_globale` | grain sexe × tranche : un patient compté **une** fois |
| Pathologies diffusées | 11 / 13 | `cohorte_pathologie` | `HAVING uniqExact(patient_pseudo) >= 5` |
| Cellules supprimées (k<5) | 178 / 1 083 | `k_anonymat_controle` | cellules calculées − cellules diffusées |

Trois commandes rejouent l'ensemble : `make quality` (les 18 règles), `make test-e2e` (les
66 invariants, dont chacun de ces chiffres), `uv run eds check-cloisonnement`. **La suite
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
âges sont publiés en tranches de dix ans. Le seuil mord dès le premier niveau : la
mucoviscidose (4 patients) et la trisomie 21 (3) disparaissent de la cohorte par pathologie,
de la prévalence et de toute vue démographique — elles existent dans le référentiel et en
silver, nulle part dans la base des chercheurs. Au grain le plus fin — pathologie × sexe ×
tranche d'âge × département — 178 cellules sur 1 083 tombent sous le seuil.

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
| Cohorte par pathologie | 13 | 11 | **2** | seuil k ≥ 5 |
| Grain fin (× département) | 1 083 | 905 | **178** | seuil k ≥ 5 |
| Marge (pathologie × sexe × âge) | 149 | 83 | **66** | décomposition incomplète |

Le coût est assumé, et il est élevé : 66 marges sur 149, soit 44 %. C'est le prix d'un grain
à huit départements sur des cohortes de quelques centaines de patients — dès qu'une marge
compte moins d'une soixantaine de patients, l'un de ses départements passe presque sûrement
sous le seuil. Une donnée dont la diffusion permettrait d'en déduire une autre ne se diffuse
pas, même agrégée ; c'est le grain départemental lui-même qu'il faudrait revoir (§8).

**Une table protégée ne se ré-agrège pas — et c'est le piège suivant.** Le graphique de part
de femmes sommait les tranches d'âge de la table protégée. L'opération est pourtant licite au
sens de l'additivité : un patient n'appartient qu'à une tranche. Mais les cellules qui
manquent à cette table ne manquent pas au hasard, ce sont les plus petites — et le ratio
calculé sur ce qui reste dérivait de **neuf points** : 71,5 % de femmes pour les infections
urinaires, contre 62,5 % en réalité. Un chiffre faux, présenté sans le moindre signe
extérieur d'erreur.

La règle qui en découle est plus forte que « ne pas sommer une mesure non additive » : **un
agrégat se calcule à son propre grain, jamais à partir d'une table filtrée.** La répartition
par sexe a donc sa table, `cohorte_demographie_sexe`, bâtie depuis silver puis soumise au
seuil — et à la suppression complémentaire, puisque `cohorte_pathologie` publie l'effectif
total et livrerait la cellule manquante par soustraction. Un test compare chaque pourcentage
publié à la vérité de silver et n'admet aucun écart.

![Protection des petits effectifs et son effet mesuré](img/recherche-k-anonymat.jpg)

Deux précautions en découlent : la table de travail qui porte les effectifs sous le seuil vit
en `eds_silver`, **hors de portée des comptes de restitution** ; et **l'attaque est rejouée à
chaque exécution** de la suite d'intégration, qui exige qu'elle ne rende rien.

### 7.3 Contrôles automatiques

Quatre règles RGPD tournent à chaque run, chiffrées dans `ops.quality_report` au même titre
que les contrôles de qualité :

| Règle | Ce qu'elle mesure | Attendu |
|---|---|---|
| `RGPD_k_anonymat` | Cellules retirées par le seuil, au grain le plus fin | 178 / 1 083 |
| `RGPD_suppression_complementaire` | Marges retirées, décomposition incomplète | 66 / 149 |
| `RGPD_cohortes_diffusees` | Cohortes par pathologie effectivement diffusées | 11 / 13 |
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

**⚠ La limite qui prime toutes les autres.** Le jeu de données est synthétique. Ses
prévalences ont des ordres de grandeur plausibles — 37 % d'infections urinaires, 4 % de
cancers bronchiques, 0,1 % d'amyotrophie spinale — mais elles sont générées et ne décrivent
aucune population. Les cohortes valident la chaîne de traitement, **pas** une conclusion
épidémiologique. Cet avertissement figure en tête du tableau de bord de recherche.

| Limite | Portée | Recommandation |
|---|---|---|
| Aucune sortie n'a 30 jours d'observation (27 au plus) | Le taux de réadmission publié est une borne basse (§5.2) | Attendre **60 jours d'historique** avant de publier cet indicateur en production |
| Suppression complémentaire coûteuse : 44 % des marges | Le grain départemental protège peu de patients, retire beaucoup de lignes, et rend la table inexploitable pour tout ré-agrégat (§7.2) | Publier le grain fin par **région** plutôt que par département, ou le réserver à un accès sur convention |
| Âge dérivé de la seule année | Approximation d'un an au plus | Conséquence assumée de la minimisation — ne pas revenir sur `birth_year` pour la corriger |
| Monitoring limité à REA et CARDIO | Les alertes ne couvrent pas tout l'hôpital | Étendre l'équipement, ou afficher la couverture à côté du taux |
| Vingt-huit jours de dépôt | Volumétrie de démonstration | Le banc d'essai (`benchmarks/`) valide 20 M de relevés par le chemin réel du pipeline |
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
