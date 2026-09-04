# Entrepôt de Données de Santé du CHU — rapport

**M2 Big Data · épreuve E05** — de dépôts quotidiens de fichiers hétérogènes à deux
tableaux de bord cloisonnés, avec pseudonymisation dès l'entrée de la zone de travail ; la
même chaîne déployée sur Azure ; et ce que ses indicateurs permettent de dire du CHU.

> Tous les chiffres de ce rapport sont ceux de la dernière exécution, identiques sur le poste
> et sur Azure, et chacun est reproductible en une commande (§5.4). Les six indicateurs du
> sujet et les cinq de l'évolution sont **vérifiés valeur par valeur** contre les feuilles de
> réponses du jeu de données corrigé (§5.2). La mise en service et l'exploitation sont dans le
> [README](../README.md).

Trois parties, à lire dans l'ordre ou séparément :

| Partie | Ce qu'elle répond |
|---|---|
| [1 — L'entrepôt sur le poste](#partie-1--lentrepôt-sur-le-poste) | Comment les chiffres sont produits : besoin, données, architecture, qualité, indicateurs, restitution, RGPD, évolution |
| [2 — Le déploiement Azure](#partie-2--le-déploiement-azure) | Où et comment la même chaîne tourne dans le cloud : architecture, fonctionnement, sécurité, coût |
| [3 — Exploitation des résultats](#partie-3--exploitation-des-résultats) | Ce que les indicateurs disent du CHU, et ce qu'on en recommande |

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
| [9](#9-évolution-du-29-août--actes-médicaux-et-description-des-services) | Que change le nouveau dépôt du CHU, et que reste-t-il inchangé ? |
| [10](#10-pourquoi-un-cloud-et-lequel) | Pourquoi un cloud, et lequel ? |
| [11](#11-larchitecture-en-un-diagramme) | À quoi ressemble l'architecture ? |
| [12](#12-pourquoi-ces-briques-et-pas-dautres) | Pourquoi ces briques, et pas d'autres ? |
| [13](#13-comment-ça-fonctionne) | Comment ça fonctionne, une nuit ordinaire ? |
| [14](#14-qui-peut-lire-quoi--sécurité-et-rgpd) | Qui peut lire quoi ? |
| [15](#15-combien-ça-coûte) | Combien ça coûte ? |
| [16](#16-limites-et-ce-quon-ferait-pour-un-vrai-chu) | Ce qui manque, et ce qu'on ferait pour un vrai CHU |
| [17](#17-comment-lire-ces-chiffres) | Comment lire ces chiffres ? |
| [18](#18-activité-et-capacité--où-sont-les-patients-et-combien-de-lits-il-faudrait) | Où sont les patients, et combien de lits il faudrait ? |
| [19](#19-qualité-et-sécurité-des-soins--mortalité-réadmissions-alertes) | Que disent la mortalité, les réadmissions et les alertes ? |
| [20](#20-population-et-pathologies--qui-sont-les-patients-et-de-quoi-souffrent-ils) | Qui sont les patients, et de quoi souffrent-ils ? |
| [21](#21-actes-et-facturation--ce-que-produit-le-plateau-technique-et-ce-que-ça-rapporte) | Que produit le plateau technique, et que rapporte-t-il ? |
| [22](#22-synthèse-et-préconisations) | Que retenir, et que recommander ? |

---

# Partie 1 — L'entrepôt sur le poste

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

Vingt-neuf jours de dépôt (1er → 29 août), six domaines, trois formats — en lecture
seule. Tout n'arrive pas tous les jours : les nomenclatures seulement quand elles changent ;
les patients trois fois, en fin de période, et à chaque fois en intégralité ; les actes
médicaux en un seul dépôt, le 29 août, avec tout leur historique (§9).

| Fichier | Format | Contenu | Jours | Volume brut |
|---|---|---|---:|---:|
| `patients/<jour>/patients.csv` | CSV | ⚠ **identité en clair** : IPP, NIR, nom, prénom, date de naissance, sexe, département | 3 | 18 000 (3 × 6 000) |
| `sejours/<jour>/sejours.csv` | CSV | Séjour : `stay_id`, patient, service, admission, sortie, modes | 28 | 6 797 |
| `diagnostics/<jour>/diagnostics.json` | JSON imbriqué | 1..n codes CIM-10 par séjour | 28 | 12 720 |
| `monitoring/<jour>/monitoring.parquet` | Parquet | Constantes au chevet : FC, SpO2, température | 28 | 41 778 |
| `actes/<jour>/actes.parquet` | Parquet | Acte médical : séjour, code CCAM, horodatage — **dépôt du 29 août** | 1 | 8 112 |
| `referentiels/<jour>/*.csv` | CSV | Nomenclatures : services et CIM-10 le 1er août ; **description des services et CCAM le 29** | 2 | 8 + 13 · 7 + 8 |

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
| 68 séjours dont la sortie **précède** l'admission | Incohérence temporelle → le séjour quitte `fact_sejour`, mais **ni ses 127 diagnostics ni ses 520 relevés** : ce sont les horodatages qui sont faux, pas le reste (§4) |
| 136 séjours admis **après un décès antérieur** du même patient | Anomalie de source → conservée et **marquée**, pour ne pas masquer un problème amont |
| Aucun séjour ne chevauche le précédent du même patient ; 1,13 séjour par patient, 3 au plus | Le calcul de réadmission est néanmoins écrit pour résister aux chevauchements (§5.3) : la bonne définition ne dépend pas de la propreté du jeu |
| 13 codes CIM-10, dont trois maladies rares portées par 8, 4 et 3 patients | Le seuil de 5 patients **masque l'effectif de deux pathologies entières** dans la base de recherche (§7.2) |
| Activité **inégale** entre services — 1 601 séjours en cardiologie, 211 en oncologie — et 49 % des admissions en mode urgence | Les indicateurs par service discriminent réellement : la DMS va de 2 à 9 jours (§5.1) |
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
| **dbt** pour silver et gold | SQL ordonné à la main | dbt déduit l'ordre d'exécution du graphe des `ref()` — plus aucune convention de nommage à respecter — et exécute **135 tests pendant** le run, pas après |
| **Python n'orchestre que** | pandas | Sortir les données du moteur pour les transformer ne passe pas à l'échelle. Seuls les deux CSV à pseudonymiser traversent Python, en flux ligne à ligne, à mémoire constante |
| **Deux bases gold** | Une base + des vues | Le cloisonnement devient un `GRANT`, donc une propriété du moteur, et non une règle applicative |
| **Partition bronze par jour** | Table unique | Rejouer un jour = `DROP PARTITION` + rechargement. L'idempotence est structurelle, pas défendue par du code |

ClickHouse et dbt ne sont pas concurrents : **ClickHouse stocke et calcule ; dbt envoie le
SQL dans le bon ordre et teste le résultat.** dbt ne stocke rien et ne calcule rien.

### 3.2 Le modèle de données

Silver est modélisé en **constellation Kimball : quatre étoiles, une par fait**, sur
dimensions conformées — trois depuis l'origine, la quatrième depuis le dépôt du 29 août.

![Modèle de données de l'entrepôt](img/eds-data-model.png)

| Fait | Grain | Dimensions | Lignes |
|---|---|---|---:|
| `fact_sejour` | un séjour | `dim_patient`, `dim_service` | 6 729 |
| `fact_diagnostic` | un code CIM-10 par séjour | `dim_patient`, `dim_cim10` | 12 720 |
| `fact_monitoring` | un relevé (`stay_id`, `ts`) | `dim_service` | 40 920 |
| `fact_acte` | un acte médical | `dim_service`, `dim_ccam` | 8 112 |

Trois propriétés à retenir :

- **Chaque fait porte les clés de ses propres dimensions**, propagées au build silver. Il
  n'y a donc **aucune jointure fait-à-fait** dans le modèle ni dans les requêtes gold — un
  produit croisé entre deux tables de faits gonflerait silencieusement tous les comptages.
- **`stay_id` est la dimension dégénérée** commune aux quatre faits : c'est elle qui permet
  le *drill-across* (partir d'une alerte de constante et remonter au séjour).
- **Les mesures non additives sont isolées.** `nb_patients` ne se somme jamais hors de son
  grain : la pyramide des âges lit une table au grain sexe × tranche, pas la table au grain
  CIM-10 × tranche × sexe — sinon un patient à cinq diagnostics serait compté cinq fois.
- **Le patient et le service des deux faits secondaires sont résolus depuis le référentiel
  de tous les séjours déposés**, pas depuis `fact_sejour`. Un séjour écarté pour ses
  horodatages garde donc ses diagnostics et ses relevés (§4).

Source PlantUML : [`data-model.puml`](data-model.puml). Un test
(`tests/test_data_model.py`) échoue si une table est ajoutée sans figurer au diagramme : le
schéma ne peut pas se périmer en silence.

### 3.3 Déploiement cloud

La même chaîne tourne sur Azure, décrite en Terraform, et **les invariants ne bougent pas
d'une unité** — c'était le critère d'acceptation. Le stockage objet remplace le dossier
local, un job planifié remplace cron, ClickHouse lit le lake par `azureBlobStorage()`.

Le cloud ajoute un **quatrième niveau de cloisonnement** que le poste ne peut pas offrir :
les droits sont attribués par conteneur de stockage, si bien que la machine qui héberge
l'entrepôt n'a aucun droit sur celui qui contient les noms et les NIR (§6, §14.2).

Tout le déploiement — diagramme, choix et alternatives, exploitation, sécurité, coût,
limites — est en [partie 2](#partie-2--le-déploiement-azure) ; le détail opérationnel dans
[`terraform/README.md`](../terraform/README.md).

### 3.4 Automatisation : planification, erreurs, traçabilité

Le sujet demande une collecte et une transformation **planifiées**, avec gestion des erreurs
et journalisation. Le pipeline est un seul geste, `eds run`, incrémental et rejouable, et il
est **déclenché de la même façon sur les deux cibles** : un conteneur planifié, construit
depuis le même `Dockerfile`, sur le même cron UTC, avec le même réessai.

| | Sur le poste | Sur Azure |
|---|---|---|
| Déclencheur | Le conteneur `scheduler` de la pile Docker Compose, démarré par `make demo` — rien à installer. Il exécute `eds schedule`, qui appelle `eds run` sur le cron `5 1 * * *`, 01 h 05 UTC | `job-eds-pipeline`, planifié par Azure : cron `5 1 * * *`, 01 h 05 UTC, après le dépôt nocturne |
| Ce qu'une nuit fait | Ne charge que les jours absents de `ops.ingest_log` ; sans nouveau fichier, ne reconstruit rien | Identique — même image, même code |
| Erreurs | Un réessai après 60 s ; le run est marqué `failed` avec son message ; le planificateur survit à une nuit ratée | Un réessai, journaux dans Log Analytics, `make cloud-status` montre les trois derniers passages |
| Reprise | `uv run eds run --date AAAA-MM-JJ` : `DROP PARTITION` puis rechargement, jamais de doublon. Ou `docker compose run --rm scheduler run`, dans l'image du cloud | `az containerapp job start … --args 'run,--date,…'` — le même job, à la main |
| Traçabilité | `ops.pipeline_runs` (un enregistrement par run, statut, message) · `ops.ingest_log` (fichier, empreinte, run) · rapport qualité chiffré par run | Idem, plus le `run_id` sur chaque ligne de journal |
| Preuve | `make schedule` : le prochain passage annoncé ; `make status` : derniers runs et jours ingérés. La CI vérifie sur un clone nu que le conteneur tourne et que son image exécute le pipeline | Trois exécutions planifiées consécutives, `Succeeded`, les 2, 3 et 4 septembre à 01:05:00 |

#### Ce que lance le conteneur, exactement

Le service `scheduler` **n'exécute pas `eds run`** : sa commande est `eds schedule`
(`command: ["schedule"]` dans `docker-compose.yml`), et c'est elle qui appelle `eds run` à
l'heure dite. Le détour mérite d'être explicité, parce que la planification locale est
**écrite dans le projet, sans bibliothèque** — ni `croniter`, ni `APScheduler`, ni cron du
système, ni service de l'hôte :

| Où regarder | Ce qui s'y trouve |
|---|---|
| `docker-compose.yml`, service `scheduler` | Image (la même que les jobs Azure), commande, montages, identité de l'utilisateur |
| `src/eds/cli.py`, commande `schedule` | Point d'entrée, options `--cron` (ou `EDS_SCHEDULE`) et `--once`, arrêt sur `SIGTERM` |
| `src/eds/schedule.py` | Lecture du cron, calcul du prochain passage, boucle, réessai |
| `tests/test_schedule.py` | 30 tests : 29 sans Docker, 1 sur la pile démarrée |
| `terraform/containerapp.tf`, `job-eds-pipeline` | Le jumeau Azure, sur la même expression cron |

`schedule.py` tient en un peu plus de deux cents lignes, commentaires compris, et fait trois
choses. Il **lit** l'expression à cinq champs — `*`, listes, plages, pas (`*/n`, `a-b/n`,
`n/p`), dimanche noté 0 ou 7, et la règle Vixie du OU entre jour du mois et jour de la semaine
quand les deux sont restreints — puis la fige en ensembles de valeurs. Il **calcule** le prochain passage en avançant jour par jour
depuis l'instant courant, borné à 366 jours : immédiat pour un cron quotidien, fini pour un
cron annuel. Il **boucle** : dormir par tranches d'une minute au plus, pour que `docker stop`
n'attende jamais ; exécuter la fonction qu'appelle aussi `eds run` — un seul chemin de code,
c'est ce qui rend la parité vraie plutôt que déclarée ; réessayer une fois après 60 s en cas
d'échec ; recommencer. Une exception qui échapperait au run est journalisée et comptée comme
un échec, jamais fatale : le service ne meurt pas sur une nuit ratée, exactement comme un job
Azure avec `replica_retry_limit = 1`.

Rien n'est mémorisé d'un passage à l'autre : l'heure suivante est recalculée depuis l'horloge
à chaque tour. Le planificateur survit donc à une mise en veille du poste, et un passage
manqué — machine éteinte — est rattrapé au suivant sans logique de rattrapage à écrire, parce
que le pipeline est incrémental (`ops.ingest_log`).

**Pourquoi aucune dépendance**, et les deux raisons sont vérifiables :

- **le cron est interprété en UTC**, comme sur Azure. Un seul fuseau : aucun décalage
  silencieux au changement d'heure, et « 01 h 05 UTC » se lit pareil sur le poste et dans le
  portail. Un test compare le défaut de `schedule.py` à la valeur de `pipeline_cron` dans
  `terraform/variables.tf` — les deux cibles ne peuvent pas diverger sans casser le build ;
- **l'horloge et la temporisation sont injectables**, donc la boucle se teste sans jamais
  attendre. Les 30 tests couvrent la lecture des cinq champs, les expressions invalides, le
  passage de fin de mois, la règle Vixie, le réessai unique et la survie à une exception, en
  quelques millisecondes. Porter un ordonnanceur généraliste pour une seule ligne de cron
  aurait ajouté une dépendance sans rendre ces garanties plus fortes.

**Ce qu'il ne fait pas, et qu'il faut savoir.** Le parser ignore les raccourcis (`@daily`),
les noms de mois et de jours (`JAN`, `MON`) et les extensions (`L`, `#`). Une telle expression
est **refusée au démarrage du conteneur, avec un message qui la cite** — `jour de la semaine :
« MON » n'est pas un nombre`, ou `« @daily » : cinq champs attendus …, 1 trouvé(s)` — jamais
interprétée de travers ni ignorée en silence. Et il n'y a **pas de délai maximal d'exécution**
en local, là où le job Azure est interrompu à 1 800 s : un `eds run` qui se figerait
bloquerait les passages suivants sans rien signaler. Rien n'interdit non plus de lancer un
`make pipeline` à la main pendant le passage nocturne. Ces deux limites sont inscrites au
tableau du §8.

Le contrôle du cloisonnement est à la demande sur les deux cibles :
`uv run eds check-cloisonnement` en local, `make cloud-check` sur Azure. Lancement,
supervision et reprise sur incident
sont dans le [README](../README.md#exploitation) ; le déroulé d'une nuit sur Azure, flèche par
flèche, en [§13](#13-comment-ça-fonctionne).

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
| **Q4** Constantes hors plage physiologique | Rejet | 41 778 | 40 920 | 858 | — |
| **Q3** Séjour sans date de sortie | Signalement | 6 729 | 6 729 | 0 | 683 |
| **Q5** Sortie datée, mode non renseigné | Signalement | 6 729 | 6 729 | 0 | 0 |
| **Q7** Admission après un décès antérieur | Signalement | 6 729 | 6 729 | 0 | 136 |
| **Q8** Relevé postérieur à la sortie | Contrôle | 40 920 | 40 920 | 0 | **0** |
| **C1** Relevé rattaché à un séjour inconnu | Contrôle | 41 778 | 40 920 | 0 | **0** |
| **C2** Diagnostic rattaché à un séjour inconnu | Contrôle | 12 720 | 12 720 | 0 | **0** |
| **Q6** Formats et intégrité référentielle (5 règles) | Contrôle | — | — | 0 | **0** |
| **Q9** Service absent du référentiel de description | Signalement | 8 | 8 | 0 | 1 |
| **C3** Acte rattaché à un séjour inconnu | Contrôle | 8 112 | 8 112 | 0 | **0** |
| **Q6** Code CCAM absent du référentiel | Contrôle | 8 112 | 8 112 | 0 | **0** |
| **Q10** Acte avant l'admission ou après la sortie | Contrôle | 8 112 | 8 112 | 0 | **0** |

Avec les contrôles RGPD de la couche gold (§7), `ops.quality_report` compte **vingt-deux
lignes** pour vingt règles — le k-anonymat est chiffré table diffusée par table diffusée.
Elles sont recalculées à chaque run et affichées au bas du tableau de bord de pilotage. Les
quatre dernières sont celles de l'évolution du 29 août (§9).

**La décision qui structure toute la couche : un rejet ne vaut que pour la table où vit
l'anomalie.**

Q2 constate que `discharge_ts` précède `admission_ts`. Ce qui est faux, ce sont **les
horodatages** — pas l'existence du séjour, pas le patient, pas le service, pas les
diagnostics qui y ont été codés, pas les constantes relevées au chevet, qui portent leur
propre horodatage. Écarter en cascade tout ce qui s'y rattache reviendrait à faire
disparaître une infection urinaire parce qu'une date de sortie a été mal saisie.

Le coût de cette cascade a été mesuré : **quinze patients manquants** sur la prévalence des
infections urinaires (2 219 au lieu de 2 234) et **520 relevés valides perdus**. Le séjour
quitte donc `fact_sejour`, où sa durée serait inexploitable ; ses 127 diagnostics et ses 520
relevés restent dans l'entrepôt et résolvent leur patient et leur service depuis le
référentiel des 6 797 séjours déposés.

Il ne reste par conséquent **aucune règle de cascade**. C1 et C2 sont devenus des contrôles
attendus à zéro : un relevé ou un diagnostic référençant un séjour *absent du dépôt* n'aurait
ni service ni patient résoluble, et serait écarté. Aucun n'existe.

Deux autres décisions à défendre :

- **Une sortie non renseignée n'est pas une anomalie** — c'est un patient encore
  hospitalisé. Les 683 séjours concernés sont conservés, marqués, et exclus du seul calcul
  où ils fausseraient le résultat : la DMS.
- **Q8 vaut zéro, et c'est un résultat.** Le contrôle ne se prononce que sur les séjours
  temporellement cohérents : sur les autres, c'est la date de sortie elle-même qui est
  fausse, et tout relevé y paraîtrait « postérieur ». Sans ce périmètre, Q8 ne mesurerait
  que Q2. Même logique pour Q5, à zéro sur ce jeu : c'est la règle qui fait l'entrepôt, pas
  le jeu de données.

**Traçabilité.** Chaque ligne de bronze et de silver porte son fichier d'origine, son jour
de dépôt et son horodatage de traitement. Chaque exécution est enregistrée dans
`ops.pipeline_runs` ; `ops.ingest_log` relie chaque fichier au run qui l'a chargé.

---

## 5. Les indicateurs

Tous sont calculés dans l'entrepôt et exposés en tables agrégées. Les requêtes des tableaux
de bord se réduisent à des `SELECT` : aucun calcul métier n'est enfoui dans Metabase, et
**aucune carte ne ré-agrège une table gold pour en changer le grain**. Si une vue manque,
c'est un modèle qui manque.

### 5.1 Les six indicateurs, et le grain auquel ils se lisent

| # | Indicateur | Grain publié | Table gold | Résultat |
|---|---|---|---|---|
| 1 | **DMS par service** | service | `kpi_dms_service` | 2,15 j aux urgences → 9,05 j en réanimation |
| 2 | **Réadmission à 30 jours** | établissement | `kpi_readmissions_30j` | **780 / 6 729 = 11,59 %** |
| 3 | **Activité des urgences** | jour d'admission | `kpi_urgences_jour` | 9 → 82 passages/j, 1 423 au total |
| 4 | **Relevés en alerte** | jour | `kpi_alertes_jour` | **3 314 / 40 920 = 8,1 %** |
| 5 | **Prévalence par pathologie** | code CIM-10 | `prevalence_pathologie` | 2 234 (infections urinaires) → 8 (amyotrophie spinale) |
| 6 | **Description de cohorte** | pathologie × tranche d'âge × sexe | `cohorte_demographie` | 102 cellules, 89 chiffrées |

**Le grain n'est pas un détail de mise en forme, c'est la question posée.** « Quels services
immobilisent le plus longtemps un lit ? » porte sur les services : la DMS se publie donc par
service, et non par service et par jour de sortie — cette vue-là a existé, elle se lisait
comme du bruit. Même chose pour la réadmission, chiffre unique de qualité des soins. À
l'inverse, l'activité des urgences et la surveillance des constantes **sont** des séries
temporelles : le grain du jour est ce que demande la question.

Chaque indicateur a donc exactement une table, à exactement un grain. Les vues
complémentaires — `kpi_readmissions_service`, `kpi_alertes_service`, `kpi_activite_service`,
`kpi_flux` — portent leur grain dans leur nom, et les cinq tables de l'évolution suivent la
même règle (§9.4).

Quelques définitions qui méritent d'être explicitées :

| Indicateur | Choix de définition | Pourquoi |
|---|---|---|
| **DMS** | Séjours **terminés** uniquement | Une durée partielle tirerait la moyenne vers le bas et simulerait une amélioration |
| **Réadmission** | Existe-t-il, pour le même patient, **une** admission dans les 30 jours suivant la sortie ? Dénominateur : **tous** les séjours valides | Un séjour en cours ne peut pas être suivi d'une réadmission ; il compte pour 0 au numérateur mais reste au dénominateur — le taux décrit la population entière, pas un sous-ensemble choisi |
| **Passage aux urgences** | Séjour dont le **service** est URGENCES | L'autre acception — admission en **mode** urgence, tous services — vaut 2,3× plus (18 → 158/j) et répond à une autre question ; elle est publiée dans `kpi_flux` |
| **Alerte de constante** | FC < 50 ou > 100 bpm, SpO2 < 92 %, T° > 38,5 °C | Seuils de **vigilance**, volontairement plus serrés que les bornes de plausibilité (FC 20-250, SpO2 50-100, T° 30-45) qui écartent les capteurs en panne : une constante peut être parfaitement mesurée et cliniquement anormale |
| **Taille de cohorte** | Patients **distincts**, tous rangs de diagnostic | Un patient hospitalisé trois fois compte une fois |
| **Description de cohorte** | Diagnostic **principal** seulement | Décrire une cohorte, c'est décrire les patients pris en charge **pour** cette pathologie. Compter aussi les comorbidités gonfle le diabète de 843 à 2 177 patients — deux populations distinctes, deux questions distinctes |

### 5.2 Les chiffres sont vérifiés, pas seulement reproductibles

Un indicateur reproductible peut être faux : il suffit qu'il le soit à chaque exécution. Le
jeu de données corrigé est accompagné de deux **feuilles de réponses** de l'intervenant :
l'une donne les valeurs attendues pour les six KPI et pour les trois points de contrôle
bronze → silver, l'autre celles des cinq KPI de l'évolution (§9.4). Elles ne sont pas
distribuées avec ce dépôt ; leurs valeurs sont reprises, littéralement, dans
`tests/test_e2e.py`.

La suite d'intégration les ancre **valeur par valeur** :

| Vérification | Valeurs comparées |
|---|---:|
| Points de contrôle silver (`dim_patient`, `fact_sejour`, `fact_monitoring`) | 3 |
| KPI 1 — DMS par service (effectif, jours, heures) | 24 |
| KPI 2 — Réadmission à 30 jours | 3 |
| KPI 3 — Urgences par jour (28 jours × 3 mesures) | 84 |
| KPI 4 — Alertes par jour (30 jours × 3 mesures) | 90 |
| KPI 5 — Prévalence par pathologie, masquages compris | 13 |
| KPI 6 — Cohorte pathologie × tranche × sexe | 102 |
| Évolution, KPI 1 à 5 — les cinq tables, ligne à ligne et dans l'ordre | 154 |

Soit 473 valeurs, pour un seul écart : un arrondi de densité, 86,6 contre 86,5, expliqué en
§9.4.

Ces vérifications ont trouvé trois défauts réels, tous corrigés : la **cascade de rejets**,
qui minorait la prévalence de quinze patients et perdait 520 relevés (§4) ; des **seuils
d'alerte** trop larges (FC 40-130, SpO2 < 90), qui sous-comptaient les alertes de 40 % ; et
un **grain de publication** qui répondait à une autre question que celle posée (§5.1).

### 5.3 Le taux de réadmission : l'indicateur qui demandait le plus de soin

**Définition robuste.** On teste **toutes** les admissions du patient, pas seulement la
suivante. Sur ce jeu, aucun séjour ne se chevauche et les deux écritures donnent le même
compte ; sur des données réelles, l'admission « suivante » est souvent un séjour concurrent
commencé avant la sortie, qui masque la réadmission réelle. La bonne définition ne doit pas
dépendre de la propreté du jeu.

**La limite : la fenêtre d'observation.** Une réadmission ne peut être constatée que si
l'entrepôt couvre la période où elle surviendrait. Les admissions s'arrêtent au 28 août ;
les sorties s'étalent du 2 août au 15 septembre. Une sortie du 2 août dispose de 27 jours
d'observation, une sortie du 27 août d'un seul, une sortie de septembre d'**aucun**.

| Fenêtre observable | Séjours | Réadmissions | Taux |
|---|---:|---:|---:|
| 22 à 27 jours | 568 | 154 | 27,1 % |
| 15 à 21 jours | 1 557 | 332 | 21,3 % |
| 8 à 14 jours | 1 676 | 231 | 13,8 % |
| 1 à 7 jours | 1 568 | 63 | 4,0 % |
| aucune — sortie après le 28 août | 677 | 0 | 0 % |
| séjour encore en cours | 683 | 0 | 0 % |

Le taux **croît avec la fenêtre** : c'est la signature d'une censure à droite, pas d'une
tendance. Le **11,59 % publié est donc une borne basse** — les séjours les mieux observés
tournent autour de 27 % — et l'avertissement est placé **au-dessus** des graphiques qu'il
qualifie, un avertissement sous le chiffre qu'il corrige n'étant pas lu. Soixante jours
d'historique permettraient de publier la valeur réelle (§8).

![Réadmissions et couverture de l'indicateur](img/pilotage-readmissions.jpg)

Par service, le taux va de 6,6 % en réanimation à 14,7 % en chirurgie et en pédiatrie — un
classement à lire avec la même précaution, les services n'ayant pas le même profil de sortie
dans la fenêtre observable. La somme des services reproduit exactement le taux global : un
test le vérifie à chaque build.

### 5.4 Retrouver n'importe quel chiffre

| Chiffre affiché | Valeur | Table gold | Expression déterminante |
|---|---:|---|---|
| Séjours pris en charge | 6 729 | `kpi_synthese` | `count()` sur `fact_sejour` |
| Patients suivis | 5 949 | `kpi_synthese` | `uniqExact(patient_pseudo)` sur `fact_sejour` |
| DMS globale | 5,15 j | `kpi_synthese` | `avg(duree_jours)` **où** `discharge_ts IS NOT NULL` |
| DMS par service | 2,15 → 9,05 j | `kpi_dms_service` | `avg(duree_jours)` **groupé par service** — la carte lit la table telle quelle |
| Réadmissions | 780 / 6 729 | `kpi_readmissions_30j` | `arrayExists(adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY, admissions_du_patient)` |
| Relevés en alerte | 3 314 / 40 920 | `kpi_alertes_jour` | `countIf(is_alert)` |
| Séjours en cours | 683 | `kpi_synthese` | `countIf(is_ongoing)` |
| Population suivie | 6 000 | `prevalence_pathologie` | `count()` sur `dim_patient` — dénominateur de la prévalence |
| Pyramide des âges | total 6 000 | `cohorte_demographie_globale` | grain sexe × tranche : un patient compté **une** fois |
| Effectifs publiés | 11 / 13 pathologies | `prevalence_pathologie` | `nb_patients >= 5` — la ligne reste, l'effectif part |
| Cellules masquées (k<5) | 13 / 102 | `k_anonymat_controle` | cellules calculées − cellules diffusées |
| Actes réalisés | 8 112 | `kpi_synthese` | `count()` sur `fact_acte`, repris de `kpi_actes_service` |
| Montant facturé | 2 199 450 € | `kpi_synthese` | `sum(montant_euros)` — tarif CCAM porté par le fait |

**Deux dénominateurs coexistent, et ce n'est pas une incohérence.** Le pilotage compte
5 949 patients — ceux qui ont au moins un séjour dont les horodatages sont exploitables. La
recherche en compte 6 000 — la population que le CHU a déposée. L'écart est exactement les
51 patients dont *tous* les séjours ont été écartés par Q2 : leurs diagnostics restent
comptés (§4), et les exclure de la population de référence fausserait la prévalence. Chaque
table porte son dénominateur en colonne pour que la lecture ne dépende pas de cette note.

Trois commandes rejouent l'ensemble : `make quality` (les 22 lignes du rapport qualité),
`make test-e2e` (les 88 invariants, dont chacun de ces chiffres), `uv run eds
check-cloisonnement`. **La suite d'intégration ancre ces valeurs** : modifier une règle sans
le vouloir fait échouer un test nommé, cela ne fait pas dériver un chiffre en silence.

---

## 6. Restitution et cloisonnement

**🏥 Pilotage** se lit par bandes : chiffres clés → durées et urgences → surveillance →
réadmissions et flux → charge des services → **fiabilité**. Grâce à cette dernière bande, un
utilisateur qui doute d'un chiffre voit, sans quitter l'interface et sans accès à la base
d'exploitation, combien de lignes ont été écartées et par quelle règle.

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

Et il n'a qu'une seule base à interroger : sa connexion Metabase ne pointe que vers
`eds_gold_pilotage`, avec le compte SQL qui n'a de droit que sur elle.

![Les bases visibles depuis le compte pilotage](img/cloisonnement-bases-pilotage.jpg)

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

### 7.2 Petits effectifs : masquer plutôt que supprimer

Le seuil est de **cinq patients**, et les âges sont publiés en tranches de dix ans. Trois
questions se posent alors : à quel grain l'appliquer, que faire de la cellule protégée, et
que reste-t-il de déductible une fois la protection en place.

**À quel grain.** Une première version ajoutait le **département**. Elle coûtait cher — 178
cellules sur 1 083 sous le seuil, plus 66 marges sur 149 retirées pour empêcher la
reconstruction par différence, soit 44 % de la table — et n'apprenait rien : huit
départements sur des cohortes de quelques centaines de patients ne protègent ni ne
renseignent personne. Le grain départemental a donc été **retiré** au profit de celui que le
sujet demande, « par âge et sexe ». Résultat mesuré : **89 cellules chiffrées au lieu de
83**, sans la chaîne de tables intermédiaires qu'il fallait protéger les unes des autres.

**Que faire de la cellule protégée.** Elle garde sa ligne, et perd son effectif :

| Table diffusée | Cellules | Effectifs publiés | Effectifs masqués |
|---|---:|---:|---:|
| `prevalence_pathologie` | 13 | 11 | **2** |
| `cohorte_demographie` | 102 | 89 | **13** |
| `cohorte_demographie_globale` | 20 | 20 | 0 |

Faire disparaître la ligne serait **moins** protecteur, pas plus. Le chercheur ne saurait pas
qu'une valeur a été retirée, et le dispositif ne serait vérifiable nulle part. C'est la
pratique du contrôle statistique de la divulgation — les instituts publient la cellule
marquée « secret », ils ne la retirent pas. Ce qui est protégé, c'est **l'effectif**, et il
ne sort pas de silver. La mucoviscidose (4 patients) et la trisomie 21 (3) apparaissent donc
au tableau de bord, sans leur taille.

**Ce qui reste déductible.** Publier une vue agrégée **et** sa décomposition, en appliquant
le seuil séparément aux deux, laisse fuiter la cellule protégée :

```
   total de la marge  −  somme des cellules diffusées  =  cellule cachée
```

L'attaque ne demande aucun privilège : une jointure entre deux tables, avec le seul compte
chercheur, suffit. Elle avait été trouvée sur la version précédente, où elle reconstituait
pathologie, sexe, tranche d'âge, département **et** effectif exact.

Deux propriétés la neutralisent dans la version actuelle :

1. **Aucune pathologie n'est publiée à moitié.** Les trois pathologies sous le seuil le sont
   sur *toutes* leurs cellules ; les dix autres sur *aucune*. Il n'existe donc, pour aucune
   pathologie, un reste à soustraire. Un test (`assert_pas_de_suppression_partielle`) échoue
   si cette condition cesse de tenir : c'est un signal, pas une garantie structurelle.
2. **Les deux tables ne décrivent pas la même population.** `prevalence_pathologie` compte
   tous les rangs de diagnostic, `cohorte_demographie` le seul diagnostic principal : la
   soustraction n'aurait pas de sens.

**Un corollaire, découvert à la dure.** Le graphique de part de femmes sommait les tranches
d'âge d'une table déjà filtrée par le seuil. L'opération est licite au sens de l'additivité
— un patient n'appartient qu'à une tranche. Mais les cellules qui manquaient ne manquaient
pas au hasard, c'étaient les plus petites, et le ratio dérivait de **neuf points** : 71,5 %
de femmes pour les infections urinaires contre 62,5 % en réalité. Un chiffre faux, sans le
moindre signe extérieur d'erreur.

La règle qui en découle est plus forte que « ne pas sommer une mesure non additive » : **un
agrégat ne se calcule jamais à partir d'une table filtrée.** La somme est redevenue légitime
ici précisément parce qu'aucune pathologie n'est publiée à moitié — et un second test
(`assert_part_de_femmes_non_biaisee`) compare chaque pourcentage publié à la vérité de
silver, sans tolérance.

![Protection des petits effectifs et son effet mesuré](img/recherche-k-anonymat.jpg)

### 7.3 Contrôles automatiques

Les règles RGPD tournent à chaque run, chiffrées dans `ops.quality_report` au même titre que
les contrôles de qualité :

| Règle | Ce qu'elle mesure | Attendu |
|---|---|---|
| `RGPD_k_anonymat` · `prevalence_pathologie` | Cohortes dont l'effectif est masqué | 2 / 13 |
| `RGPD_k_anonymat` · `cohorte_demographie` | Cellules dont l'effectif est masqué | 13 / 102 |
| `RGPD_k_anonymat` · `cohorte_demographie_globale` | Idem, pyramide des âges | 0 / 20 |
| `RGPD_minimisation` | Colonnes identifiantes **ou pseudonyme** dans la base recherche | **0** |

S'y ajoutent, côté dbt, quatre tests qui échouent le build : aucun effectif publié sous le
seuil, cohérence entre le drapeau `diffusable` et la présence de l'effectif, aucune
pathologie publiée à moitié, et aucune part de femmes biaisée.

### 7.4 Registre des hypothèses

Ce que nous avons tranché sans que le sujet le fasse, et qu'il faudrait valider :

1. Les seuils d'alerte des constantes (§5.1), repris de la feuille de réponses mais non
   validés cliniquement ;
2. le maintien des séjours décédés et en cours au dénominateur des réadmissions — le taux
   décrit alors la population entière, pas un sous-ensemble choisi ;
3. l'exclusion des séjours en cours du calcul de la DMS ;
4. la restriction de la description de cohorte au diagnostic **principal** (§5.1) ;
5. le retrait du grain départemental des vues de recherche (§7.2) ;
6. le seuil k = 5, retenu d'après l'énoncé — certaines autorités en recommandent un plus élevé.

---

## 8. Limites et recommandations

**⚠ La limite qui prime toutes les autres.** Le jeu de données est synthétique. Ses
prévalences ont des ordres de grandeur plausibles — 37 % d'infections urinaires, 4 % de
cancers bronchiques, 0,1 % d'amyotrophie spinale — mais elles sont générées et ne décrivent
aucune population. Les cohortes valident la chaîne de traitement, **pas** une conclusion
épidémiologique. Cet avertissement figure en tête du tableau de bord de recherche.

| Limite | Portée | Recommandation |
|---|---|---|
| Aucun séjour n'a 30 jours d'observation (27 au plus) | Le taux de réadmission publié, 11,59 %, est une borne basse : les séjours les mieux observés sont à 27 % (§5.3) | Attendre **60 jours d'historique** avant de publier cet indicateur en production |
| La charge des services s'effondre après le 28 août | Ce n'est pas une baisse d'activité, c'est la fin des admissions déposées | La courbe le signale en description ; en production le problème disparaît |
| Le grain départemental a été retiré des vues de recherche | Une analyse territoriale n'est plus possible depuis le tableau de bord (§7.2) | La rouvrir par **région** plutôt que par département, ou la réserver à un accès sur convention |
| Absence de suppression partielle : une propriété du jeu, pas du code | Si un futur dépôt publiait une pathologie à moitié, la somme par sexe redeviendrait biaisée (§7.2) | Le test `assert_pas_de_suppression_partielle` casse le build — traiter l'alerte, ne pas la contourner |
| Âge dérivé de la seule année | Approximation d'un an au plus | Conséquence assumée de la minimisation — ne pas revenir sur `birth_year` pour la corriger |
| Monitoring limité à REA et CARDIO | Les alertes ne couvrent pas tout l'hôpital | Étendre l'équipement, ou afficher la couverture à côté du taux |
| Vingt-huit jours de dépôt | Volumétrie de démonstration | Le banc d'essai (`benchmarks/`) valide 20 M de relevés par le chemin réel du pipeline |
| Seuils d'alerte non validés cliniquement | Le nombre d'alertes en dépend directement | Faire arbitrer par les équipes soignantes avant tout usage |
| Metabase tourne à ~78 % de sa limite mémoire sur la VM cloud | Marge étroite : un métaspace borné trop bas a déjà arrêté la JVM en cours de provisionnement | Budget JVM redécoupé (tas 524 Mo, métaspace 498 Mo, marge native 289 Mo) et vérifié sous charge ; une VM à 8 Gio le rendrait confortable |
| La neurologie n'est pas décrite par le CHU | Sa densité d'actes par lit reste vide, sa catégorie est « (non decrit) » (§9) | Obtenir la ligne manquante du référentiel — le pipeline la prendra au prochain dépôt sans autre changement |
| Rien n'empêche deux exécutions simultanées du pipeline | Un `make pipeline` lancé pendant le passage nocturne lit le même `ops.ingest_log` : selon l'entrelacement, un fichier peut être chargé deux fois. La fenêtre est étroite (un passage par nuit) mais réelle | Poser un verrou en début de run dans `ops` — la table existe déjà et porte le `run_id` |
| Le planificateur local n'a pas de délai maximal d'exécution | Un `eds run` figé bloquerait les passages suivants sans alerte ; le job Azure, lui, est interrompu à 1 800 s (§3.4) | Borner l'exécution dans `schedule.py` et aligner la valeur sur `replica_timeout_in_seconds` |
| Le tarif d'un acte est celui du référentiel courant | Un changement de tarif recalculerait tout l'historique facturé (§9.5) | Historiser `dim_ccam` (dimension à évolution lente) le jour où la T2A change |

**Trois recommandations de gouvernance**, qui relèvent de l'organisation et non du code :

1. Conserver le sel de pseudonymisation dans un coffre, avec une procédure de rotation
   documentée — le changer casse toutes les jointures historiques : c'est une décision, pas
   une manipulation.
2. Faire valider le seuil k = 5 par le délégué à la protection des données.
3. Revoir les hypothèses de §7.4 à chaque évolution du besoin métier.

---

## 9. Évolution du 29 août : actes médicaux et description des services

Le CHU ajoute des données sans rien retirer : une description plus fine de ses services et un
flux d'actes médicaux, déposés le 29 août. La consigne tient en une phrase — faire évoluer
l'entrepôt **sans tout refaire, sans rien casser**.

### 9.1 Ce que le dépôt contient

| Fichier | Contenu | Lignes | Ce que le profilage a révélé |
|---|---|---:|---|
| `referentiels/2026-08-29/description_service.csv` | catégorie, capacité en lits, pôle | **7** | **NEURO n'y figure pas.** Le référentiel est incomplet, comme le sujet le laissait craindre |
| `referentiels/2026-08-29/ccam.csv` | code d'acte → libellé, tarif T2A | 8 | Tarifs de 25 à 800 € |
| `actes/2026-08-29/actes.parquet` | séjour, code CCAM, horodatage | **8 112** | Tout l'historique en un dépôt (actes du 1er au 29 août), 5 096 séjours ; aucun doublon, aucun code inconnu, aucun séjour inconnu ; **82 actes pendant les 68 séjours écartés par Q2** ; tous les autres dans les bornes de leur séjour |

Une observation de plus, qui a une conséquence de modélisation : la hiérarchie annoncée
service → catégorie → pôle n'est stricte qu'au premier niveau. La catégorie « medecine »
relève de **deux** pôles — Coeur-Poumon pour la cardiologie et la pneumologie, Cancerologie
pour l'oncologie. Le pôle est une propriété du service, pas de la catégorie ; aucune vue au
grain de la catégorie ne peut donc le porter.

### 9.2 Ingérer sans retraiter

Le pipeline incrémental a chargé **les trois fichiers, et rien d'autre** : 89 fichiers
ignorés, empreintes inchangées ; journal d'ingestion à 92 fichiers, 29 jours, 6 domaines.
Deux évolutions du collecteur l'ont permis :

- `actes` est un **flux quotidien**, comme le monitoring : un jour déposé sans son fichier
  alerte ;
- les **nomenclatures** cessent d'être une liste fixe. Le CHU ne dépose que celles qui
  changent — services et CIM-10 le 1er août, description et CCAM le 29. Exiger les quatre
  à chaque dépôt aurait fait échouer précisément le dépôt d'évolution. Un fichier est donc
  facultatif un jour donné ; un jour sans aucune nomenclature reconnue alerte ; un fichier
  inconnu est signalé, pas chargé en silence.

Côté bronze, trois tables dans un fichier DDL séparé
(`sql/10_bronze/02_actes_et_descriptions.sql`) : les six tables historiques n'ont pas changé
d'une ligne. Même partition par jour de dépôt, même lignage — un rejeu du 29 août est un
`DROP PARTITION` suivi d'un `INSERT`, comme pour n'importe quel autre jour.

### 9.3 Le modèle : un incrément

| Demandé | Fait | Décision structurante |
|---|---|---|
| Compléter `dim_service` | catégorie, pôle, capacité, `est_decrit` | **Jointure externe** vers la description — piège n° 1 |
| Ajouter `dim_ccam` | code, libellé, tarif | Dernière version déposée, comme les autres dimensions |
| Ajouter `fact_acte` | grain : un acte ; 8 112 lignes | Le **service est résolu au build** et rangé sur le fait — piège n° 2 ; le montant T2A est une mesure du fait ; pas de pseudonyme (minimisation) |
| Non-régression | les six KPI du corrigé | **Identiques** : 6 729 · 9,05 j · 11,59 % · 1 423 · 3 314 · 2 234 · 89 — vérifiés par un test nommé |

**Piège n° 1 — le service non décrit.** NEURO reste dans la dimension avec ses 1 208
séjours. Sa catégorie et son pôle prennent le libellé explicite « (non decrit) », qui se
regroupe et s'affiche comme n'importe quelle valeur ; sa capacité reste **NULL** — on ne
fabrique pas un nombre de lits, et sa densité d'actes par lit sera vide plutôt que fausse ;
le fait est porté par `est_decrit` et compté par la règle Q9. Retirer le service aurait
cassé tous les indicateurs historiques ; lui inventer une capacité aurait produit un chiffre
faux sans le moindre signe extérieur d'erreur. Le jour où le CHU dépose la ligne manquante,
elle est prise au run suivant sans autre changement.

**Piège n° 2 — le service d'un acte.** Il vient du séjour, et le sujet interdit de relier
deux tables de faits. La réponse est celle déjà donnée pour les constantes et les
diagnostics : le service est **propagé sur le fait au moment de la construction**, depuis le
référentiel de tous les séjours déposés. « Actes par service » devient un simple
`GROUP BY` sur `fact_acte`. Les 82 actes réalisés pendant les séjours aux horodatages
incohérents gardent ainsi leur service et restent comptés — un acte est un fait clinique,
une date de sortie fausse ne l'annule pas (§4).

« Actes par séjour » ne demande pas non plus deux faits : son dénominateur est le nombre
de séjours distincts ayant au moins un acte, lu dans `fact_acte` lui-même. L'agrégation au
grain du service est écrite **une** fois — le modèle éphémère `int_actes_service`, que dbt
inline — et publiée trois fois (KPI 2, 4 et 5). Le test `assert_actes_reconcilies` en est
le garde-fou : la somme des actes de chaque table doit valoir exactement le nombre de
lignes de `fact_acte`, ce qu'une jointure fait-à-fait ferait exploser.

Quatre règles qualité s'ajoutent au rapport, qui passe à 22 lignes pour 20 règles : Q9
signale le service non décrit (1) ; C3, Q6 et Q10 — séjour inconnu, code CCAM inconnu, acte
hors des bornes de son séjour — sont des contrôles attendus à zéro, et valent zéro.

### 9.4 Les cinq indicateurs

**Une table gold par indicateur, dans l'ordre de la consigne, aux colonnes de la question
posée.** Chaque table porte un `rang` — sa clé de tri physique — et se lit donc dans l'ordre
du classement sans `ORDER BY` ; le tableau de bord de pilotage les affiche telles quelles,
sans renommage ni recalcul. Les valeurs ci-dessous sont celles de l'entrepôt, local et Azure ;
la suite d'intégration les vérifie ligne à ligne, dans cet ordre.

| # | Indicateur | Grain | Table gold | Classement |
|---|---|---|---|---|
| 1 | Activité et DMS par catégorie de service | catégorie | `kpi_activite_categorie` | séjours clos décroissants |
| 2 | Nombre d'actes par service | service | `kpi_actes_service` | actes décroissants |
| 3 | Nombre d'actes par type d'acte | code CCAM | `kpi_actes_type` | actes décroissants |
| 4 | Densité d'actes par lit | service | `kpi_densite_lits` | densité décroissante, capacité inconnue en dernier |
| 5 | Montant facturé par service (T2A) | service | `kpi_facturation_service` | montant décroissant |

**KPI 1 — Activité et DMS par catégorie de service** (séjours clos, comme la DMS par service)

| categorie | nb_sejours | dms_jours |
|---|---:|---:|
| medecine | 2 397 | 5,71 |
| urgences | 1 277 | 2,15 |
| (non decrit) | 1 077 | 7,06 |
| pediatrie | 448 | 3,19 |
| chirurgie | 424 | 4,39 |
| reanimation | 423 | 9,05 |

La catégorie « medecine » regroupe cardiologie, pneumologie et oncologie ; « (non decrit) »
est la neurologie, absente du référentiel de description. Les six lignes totalisent les
6 046 séjours terminés (6 729 valides moins 683 en cours).

**KPI 2 — Nombre d'actes par service** (le service est celui du séjour, porté par le fait)

| service_code | service_label | nb_actes | nb_sejours_avec_acte | actes_par_sejour |
|---|---|---:|---:|---:|
| CARDIO | Cardiologie | 1 935 | 1 213 | 1,60 |
| URGENCES | Urgences | 1 731 | 1 090 | 1,59 |
| NEURO | Neurologie | 1 471 | 918 | 1,60 |
| PNEUMO | Pneumologie | 1 009 | 642 | 1,57 |
| PEDIA | Pediatrie | 598 | 379 | 1,58 |
| CHIR | Chirurgie | 564 | 344 | 1,64 |
| REA | Reanimation | 563 | 355 | 1,59 |
| ONCO | Oncologie | 241 | 155 | 1,55 |

**KPI 3 — Nombre d'actes par type d'acte**

| code_ccam | libelle_ccam | nb_actes |
|---|---|---:|
| ZBQK001 | Radiographie du thorax | 1 043 |
| YYYY010 | Consultation de suivi | 1 039 |
| DZEA001 | Coronarographie | 1 030 |
| EBLA003 | Pose de catheter central | 1 025 |
| HGQD001 | Coloscopie totale | 1 015 |
| GLLD001 | Ventilation mecanique assistee | 1 000 |
| NEJA001 | IRM cerebrale | 982 |
| HHFA001 | Appendicectomie | 978 |

**KPI 4 — Densité d'actes par lit** (nb_actes / capacite_lits)

| service_code | service_label | capacite_lits | nb_actes | actes_par_lit |
|---|---|---:|---:|---:|
| URGENCES | Urgences | 20 | 1 731 | 86,6 |
| CARDIO | Cardiologie | 30 | 1 935 | 64,5 |
| PNEUMO | Pneumologie | 28 | 1 009 | 36,0 |
| REA | Reanimation | 16 | 563 | 35,2 |
| PEDIA | Pediatrie | 22 | 598 | 27,2 |
| CHIR | Chirurgie | 40 | 564 | 14,1 |
| ONCO | Oncologie | 35 | 241 | 6,9 |
| NEURO | Neurologie | — | 1 471 | — |

La neurologie garde sa ligne et ses actes, sans densité : sa capacité n'est pas connue, et
l'on ne divise pas par un nombre de lits inventé. Une précision d'arrondi : 1 731 / 20 vaut
86,55 exactement ; ClickHouse arrondit la demi-unité vers le haut (86,6), un outil qui
arrondit le flottant binaire 86,549 999… affiche 86,5. Les sept autres densités ne
présentent aucun cas limite.

**KPI 5 — Montant facturé par service** (T2A : somme des tarifs des actes)

| service_code | service_label | nb_actes | montant_facture_euros |
|---|---|---:|---:|
| CARDIO | Cardiologie | 1 935 | 521 655 |
| URGENCES | Urgences | 1 731 | 478 585 |
| NEURO | Neurologie | 1 471 | 393 850 |
| PNEUMO | Pneumologie | 1 009 | 268 045 |
| PEDIA | Pediatrie | 598 | 171 165 |
| REA | Reanimation | 563 | 154 740 |
| CHIR | Chirurgie | 564 | 147 145 |
| ONCO | Oncologie | 241 | 64 265 |
| **Total** | | **8 112** | **2 199 450** |

Le total est repris tel quel dans `kpi_synthese`, d'où les deux tuiles qui ouvrent la bande
du tableau de bord — 8 112 actes, 2 199 450 € — avant les cinq tables, dans cet ordre.

![Les cinq indicateurs de l'évolution sur le tableau de bord de pilotage](img/pilotage-actes.jpg)

Chaque chiffre a été recalculé par un chemin indépendant — une jointure directe entre
`bronze.actes` et `bronze.ccam` rend 8 112 actes et 2 199 450 € — puis ancré dans la suite
d'intégration : les cinq tables ligne à ligne et dans l'ordre, la dimension complétée, le
fait, les quatre règles qualité et le tuple de non-régression y sont littéraux.

### 9.5 Limites propres à l'évolution

- **Le dépôt d'actes est un rattrapage** : vingt-neuf jours d'actes dans un seul fichier.
  L'incrémentalité est démontrée sur ce fichier ; un flux réellement quotidien produirait
  une partition par jour, par le même mécanisme, sans rien changer au code.
- **« Actes par séjour » rapporte les actes aux séjours qui en ont au moins un** (5 096) :
  c'est l'intensité d'un séjour traité, pas une moyenne sur l'activité. Rapportés aux
  6 729 séjours valides, les 8 112 actes donnent 1,21 acte par séjour — une autre question,
  que `kpi_synthese` et `kpi_dms_service` permettent de poser.
- **Le tarif est celui du référentiel courant.** Un changement de tarif recalculerait tout
  l'historique facturé. Facturer par période exigerait d'historiser `dim_ccam` (§8).
- **Le pôle n'est pas modélisé au grain de la catégorie**, faute de hiérarchie stricte dans
  les données (§9.1). Il reste disponible au grain du service, dans `dim_service`.

---

# Partie 2 — Le déploiement Azure

La chaîne du poste (dépôt du CHU → lake pseudonymisé → ClickHouse → dbt → Metabase) portée
sur Azure, décrite intégralement en Terraform, exploitée sans se connecter à une machine.
**Les chiffres publiés y sont identiques à ceux du déploiement local** : c'était le critère
d'acceptation du portage, et il est tenu.

> Tout ce que cette partie affirme a été **relevé sur l'abonnement le 3 septembre 2026**
> (`az`, `terraform state`, journaux des jobs, facture) ou lu dans [`terraform/`](../terraform/).
> Le diagramme est généré depuis [`cloud-architecture.puml`](cloud-architecture.puml) ; un
> test (`tests/test_cloud_diagram.py`) échoue s'il oublie une ressource ou un paramètre.

---

## 10. Pourquoi un cloud, et lequel

Le déploiement local répond déjà au sujet. Le cloud n'apporte que ce qu'un poste **ne peut
pas** offrir — et rien de décoratif :

| Ce que le poste ne peut pas offrir | Ce que le déploiement Azure apporte |
|---|---|
| Un dépôt réaliste | Le CHU dépose dans un **conteneur de stockage objet**, versionné, à suppression réversible — c'est ainsi qu'un hôpital dépose réellement |
| Une planification **sans machine à garder allumée** | Un **job serverless** déclenché chaque nuit par Azure, journalisé, avec réessai et déclenchement manuel pour la reprise. En local, le même cron tourne dans un conteneur de la pile — tant que le poste est allumé |
| Des secrets hors des fichiers | Le `.env` devient un **coffre Key Vault**, lu par identité gérée : aucun mot de passe sur disque, ni dans Git, ni dans un manifeste |
| Un cloisonnement que le code ne peut pas contourner | Les droits de lecture sont attribués **par conteneur de stockage** : la machine de l'entrepôt n'a *aucun droit* sur l'identité en clair |
| Une infrastructure reproductible | `terraform apply` construit les 14 ressources ; `terraform destroy` ne laisse rien. 29 variables, **une seule obligatoire** |

**L'abonnement commande l'architecture.** C'est une offre *Azure for Students*, et ses
contraintes ont été relevées, pas supposées :

| Contrainte relevée | Conséquence |
|---|---|
| Une policy n'autorise que 5 régions (`uaenorth`, `spaincentral`, `italynorth`, `swedencentral`, `germanywestcentral`) — la France est exclue | Parmi elles, seules la Suède et l'Espagne proposent des petites VM. **`swedencentral`** : dans l'Union européenne, donc dans le champ du RGPD, et la moins chère |
| Quota de **6 vCPU** par région | Une seule VM de 2 vCPU. Ni cluster, ni haute disponibilité |
| Crédit de 100 $, limite de dépense activée | ≈ 33 €/mois allumée, 8 en pause (§15) ; budget avec alertes ; `make cloud-stop` entre deux démonstrations |
| Marketplace interdit au crédit | Uniquement Ubuntu et des images de conteneurs publiques |

**Ce qui ne change pas — les invariants.** Un seul code, deux cibles (`local`, `azure`) :
même orchestrateur Python, même SQL bronze, mêmes 37 modèles dbt, mêmes tableaux de bord
provisionnés par code. Vérifié sur les deux déploiements : 92 fichiers sur 29 jours, 20 tables
gold, 28 cartes Metabase sans erreur, **27 résultats de carte sur 28 identiques au bit près**
(la 28ᵉ, le journal d'ingestion, diffère par son horodatage de traitement).

> **Deux écarts trouvés en rédigeant cette partie, corrigés le jour même.** Relire
> l'infrastructure pour la décrire a montré (1) que le droit du job sur le site de
> documentation portait sur le **compte** de stockage entier, et non sur son seul conteneur —
> ramené au conteneur `$web` (§14.2) ; (2) que l'environnement Container Apps n'est pas gratuit :
> il crée une IP publique facturée ~3 €/mois, absente de toutes les estimations (§15).

---

## 11. L'architecture en un diagramme

Vue de **déploiement** au sens du modèle C4 (niveau 4 : *où* tourne chaque brique), avec les
icônes officielles Azure. Elle se lit **de gauche à droite** — la livraison (GitHub, Docker Hub),
puis le traitement (les jobs), puis le stockage — et l'entrepôt en bas, entre les utilisateurs
et le stockage. Chaque boîte porte le nom réel de la ressource ; les paramètres détaillés sont
dans le tableau qui suit. Les flèches numérotées **1 → 7** se lisent dans l'ordre d'une nuit
ordinaire (§13). dbt y figure comme brique à part entière du job nocturne : `eds run` (Python)
collecte, pseudonymise et charge bronze ; `dbt build` construit silver et gold dans ClickHouse.

[![Architecture du déploiement Azure](img/eds-cloud-architecture.png)](img/eds-cloud-architecture.svg)

*Cliquer pour la version vectorielle. Source : [`cloud-architecture.puml`](cloud-architecture.puml), régénérée par `make diagram`.*

| Ce qu'on voit | Signification |
|---|---|
| Cadre **bleu** | Le réseau virtuel et ses deux sous-réseaux : ce qui est dedans se parle par adresse privée |
| Cadre **vert** | L'environnement Container Apps : des jobs sans serveur, zéro réplique entre deux exécutions |
| Cadre **jaune** | La machine virtuelle : trois conteneurs Docker Compose |
| Cadre **violet** | Le compte de stockage et ses trois conteneurs |
| Cadre **gris** | Secrets, identités, journaux — un regroupement de lecture, pas une ressource |
| Boîte **rouge** | Identité en clair. Un seul composant peut la lire : le job de collecte |
| Boîte **verte** | Données pseudonymisées ou agrégées |
| Boîte **gris foncé** | Joignable depuis Internet : l'IP publique, Caddy, le site de documentation |
| Flèches **bleues** | Flux de données du traitement nocturne (1 → 6) |
| Flèches **vertes** | Restitution aux utilisateurs (7) |
| Flèches **violettes**, tiretées | Lecture des secrets par identité gérée |
| Flèches **grises**, pointillées | Exploitation, livraison, provisionnement |

Les 14 ressources du groupe, plus deux hors du groupe :

| Ressource | Nom | Rôle |
|---|---|---|
| Groupe de ressources | `rg-eds-chu-prod` | Tout y vit ; le détruire ne laisse rien |
| Réseau virtuel | `vnet-eds-chu-prod` · `10.20.0.0/16` | Deux sous-réseaux : `snet-warehouse` (`/24`, la VM) et `snet-jobs` (`/27`, délégué à Container Apps) |
| Groupe de sécurité | `nsg-warehouse-eds-chu-prod` | Ce qui peut entrer, et d'où (§14.1) |
| IP publique + carte réseau | `pip-eds-chu-prod` · `nic-warehouse-eds-chu-prod` | `4.223.135.71`, statique, avec un nom DNS Azure ; IP privée **statique** `10.20.1.10` — celle que les jobs appellent |
| Machine virtuelle + disque | `vm-warehouse-eds-chu-prod` | `Standard_B2als_v2` (2 vCPU, 4 Gio), Ubuntu 24.04, disque 32 Gio. Porte **ClickHouse 26.3**, **Metabase 0.58**, **Caddy 2** en Docker Compose |
| Environnement Container Apps | `cae-eds-chu-prod` | Dans le réseau, profil Consommation : zéro réplique entre deux exécutions |
| Trois jobs | `job-eds-pipeline` · `job-eds-provision` · `job-eds-controle` | Le traitement nocturne (cron `5 1 * * *`, 01 h 05 UTC) ; la mise en service ; la preuve du cloisonnement |
| Identité gérée | `id-pipeline-eds-chu-prod` | Ce que les trois jobs *sont* pour Azure — c'est à elle que sont attribués les droits |
| Compte de stockage | `steds4152c908` | Trois conteneurs : `filestorage` (dépôt du CHU, **identité en clair**, versionné), `lake` (pseudonymisé), `$web` (documentation dbt, public) |
| Coffre | `kv-eds-4152c908` | 8 secrets : le sel HMAC, six mots de passe, l'URL SAS du lake |
| Journaux | `log-eds-chu-prod` | Log Analytics, 30 jours, plafond 0,5 Go/jour |
| *Hors du groupe* : budget | `budget-eds-chu-prod` | 60 €/mois, alertes à 50, 80 et 100 % |
| *Hors du groupe* : état Terraform | `rg-eds-tfstate` | Conteneur privé versionné, authentification Entra ID. Il contient les mots de passe générés : jamais dans Git |

---

## 12. Pourquoi ces briques, et pas d'autres

Chaque ligne est un choix **contraint par un fait vérifié**, pas une préférence.

| Brique | Choix | Alternative écartée | Raison |
|---|---|---|---|
| **Entrepôt** | ClickHouse sur une VM, disque local | Container Apps + Azure Files | ClickHouse exige des renommages atomiques et des liens durs ; un partage réseau les casse ([ClickHouse #74572](https://github.com/ClickHouse/ClickHouse/issues/74572)). Même raison que le volume Docker nommé en local |
| | | ClickHouse Cloud, AKS | ≥ 50 $/mois ; quota de 6 vCPU |
| **Taille de VM** | `Standard_B2als_v2`, 4 Gio, 24,38 €/mois | `B2ts_v2` (1 Gio, 6,77 €) | Trop juste pour trois conteneurs dont une JVM |
| | | Variante Arm (21,56 €) | Imposerait des images arm64 pour ClickHouse, Metabase et Caddy : trois variables de plus pour 2,80 €/mois |
| **Dépôt et lake** | Compte de blobs **versionné**, sans espace de noms hiérarchique | ADLS Gen2 | Azure interdit le versioning sur un compte hiérarchique — et le dépôt du CHU est la seule chose non reconstructible du système |
| **Lecture du lake par ClickHouse** | `azureBlobStorage()` avec un **jeton SAS** lecture seule, limité au conteneur, daté | Identité gérée de la VM | ClickHouse 26.3 ne sait pas l'utiliser hors Kubernetes (`WorkloadIdentityCredential`), vérifié |
| | | blobfuse | Une couche FUSE masquerait justement ce qu'on veut montrer : le moteur lit le stockage objet lui-même, comme `file()` en local |
| **Planification** | Job Container Apps `Schedule` | cron sur la VM | Serverless, **dans le réseau**, journalisé en KQL, déclenchable à la main avec le même code — et l'exécution coûte 0,5 % de l'offre gratuite |
| | | Data Factory, Logic Apps | Surdimensionnés pour lancer une commande |
| **Restitution** | Metabase sur la VM, base H2 | Metabase en Container App | ≈ 10 €/mois même au repos, une minute de démarrage à froid |
| **TLS** | Caddy, certificat interne | Let's Encrypt | Inutilisable sur `*.cloudapp.azure.com` : quota d'émission partagé entre tous les clients Azure. Une variable (`acme_hostname`) bascule dès qu'un nom propre existe |
| **Secrets** | Key Vault + identités gérées, RBAC | `.env` sur la VM | La VM lit ses secrets au démarrage par l'adresse de métadonnées (IMDS), sans `azure-cli`, et ne les écrit qu'en `0600` root |
| **Image du pipeline** | Docker Hub, dépôt **public**, `linux/amd64` | Azure Container Registry | 4,35 €/mois pour aucun gain : l'image ne contient que du code — `.dockerignore` exclut données et `.env`. Aucun secret de registre à gérer |
| **Infrastructure** | Terraform, état distant authentifié par Entra ID | Portail, scripts `az` | Reproductible, relu en CI (`fmt`, `validate`), et `terraform plan` vide prouve que le code décrit ce qui tourne |
| **Budget mémoire** | Calculé dans `locals.tf` depuis la taille de VM | Valeurs fixes | Sans limites, ClickHouse dimensionne ses caches sur la RAM visible (5 Gio de cache de marques par défaut) et se fait tuer par le noyau |

---

## 13. Comment ça fonctionne

### 13.1 Une nuit ordinaire — les sept flèches du diagramme

| # | Qui | Quoi | Comment, et pourquoi c'est sûr |
|---|---|---|---|
| **1** | Le CHU — aujourd'hui l'exploitant, par `make cloud-seed` | Dépose ses fichiers dans `filestorage` | `az storage blob upload-batch`, authentifié par Entra ID. Le conteneur est versionné : un fichier écrasé se retrouve |
| **2** | Azure, à 01 h 05 UTC | Démarre `job-eds-pipeline` | Tire l'image publique, injecte les 7 secrets depuis le coffre par l'identité gérée. Zéro réplique le reste du temps |
| **3** | Le job | Lit le dépôt | `Storage Blob Data Reader`, sur ce seul conteneur. Empreinte SHA-256 par fichier : un fichier déjà chargé est ignoré |
| **4** | Le job | Écrit le lake pseudonymisé | `Storage Blob Data Contributor`, sur ce seul conteneur. La pseudonymisation (HMAC-SHA256, sel du coffre) se fait **en flux**, ligne à ligne : l'identité en clair n'est jamais un fichier intermédiaire |
| **5** | Le job, en deux temps | Pilote ClickHouse | HTTP 8123 sur l'IP privée `10.20.1.10`, via le réseau virtuel — le port n'est pas ouvert sur Internet. `eds run` charge bronze par jour (`DROP PARTITION` + `INSERT`) ; `dbt build` construit silver, gold et le rapport qualité, et exécute 135 tests. Aucune donnée ne remonte dans le job : tout est SQL exécuté par le moteur |
| **6** | ClickHouse | Lit lui-même le lake | `azureBlobStorage(lake, …)` : une collection nommée porte l'URL SAS côté serveur. Le jeton n'apparaît ni dans le SQL, ni dans `system.query_log` (règle de masquage), ni dans les journaux du pipeline |
| **7** | Direction, chercheurs | Consultent | HTTPS 443 → Caddy → Metabase → ClickHouse avec `chu_pilotage` ou `chu_recherche`, chacun `SELECT` sur sa seule base gold |

La sortie du job part dans Log Analytics avec le `run_id` — le même que dans
`ops.pipeline_runs` et le rapport qualité du tableau de bord.

**La planification tourne, et le prouve.** Trois exécutions planifiées consécutives — les
2, 3 et 4 septembre, à 01:05:00 UTC précises — toutes `Succeeded` en une trentaine de
secondes. Sans nouveau dépôt, une nuit se résume à : « 92 fichier(s) déjà ingéré(s),
ignoré(s) · Aucun nouveau fichier : les couches silver et gold sont à jour », et une ligne
`success` de plus dans `ops.pipeline_runs`. Le jour où un fichier arrive dans `filestorage`,
la même exécution le charge. `make cloud-status` affiche ces passages ; la requête KQL des
sorties Terraform en donne le détail. En local, le conteneur `scheduler` de la pile Docker
Compose fait la même chose, depuis la même image et sur le même cron
([§3.4](#34-automatisation--planification-erreurs-traçabilité)).

### 13.2 Ce qui se passe quand la VM démarre

La pile est un service systemd (`eds-stack`). À chaque démarrage, avant Docker Compose, un
script de 50 lignes demande un jeton à l'adresse de métadonnées locale (IMDS), lit dans le
coffre le mot de passe ETL et l'URL SAS, écrit le premier dans `/opt/eds/.env` (`0600`, root)
et la seconde dans la configuration de ClickHouse. Conséquence : **changer un secret ou
renouveler le jeton = redémarrer la VM.** Rien n'est écrit dans `custom_data`, qui finirait
dans l'état Terraform et serait lisible de quiconque a un droit de lecture sur la VM.

### 13.3 Mise en service, de zéro

| Étape | Commande | Ce qu'elle fait |
|---|---|---|
| 1 | `make cloud-bootstrap` | Une fois : enregistre les fournisseurs Azure, crée le stockage de l'état Terraform — le socle ne peut pas être géré par l'état qu'il héberge |
| 2 | `make image-push` | Construit l'image en `linux/amd64` (un Mac produirait de l'arm64, que Container Apps refuse) et la publie |
| 3 | `make cloud-apply` | ≈ 10 min : réseau, stockage, coffre, VM, jobs, budget |
| 4 | `make cloud-seed` | Dépose les 92 fichiers du CHU |
| 5 | `make cloud-provision` | `job-eds-provision` : bases, tables, comptes cloisonnés, connexions, groupes, tableaux de bord Metabase, documentation dbt. Idempotent |
| 6 | `make cloud-run` | Premier traitement. Ensuite, chaque nuit, tout seul |
| 7 | `make cloud-check` | `job-eds-controle` : se connecte réellement avec chaque compte et exige un refus explicite hors périmètre |

Les identifiants n'existent que dans le coffre : `az keyvault secret show --vault-name
kv-eds-4152c908 -n mb-pilotage-password`.

### 13.4 Exploitation et reprise

**Le geste normal : aucun.** `make cloud-status` montre la VM et les trois derniers passages
de chaque job ; `make cloud-logs` la dernière exécution.

| Situation | Geste |
|---|---|
| Rejouer un jour | `az containerapp job start -n job-eds-pipeline … --args 'run,--date,2026-08-27'` — même code que la nuit, `DROP PARTITION` garantit l'absence de doublon |
| Modèle dbt modifié | `git push` reconstruit l'image ; `make cloud-run` la tire à l'exécution suivante |
| Pause entre deux démonstrations | `make cloud-stop` désalloue la VM ; `make cloud-start` la remonte, pile comprise, en deux minutes |
| Tableaux de bord perdus, VM recréée | `make cloud-provision` — tout est défini en code |
| Vérifier que le code décrit ce qui tourne | `make cloud-plan` doit être vide |

**Livraison.** Chaque poussée sur `main` déclenche la CI (style, tests unitaires, compilation
dbt, validation Terraform, puis la démonstration complète depuis un clone nu) et la
reconstruction de l'image, étiquetée `latest` et par commit. Les jobs tirent `latest` ; épingler
un commit dans `terraform.tfvars` fige une version avant une démonstration.

---

## 14. Qui peut lire quoi — sécurité et RGPD

### 14.1 Réseau : ce qui entre, et d'où

| Port | Ouvert à | Pour | Vérifié le 3 septembre |
|---|---|---|---|
| 443 | Internet | Tableaux de bord, derrière Caddy | Répond ; HSTS, redirection 80 → 443 |
| 80 | Internet | Redirection vers HTTPS | `308 Permanent Redirect` |
| 8123 (ClickHouse) | `snet-jobs` seulement | Le pipeline | **Délai d'attente depuis Internet** : l'entrepôt n'écoute pas dehors |
| 3000 (Metabase) | `snet-jobs` seulement | Le provisionnement par API | Idem |
| 22 | L'adresse du poste au dernier `apply` | Administration, tunnel SSH vers la console SQL | Non utilisé par le projet : tout passe par `az` |
| Tout le reste | Personne | — | Refus explicite, priorité 4096 |

Le cloisonnement des tableaux de bord ne repose **pas** sur le réseau (443 est ouvert à tous,
c'est une démonstration) mais sur l'authentification Metabase et les `GRANT` ClickHouse.

### 14.2 Identités et droits — relevés, pas déclarés

| Identité | `filestorage` (clair) | `lake` | `$web` | Coffre |
|---|---|---|---|---|
| **Jobs** (`id-pipeline-eds-chu-prod`) | Lecture | Lecture, écriture | Écriture (documentation) | Lecture des secrets |
| **VM** (ClickHouse, Metabase) | **aucun droit** | Lecture seule, par jeton SAS daté | — | Lecture des secrets |
| Comptes SQL `chu_pilotage`, `chu_recherche` | aucun | aucun | — | aucun |
| Exploitant (compte Entra ID du poste) | Écriture (dépôt) | Écriture | Écriture | Écriture des secrets |

> **La machine qui héberge l'entrepôt ne peut pas lire les noms et les NIR.** Pas « ne le fait
> pas » : *ne le peut pas*. Aucun rôle ne lui est attribué sur le compte de stockage
> (`az role assignment list` ne lui connaît que la lecture du coffre), et le jeton confié à
> ClickHouse ne vise que `lake`, en lecture, pour 180 jours. C'est le **quatrième niveau** du
> cloisonnement décrit en [§6](#6-restitution-et-cloisonnement) — le seul
> que le code ne peut pas contourner.

Les droits des identités de la plateforme sont attribués **au conteneur**, jamais au compte.
Celui du job sur `$web` faisait exception jusqu'à ce jour : il portait sur le compte entier,
donc aussi sur `filestorage` en écriture. Ramené au conteneur, appliqué, et vérifié par une
exécution de `job-eds-provision` qui a republié la documentation. Seul l'exploitant garde un
droit d'écriture sur le compte entier, pour `make cloud-seed` — attribué à la main, hors
Terraform, comme le droit sur le stockage de l'état : c'est le geste d'amorçage, pas la
plateforme.

### 14.3 Secrets : où ils vivent, qui les lit

| Secret | Où | Lu par | Jamais dans |
|---|---|---|---|
| Sel de pseudonymisation | Coffre — **irremplaçable** : le perdre rompt toutes les jointures | Le job, en variable d'environnement | Git, journaux, SQL |
| Six mots de passe (ClickHouse × 3, Metabase × 3) | Coffre, générés par Terraform (28 caractères) | Les jobs ; la VM ne lit que celui de l'ETL | Git, `custom_data`, manifestes ARM — les jobs ne portent que des *références* |
| URL SAS du lake | Coffre, renouvelée par `terraform apply` 15 jours avant son terme | La VM, au démarrage → configuration ClickHouse | Le SQL envoyé, `system.query_log` (masquage `sig=…`) |
| État Terraform | Conteneur privé, versionné, Entra ID | L'exploitant | Git, le poste |

Le coffre est en suppression réversible 7 jours, **sans** protection contre la purge : un
projet pédagogique doit rester destructible. Pour un CHU, la protection serait activée.

### 14.4 Données de santé : où sont-elles ?

| Zone | Contenu | Identifiant |
|---|---|---|
| `filestorage` | Les exports du CHU tels que déposés | **Oui** — NIR, nom, prénom, date de naissance |
| `lake` | Copie de travail | Non — `patient_pseudo` (HMAC), année de naissance ; NIR, nom et prénom n'y sont jamais copiés |
| ClickHouse (VM) | bronze, silver, gold, ops | Non — construit uniquement depuis `lake` |
| Metabase, `$web` | Agrégats, métadonnées | Non |
| Journaux, état Terraform | Exploitation | Non |

La région est `swedencentral` : Union européenne, donc RGPD. Un CHU réel exigerait un
hébergeur certifié HDS en France — possible sur un abonnement payant en changeant la seule
variable `location` (§16).

---

## 15. Combien ça coûte

Tarifs Linux relevés à l'API tarifaire Azure pour `swedencentral` le 3 septembre 2026, base
730 h/mois. **Puis la facture réelle**, qui a révélé un poste oublié.

| Poste | Détail | €/mois |
|---|---|---:|
| VM `Standard_B2als_v2` | 2 vCPU, 4 Gio · 0,0334 €/h | **24,38** |
| Disque OS | Standard SSD E4, 32 Gio, LRS | **2,06** |
| IP publique de la VM | Standard, statique · 0,0043 €/h | **3,14** |
| IP publique de l'environnement Container Apps | Créée par Azure dans son groupe géré `ME_cae-…`, **facturée même quand aucun job ne tourne** | **3,14** |
| Stockage | ≈ 11 Mo, versionné | 0,01 |
| Key Vault, Log Analytics, exécution des jobs | Sous les offres gratuites | ≈ 0 |
| Registre d'images | Docker Hub, public | 0 |
| | **Allumée en permanence** | **≈ 32,7** |

**Facture relevée** depuis le 1ᵉʳ septembre (deux jours pleins) : 2,19 €, dont 1,43 € de VM,
0,37 € de disque et deux fois 0,19 € d'IP publique — le rythme de ≈ 33 €/mois est confirmé.
L'IP de l'environnement n'était dans aucune estimation : « les jobs sont gratuits » était vrai
pour l'exécution, faux pour l'infrastructure qui les porte.

| Levier | Facture | Quand |
|---|---:|---|
| `make cloud-stop` (VM désallouée, disque et IP conservés) | **≈ 8,3 €/mois** | Entre deux démonstrations — le plus efficace |
| Mode nuit, 22 h → 8 h (`auto_shutdown_time` + `auto_startup_cron`) | ≈ 22,6 €/mois | Préparé dans Terraform, **non activé** : les deux variables sont commentées dans `terraform.tfvars` |
| `make cloud-destroy` | 0 € | Le dépôt local et l'état Terraform survivent |

Un budget de 60 €/mois avec alertes à 50, 80 et 100 % est en place ; la limite de dépense de
l'offre étudiante désactive les ressources à crédit épuisé — la facturation ne peut pas
devenir négative.

---

## 16. Limites, et ce qu'on ferait pour un vrai CHU

| Limite | Pourquoi ici | Pour un CHU |
|---|---|---|
| **Point unique de défaillance** | Quota de 6 vCPU : une seule VM | Cluster ClickHouse à 3 nœuds, Metabase répliqué derrière un Application Gateway |
| **Pas de sauvegarde de l'entrepôt** | Tout se reconstruit en dix minutes depuis `filestorage` (versionné) et le sel (coffre) — la VM est du bétail, pas un animal de compagnie | Instantanés de disque, `BACKUP` ClickHouse vers un conteneur froid, protection contre la purge du coffre |
| **Certificat auto-signé** | Let's Encrypt saturé sur `cloudapp.azure.com` ; le navigateur avertit une fois, le trafic est chiffré | Nom de domaine de l'hôpital, certificat de confiance — une variable Terraform |
| **Stockage joignable par le réseau public** | Un point de terminaison privé exige un profil Container Apps dédié, facturé | Points de terminaison privés sur le stockage et le coffre, accès public bloqué |
| **Jeton SAS plutôt qu'identité gérée** pour ClickHouse | Limite de ClickHouse 26.3 sur une VM | À rebasculer dès que le moteur le permettra ; seul `lake.xml` change |
| **Suède, pas France** | Policy de l'offre étudiante | Abonnement payant, région française, hébergeur certifié HDS : la variable `location` |
| **Metabase à ~78 % de sa limite mémoire** | 4 Gio partagés par trois conteneurs ; budget JVM redécoupé et vérifié sous charge | VM à 8 Gio (`Standard_B2s_v2`, 65,82 €/mois) |
| **Metabase sur H2** | Deux comptes, reconstructible par code | PostgreSQL managé |
| **Règle SSH liée à une adresse** | Elle suit l'adresse du poste au dernier `apply` ; `terraform plan` la signale dès que l'adresse change | Bastion, ou suppression de la règle — SSH n'est pas utilisé |
| **Contrôle du cloisonnement à la demande seulement** | `job-eds-controle` est en déclenchement manuel, comme son jumeau local | Le passer en déclencheur planifié (hebdomadaire) sur les deux cibles — il resterait lançable à la main |
| **Mode nuit non activé** | Deux variables suffisent ; laissé éteint pour que la plateforme réponde à toute heure pendant l'évaluation | L'activer : 22,6 €/mois |
| **Une seule région, réplication locale (LRS)** | Coût | Réplication géo-redondante du dépôt, plan de reprise |
| **Supervision limitée aux alertes de budget** | Aucun test de disponibilité | Alerte Azure Monitor sur `job-eds-pipeline` en échec et sur la VM arrêtée |

**Trois recommandations de gouvernance**, qui relèvent de l'organisation et non du code :

1. Le sel de pseudonymisation est le seul élément **non reconstructible** de la plateforme :
   activer la protection contre la purge du coffre, et documenter qui a le droit de le lire.
2. Faire délivrer au CHU un jeton d'écriture sur `filestorage`, et rien d'autre : le dépôt
   devient son geste, pas celui de l'exploitant.
3. Exiger que `terraform plan` soit vide avant toute démonstration : c'est la preuve que le
   code décrit ce qui tourne, et donc que cette partie est encore vraie.

---

# Partie 3 — Exploitation des résultats

Les deux premières parties disent comment les chiffres sont produits, et où. Celle-ci les lit
comme le feraient une direction d'hôpital, un cadre de santé, le département d'information
médicale (DIM) ou un chercheur. Tout chiffre y est calculé dans l'entrepôt, sur silver et
gold, à la date du dernier traitement ; les tables d'origine sont nommées sous chaque tableau.

---

## 17. Comment lire ces chiffres

**Le jeu est synthétique : la méthode compte plus que les conclusions.** Cette partie tire
des conclusions *comme si* les chiffres étaient ceux du CHU, et dit lesquels décrivent un
hôpital plutôt que le générateur qui a produit les fichiers. Un chiffre cliniquement
invraisemblable est un résultat utile : sur des données réelles, ce serait le signal qu'une
source est cassée. Chaque constat porte donc une étiquette :

| Étiquette | Sens |
|---|---|
| **Exploitable** | Le signal a une structure cohérente ; sur des données réelles, on agirait dessus |
| **Artefact probable** | Le signal ressemble à un tirage aléatoire du générateur ; on retient la méthode, pas la valeur |
| **Défaut de source** | Le signal révèle une donnée manquante ou incohérente à corriger en amont |

Les dix chiffres à garder en tête :

| Chiffre | Valeur | Lecture |
|---|---:|---|
| Séjours valides, 28 jours d'admissions | 6 729 | 240 admissions par jour |
| Patients distincts | 5 949 (6 000 déposés) | 1,13 séjour par patient ; 754 patients revenus au moins une fois |
| Patients présents un jour donné | ≈ 1 240 | admissions par jour × DMS (loi de Little) ; 1 246 observés en moyenne |
| Durée moyenne de séjour | 5,15 j | de 2,15 j aux urgences à 9,05 j en réanimation |
| Admissions en mode urgence | 49 % | 26 % par mutation, 24 % programmées |
| Sorties | 50 % domicile, 17 % transfert, 17 % mutation, **16,5 % décès** | la mortalité est le premier chiffre à ne pas publier tel quel (§19.1) |
| Réadmission à 30 jours | 11,59 % | borne basse ; 133 de ces « réadmissions » suivent un décès enregistré |
| Relevés en alerte | 8,1 % | stable sur la période, identique en cardiologie et en réanimation |
| Actes et facturation | 8 112 actes · 2 199 450 € | 76 % des séjours ont au moins un acte ; 270 € par acte |
| Lits déclarés | 191 (7 services) | pour ≈ 1 240 patients présents : l'incohérence à traiter en premier (§18.3) |

*Sources : `kpi_synthese`, `fact_sejour`, `kpi_readmissions_30j`, `kpi_alertes_jour`, `kpi_facturation_service`, `dim_service`.*

---

## 18. Activité et capacité : où sont les patients, et combien de lits il faudrait

### 18.1 Où sont les patients

| Service | Séjours | Part | Adm./jour | DMS (j) | Médiane (j) | Présents en moyenne | Pathologie principale dominante |
|---|---:|---:|---:|---:|---:|---:|---|
| Cardiologie | 1 601 | 23,8 % | 57 | 5,31 | 4,71 | 306 | diabète 47 %, insuffisance cardiaque 34 %, infarctus 19 % |
| Urgences | 1 423 | 21,1 % | 51 | 2,15 | 2,04 | 141 | infection urinaire 57 %, puis neuf autres |
| Neurologie | 1 208 | 18,0 % | 43 | 7,06 | 5,83 | 288 | épisode dépressif 62 %, AVC 38 % |
| Pneumologie | 840 | 12,5 % | 30 | 6,20 | 5,71 | 183 | pneumopathie 69 %, BPCO 31 % |
| Pédiatrie | 503 | 7,5 % | 18 | 3,19 | 2,58 | 67 | appendicite 72 % |
| Chirurgie | 476 | 7,1 % | 17 | 4,39 | 3,67 | 79 | appendicite 100 % |
| Réanimation | 467 | 6,9 % | 17 | 9,05 | 8,21 | 131 | pneumopathie 28 %, insuffisance cardiaque 27 %, AVC 26 % |
| Oncologie | 211 | 3,1 % | 7,5 | 6,87 | 5,67 | 50 | cancer bronchique 100 % |
| **Total** | **6 729** | 100 % | **240** | **5,15** | | **1 246** | |

*Sources : `fact_sejour`, `kpi_dms_service`, `kpi_activite_service` (moyenne du 1er au 28 août), `fact_diagnostic` (diagnostic principal).*

- **Trois services font 63 % de l'activité** — cardiologie, urgences, neurologie — et 59 %
  des patients présents. Toute action sur la charge de l'hôpital commence par eux.
  *Exploitable.*
- **La DMS est du case-mix, pas une performance.** Chaque service porte une pathologie
  dominante et sa durée : la réanimation (9 j) traite des pneumopathies, des insuffisances
  cardiaques et des AVC ; les urgences (2,2 j) des infections urinaires. La correspondance
  service ↔ pathologie est cliniquement cohérente — chirurgie = appendicites, oncologie =
  cancers bronchiques, pneumologie = pneumopathies et BPCO. Comparer les DMS entre services
  n'a donc pas de sens ; comparer la DMS d'un service à lui-même dans le temps, ou entre
  établissements à case-mix égal, en a. *Exploitable.*
- **La médiane est partout sous la moyenne** (réanimation 8,2 contre 9,1 j ; neurologie 5,8
  contre 7,1). Les distributions sont asymétriques : quelques séjours longs tirent la moyenne.
  Pour dimensionner des lits, c'est la moyenne qui compte (elle porte les journées) ; pour
  repérer les séjours à examiner, c'est l'écart à la médiane. *Exploitable.*
- **Les urgences hébergent.** 2,15 j — 52 heures — de durée moyenne, c'est le comportement
  d'une unité d'hospitalisation de courte durée, pas d'un service d'accueil. Et 146 séjours y
  sont « en cours » à la fin du dépôt, âgés de 8,5 jours en moyenne : quatre fois la DMS du
  service. Ce ne sont pas des patients toujours présents, ce sont des **sorties non
  transmises**. Même lecture pour les 683 séjours en cours de l'hôpital, âgés de 7,8 à 8,7 j
  selon le service. *Défaut de source.*

### 18.2 Le rythme : une activité qui monte, sans saisonnalité hebdomadaire

| Semaine complète | Admissions | Par jour | Dont urgences (mode) |
|---|---:|---:|---:|
| 3 → 9 août | 1 671 | 239 | 816 |
| 10 → 16 août | 1 814 | 259 | 903 |
| 17 → 23 août | 2 036 | 291 | 1 019 |

*Sources : `fact_sejour`, `kpi_urgences_jour`.*

- **+22 % en deux semaines**, portés par tous les modes d'admission (urgence +25 %), avec un
  pic le 21 août : 307 admissions, dont 82 passages aux urgences. Les passages aux urgences
  passent de 49 à 52 par jour d'une quinzaine à l'autre. Sur des données réelles, ce serait
  une tension d'été à anticiper en effectifs. *Exploitable.*
- **Aucune saisonnalité hebdomadaire** : de 247 à 274 admissions par jour selon le jour de
  la semaine, une fois écartés les jours incomplets. Un hôpital réel admet moins le week-end
  (pas de programmé) ; ici, les modes sont tirés indépendamment du jour. *Artefact probable.*
- **Les trois derniers jours sont partiels** : 40, 50 et 62 admissions les 26, 27 et 28 août,
  contre 300 la veille ; 9, 11 et 16 passages aux urgences contre une soixantaine. Rien n'a
  baissé : le dépôt s'arrête. Toute lecture de tendance s'arrête donc au 25 août, et la courbe
  de charge après le 28 (sorties seules) ne décrit rien. Un contrôle « jour déposé à moins de
  la moitié de la médiane » l'aurait signalé (§22.1). *Défaut de source.*

### 18.3 Les lits : combien il en faudrait, et ce que dit le référentiel

Le nombre de lits nécessaires se déduit des deux mesures publiées, par la **loi de Little** :
patients présents = admissions par jour × durée moyenne de séjour. L'entrepôt permet de
vérifier la formule contre la charge observée jour par jour, et les deux coïncident.

| Service | Lits déclarés | Présents en moyenne | Lits requis (Little) | Présents par lit déclaré | Part des lits déclarés | Part du besoin |
|---|---:|---:|---:|---:|---:|---:|
| Cardiologie | 30 | 306 | 304 | 10,2 | 15,7 % | 24,5 % |
| Neurologie | — | 288 | 305 | — | — | 24,6 % |
| Pneumologie | 28 | 183 | 186 | 6,5 | 14,7 % | 15,0 % |
| Urgences | 20 | 141 | 109 | 7,1 | 10,5 % | 8,8 % |
| Réanimation | 16 | 131 | 151 | 8,2 | 8,4 % | 12,2 % |
| Chirurgie | 40 | 79 | 75 | 2,0 | 20,9 % | 6,1 % |
| Pédiatrie | 22 | 67 | 57 | 3,0 | 11,5 % | 4,6 % |
| Oncologie | 35 | 50 | 52 | 1,4 | 18,3 % | 4,2 % |
| **Total** | **191** | **1 246** | **1 239** | **6,5** | 100 % | 100 % |

*Sources : `dim_service`, `kpi_activite_service`, `kpi_dms_service`, `fact_sejour`. Lits requis = admissions par jour × DMS ; part du besoin sur les 1 239 lits requis.*

- **191 lits ne peuvent pas héberger 1 240 patients.** Le facteur est de 6,5 ; même en
  retirant la neurologie, non décrite, il reste de 5. Soit le référentiel de capacité est faux
  — des lits par unité et non par service, une colonne mal renseignée — soit les volumes sont
  ceux de six CHU. Dans les deux cas, **le KPI « densité d'actes par lit » ne se lit qu'en
  relatif**, et la première décision n'est pas une décision de lits : c'est de faire valider
  `description_service` par le DIM. *Défaut de source.*
- **En relatif, le signal est net et robuste** : si toutes les capacités sont sous-déclarées
  du même facteur, les proportions tiennent. La chirurgie détient 21 % des lits pour 6 % du
  besoin, l'oncologie 18 % pour 4 %, la pédiatrie 11,5 % pour 4,6 % ; la cardiologie 16 % pour
  24,5 %, la réanimation 8 % pour 12 %. Autrement dit : **trop de lits en chirurgie, en
  oncologie et en pédiatrie ; pas assez en cardiologie et en réanimation** ; pneumologie et
  urgences à l'équilibre. C'est la lecture qu'attend une direction, et elle survit à
  l'incohérence du référentiel. *Exploitable, sous réserve du référentiel.*
- **Le levier n'est pas que le lit, c'est la durée.** Réduire d'une journée la DMS libère
  autant de lits qu'il y a d'admissions par jour : 57 en cardiologie, 43 en neurologie, 30 en
  pneumologie. Les séjours au-delà de la médiane sont l'endroit où chercher. *Exploitable.*

### 18.4 Les flux : d'où viennent les patients, où vont-ils

Les patients entrent à 49 % en urgence, 26 % par mutation, 24 % en programmé, et sortent à
50 % vers le domicile, 17 % par transfert, 17 % par mutation, **16,5 % par décès** (§19.1).

Un hôpital réel a des profils très différents d'un service à l'autre : la chirurgie et
l'oncologie sont très majoritairement programmées, les urgences ne le sont jamais, la
réanimation sort par mutation. Ici, **chaque service reçoit et libère ses patients dans les
mêmes proportions que les autres** — au plus quatre points d'écart sur chaque mode : ils sont
tirés indépendamment du service. *Artefact probable.* La méthode reste : sur des données
réelles, la part de programmé par service pilote les blocs et la destination des sorties
décrit l'aval, deux vues que `kpi_flux` publie déjà au grain du jour.

*Sources : `fact_sejour`, `kpi_flux`.*

---

## 19. Qualité et sécurité des soins : mortalité, réadmissions, alertes

### 19.1 Mortalité : le chiffre qu'il ne faut pas publier tel quel

| Catégorie | Séjours clos | Décès | Taux |
|---|---:|---:|---:|
| Pédiatrie | 448 | 88 | 19,6 % |
| Réanimation | 423 | 77 | 18,2 % |
| Médecine (cardiologie, pneumologie, oncologie) | 2 397 | 391 | 16,3 % |
| Urgences | 1 277 | 206 | 16,1 % |
| Neurologie (non décrite) | 1 077 | 168 | 15,6 % |
| Chirurgie | 424 | 65 | 15,3 % |
| **Hôpital** | **6 046** | **995** | **16,5 %** |

*Sources : `fact_sejour` (`is_deces`), `dim_service`.*

Un décès sur six séjours, **partout** : de 15 à 20 % selon le service, de 13,7 % à 18,1 % selon
la pathologie principale, et la pédiatrie en tête. Les séjours qui se terminent par un décès
durent autant que les autres (réanimation 9,7 contre 8,9 j, urgences 2,2 contre 2,1). Un
établissement réel est autour de 2 à 4 %, concentré en réanimation et en oncologie, presque
nul en pédiatrie et en chirurgie programmée. Ici, le décès est un mode de sortie tiré au sort.
*Artefact probable.*

Deux faits vont plus loin que l'artefact, parce qu'ils sont **impossibles** et non seulement
improbables : 136 admissions surviennent après un décès antérieur du même patient (règle Q7,
§4), et 133 des 780 réadmissions comptées suivent un séjour terminé par un décès. Sur des
données réelles, cela désignerait soit une fusion d'identités (deux personnes sous un même
IPP), soit un codage de sortie erroné. *Défaut de source.*

Ce qu'on garde : la mécanique — mortalité par service et par pathologie, durée des séjours
des décédés — et une décision à prendre avec le DIM sur le dénominateur des réadmissions
(§7.4, hypothèse 2) : hors décès, le taux vaudrait 647 / 6 729 = 9,6 %, ou 11,3 % sur les
seuls séjours dont le patient est sorti vivant.

### 19.2 Réadmissions : un problème de parcours, pas de service

| Service du séjour initial | Séjours | Réadmis sous 30 j | Taux |
|---|---:|---:|---:|
| Chirurgie | 476 | 70 | 14,7 % |
| Pédiatrie | 503 | 74 | 14,7 % |
| Urgences | 1 423 | 192 | 13,5 % |
| Oncologie | 211 | 25 | 11,9 % |
| Cardiologie | 1 601 | 187 | 11,7 % |
| Neurologie | 1 208 | 123 | 10,2 % |
| Pneumologie | 840 | 78 | 9,3 % |
| Réanimation | 467 | 31 | 6,6 % |

| Trajectoire (séjour initial → réadmission) | Paires |
|---|---:|
| Pédiatrie → Pédiatrie | 75 |
| Cardiologie → Cardiologie | 69 |
| Urgences → Urgences | 66 |
| **Urgences → Cardiologie** | 49 |
| Cardiologie → Urgences | 40 |
| **Urgences → Neurologie** | 40 |
| Chirurgie → Chirurgie | 36 |
| Neurologie → Urgences | 34 |
| Neurologie → Cardiologie | 32 |
| Cardiologie → Pneumologie | 32 |

*Sources : `kpi_readmissions_service`, `fact_sejour` (paires séjour → admission du même patient sous 30 jours ; 806 paires pour 780 séjours réadmis).*

- **63 % des réadmissions arrivent dans un autre service** que celui du séjour initial (505
  paires sur 806), avec un délai médian de **7 jours**. La réadmission n'est donc pas le
  problème d'un service, c'est celui d'un **parcours** : le patient passé aux urgences revient
  une semaine plus tard en cardiologie ou en neurologie. Une consultation de suivi à J+7 après
  un passage aux urgences pour motif cardiaque ou neurologique est la mesure que ces chiffres
  désignent. *Exploitable.*
- **Chirurgie et pédiatrie sont en tête (14,7 %)** avec, après les urgences, les DMS les plus
  courtes de l'hôpital : le schéma classique de la sortie précoce. À surveiller en premier si
  ces chiffres étaient réels. *Exploitable.*
- **La réanimation est la plus basse (6,6 %)** parce que ses patients en sortent par mutation
  vers un autre service : le séjour suivant n'est pas une réadmission, et le service « initial »
  auquel l'indicateur attribue la réadmission est rarement elle. Lire ce classement sans cette
  précaution pénaliserait les services d'aval. *Exploitable.*
- Le taux est identique quel que soit le mode de sortie — domicile 12,9 %, transfert 12,0 %,
  mutation 13,4 %, décès 13,4 % — ce qui, pour le dernier, est impossible (§19.1). *Artefact
  probable.* Et le 11,59 % global reste une **borne basse** : aucun séjour n'a 30 jours
  d'observation (§5.3).

### 19.3 Surveillance des constantes

| | Cardiologie | Réanimation |
|---|---:|---:|
| Séjours monitorés / séjours du service | 677 / 1 601 (42 %) | 195 / 467 (42 %) |
| Relevés | 31 745 | 9 175 |
| Relevés par séjour monitoré | 47 | 47 |
| Relevés en alerte | 2 582 (8,1 %) | 732 (8,0 %) |
| dont fréquence cardiaque · saturation · température | 875 · 862 · 845 | 230 · 265 · 237 |

*Sources : `kpi_alertes_service`, `kpi_alertes_jour`, `fact_monitoring`.*

- **8 % d'alertes, stables** (8,0 % la première quinzaine, 8,2 % la seconde), identiques dans
  les deux services et réparties à parts égales entre les trois constantes. Les alertes de
  fréquence cardiaque se partagent entre bradycardies (566, autour de 45 bpm) et tachycardies
  (539, autour de 120) ; les désaturations sont à 88,5 % en moyenne, les fièvres à 39,3 °C.
  C'est le bruit de fond d'une unité monitorée, et le seuil de vigilance est bien placé : il
  détecte, il ne sature pas. *Exploitable.*
- **Aucun relevé ne porte deux constantes hors seuil** — zéro sur 3 314. Cliniquement, une
  fièvre accélère le cœur et une désaturation aussi ; ici les trois constantes sont tirées
  indépendamment. Sur des données réelles, la co-occurrence est précisément le signal
  d'escalade à construire. *Artefact probable.*
- **42 % de couverture dans les deux services** : plus d'un séjour de cardiologie sur deux
  n'a aucun relevé. Quels lits sont équipés, et pourquoi ceux-là ? C'est la question à poser
  avant d'étendre la surveillance à la pneumologie et à la neurologie (AVC). *Exploitable.*
- **2 % de relevés de capteurs en panne** (858 sur 41 778), écartés par la règle Q4, avec une
  signature nette — fréquence cardiaque et saturation aberrantes sur la même ligne. Un suivi
  de ce taux par service est un indicateur de maintenance biomédicale gratuit, déjà calculé.
  *Exploitable.*

---

## 20. Population et pathologies : qui sont les patients, et de quoi souffrent-ils

### 20.1 Qui sont les patients

| | Valeur |
|---|---|
| Patients déposés | 6 000 — 2 985 femmes, 3 015 hommes |
| Âge moyen | 57,3 ans ; 45 % ont 65 ans ou plus, 8 % moins de 18 ans |
| Tranches les plus peuplées | 60-69 ans (1 185) et 70-79 ans (999) : 36 % de la population |
| Résidence | huit départements d'Île-de-France, de 12,4 % à 13,2 % chacun |
| Pathologies distinctes par patient | une : 34 % · deux : 35 % · trois : 27 % · quatre et plus : 4 % |
| Diagnostics par séjour | 1,87 (un principal, 0,87 secondaire en moyenne) |

*Sources : `dim_patient`, `cohorte_demographie_globale`, `fact_diagnostic`.*

- **Une population âgée et polypathologique** : deux patients sur trois cumulent au moins
  deux pathologies, et les quatre affections les plus fréquentes — infection urinaire,
  diabète, insuffisance cardiaque, BPCO — touchent chacune 30 à 37 % des patients. C'est le
  profil d'un CHU de recours, et c'est la cohorte que la recherche devrait regarder en
  premier : les patients qui portent à la fois insuffisance cardiaque, diabète et BPCO
  (§22.1). *Exploitable.*
- **Le recrutement territorial est plat** : huit départements à un huitième chacun. Un
  établissement réel recrute selon la distance ; le grain départemental a été retiré des vues
  de recherche (§7.2), et ces chiffres montrent qu'il n'aurait rien appris. *Artefact
  probable.*

### 20.2 Pathologies : prévalence, profil, durée

| Code | Pathologie | Patients (tous rangs) | Prévalence | Séjours clos (diag. principal) | Tranche dominante | Femmes | DMS (j) |
|---|---|---:|---:|---:|---|---:|---:|
| N39 | Infection des voies urinaires | 2 234 | 37,2 % | 798 | 60-69 | 96 % | 2,18 |
| E11 | Diabète de type 2 | 2 177 | 36,3 % | 776 | 40-49 | 54 % | 4,95 |
| I50 | Insuffisance cardiaque | 2 156 | 35,9 % | 678 | 60-69 | 60 % | 5,52 |
| J44 | BPCO | 1 775 | 29,6 % | 262 | 60-69 | 0 % | 5,84 |
| J18 | Pneumopathie | 850 | 14,2 % | 773 | 60-69 | 56 % | 5,92 |
| F32 | Épisode dépressif | 827 | 13,8 % | 752 | 40-49 | 45 % | 6,61 |
| K35 | Appendicite aiguë | 806 | 13,4 % | 801 | 10-19 | 41 % | 3,79 |
| I63 | AVC ischémique | 643 | 10,7 % | 575 | 60-69 | 54 % | 6,93 |
| I21 | Infarctus du myocarde | 421 | 7,0 % | 404 | 50-59 | 0 % | 5,75 |
| C34 | Cancer bronchique | 239 | 4,0 % | 214 | 70-79 | 0 % | 6,25 |
| G12 | Amyotrophie spinale | 8 | 0,13 % | 6 | masqué | masqué | — |
| E84 · Q90 | Mucoviscidose · Trisomie 21 | masqué (< 5) | — | — | — | — | — |

*Sources : `prevalence_pathologie`, `cohorte_demographie` (diagnostic principal, cellules diffusables), `fact_diagnostic` ⋈ `fact_sejour`. Les cellules masquées le sont ici comme au tableau de bord.*

- **Les quatre grandes pathologies sont des comorbidités plus que des motifs.** Le diabète
  concerne 2 177 patients, mais n'est le diagnostic principal que de 776 séjours ; l'infection
  urinaire, 2 234 patients pour 798 séjours. Deux questions, deux comptes — c'est la raison
  pour laquelle la prévalence et la description de cohorte ne lisent pas le même rang de
  diagnostic (§5.1). *Exploitable.*
- **Les durées par pathologie sont cohérentes** : l'AVC et l'épisode dépressif sont les plus
  longs (6,6 à 6,9 j), l'appendicite est courte (3,8 j), l'infection urinaire très courte
  (2,2 j, traitée aux urgences). C'est ce case-mix qui fabrique les DMS par service de §18.1.
  *Exploitable.*
- **Trois pathologies n'ont aucune femme** en diagnostic principal — infarctus, BPCO, cancer
  bronchique — là où la réalité est autour de 60 à 70 % d'hommes ; à l'inverse 96 % de femmes
  pour l'infection urinaire est plausible mais extrême. Les sex-ratios de ce jeu ne doivent
  pas être exploités. *Artefact probable.*
- **Quinze patients portent une maladie rare** (8, 4 et 3) : deux effectifs sur trois sont
  masqués, et la tranche d'âge de la troisième aussi. La recherche sur ces cohortes ne passe
  pas par le tableau de bord ; elle passe par un accès sur convention, à définir avec le
  délégué à la protection des données (§8). *Exploitable.*

---

## 21. Actes et facturation : ce que produit le plateau technique, et ce que ça rapporte

### 21.1 Ce que produit le plateau technique

- **Le volume d'actes est une fonction du nombre de séjours, et de rien d'autre.** Les
  huit services se tiennent en trois points : de 72 % (chirurgie) à 77 % (urgences) de
  séjours ayant au moins un acte, et de 1,55 à 1,64 acte par séjour traité — le détail par
  service est au KPI 2 (§9.4). Même uniformité selon le mode d'admission (74 à 76 %). Un
  plateau technique réel est trois à cinq fois plus sollicité en réanimation ou en chirurgie
  qu'aux urgences. *Artefact probable.*
- **Les types d'actes sont distribués au hasard entre les services** : la cardiologie compte
  231 appendicectomies pour 237 coronarographies, la chirurgie 81 coronarographies, la
  pédiatrie 71 ventilations mécaniques. C'est cliniquement impossible, et c'est précieux :
  la **matrice service × type d'acte** est le premier contrôle de cohérence à écrire sur des
  données réelles — un signalement « acte incompatible avec le service », sur une table de
  compatibilité tenue par le DIM (§22.1). Le générateur a une structure clinique pour les
  diagnostics (§18.1), pas pour les actes. *Artefact probable → futur contrôle.*
- Le rythme suit les admissions : 239 actes par jour la première semaine complète, 306 la
  troisième. Un acte survient en médiane 1,9 jour après l'admission ; 13 % le jour même.

*Sources : `kpi_actes_service`, `fact_acte` ⋈ `fact_sejour`.*

### 21.2 Ce que ça rapporte

| Type d'acte | Tarif | Actes | Montant | Part des recettes |
|---|---:|---:|---:|---:|
| Appendicectomie | 800 € | 978 | 782 400 € | 35,6 % |
| Coronarographie | 450 € | 1 030 | 463 500 € | 21,1 % |
| IRM cérébrale | 300 € | 982 | 294 600 € | 13,4 % |
| Coloscopie totale | 260 € | 1 015 | 263 900 € | 12,0 % |
| Ventilation mécanique assistée | 220 € | 1 000 | 220 000 € | 10,0 % |
| Pose de cathéter central | 120 € | 1 025 | 123 000 € | 5,6 % |
| Radiographie du thorax | 25 € | 1 043 | 26 075 € | 1,2 % |
| Consultation de suivi | 25 € | 1 039 | 25 975 € | 1,2 % |
| **Total** | | **8 112** | **2 199 450 €** | 100 % |

| Service | Montant | Par acte | Par séjour traité | Par lit déclaré |
|---|---:|---:|---:|---:|
| Cardiologie | 521 655 € | 270 € | 430 € | 17 388 € |
| Urgences | 478 585 € | 276 € | 439 € | 23 929 € |
| Neurologie | 393 850 € | 268 € | 429 € | — |
| Pneumologie | 268 045 € | 266 € | 418 € | 9 573 € |
| Pédiatrie | 171 165 € | 286 € | 452 € | 7 780 € |
| Réanimation | 154 740 € | 275 € | 436 € | 9 671 € |
| Chirurgie | 147 145 € | 261 € | 428 € | 3 679 € |
| Oncologie | 64 265 € | 267 € | 415 € | 1 836 € |

*Sources : `kpi_actes_type` ⋈ `dim_ccam`, `kpi_facturation_service`, `kpi_densite_lits`.*

- **Trois actes font 70 % des recettes** — appendicectomie, coronarographie, IRM — et les
  deux actes à 25 € font un quart des actes pour 2,4 % du montant. Sur un mois, 2,2 M€ d'actes,
  soit un ordre de grandeur de 28 M€ par an à activité constante. Une direction financière
  suivrait la structure de ces recettes mois par mois, et un changement de tarif de
  l'appendicectomie pèserait plus que tout le reste : c'est l'argument pour historiser
  `dim_ccam` (§9.5). *Exploitable.*
- **Le classement des services par montant est le classement par activité.** 270 € par acte
  à ± 5 % près, 430 € par séjour traité partout : le KPI 5 ne dit rien de la valorisation d'un
  service, seulement de son volume — conséquence directe de la distribution aléatoire des
  actes (§21.1). Sur des données réelles, la réanimation et la chirurgie domineraient en
  montant par séjour ; ici, l'oncologie et les urgences se valent. *Artefact probable.*
- **Par lit déclaré, l'écart est de 1 à 13** — 23 929 € aux urgences, 1 836 € en oncologie —
  avec la réserve de §18.3 sur les capacités. En relatif, c'est la même image que les lits :
  un plateau saturé aux urgences et en cardiologie, sous-employé en oncologie et en chirurgie.
  *Exploitable, sous réserve du référentiel.*

---

## 22. Synthèse et préconisations

### 22.1 Préconisations

En sept lignes : un établissement d'environ **1 240 patients présents** en croissance de 22 %
en deux semaines, dont trois services portent 63 % de l'activité ; des durées de séjour
dictées par les pathologies et non par les services ; des **lits qui ne sont pas là où sont
les patients** ; une réadmission qui est un problème de **parcours** plutôt que de service ;
une surveillance qui fonctionne mais ne couvre que 42 % des séjours des services équipés ;
une population âgée et polypathologique ; des recettes d'actes qui suivent le volume, trois
actes en faisant 70 %. Ce qu'on en fait :

| # | Préconisation | Pour qui | Fondée sur |
|---|---|---|---|
| 1 | **Faire valider le référentiel de capacité** (191 lits pour 1 240 présents) avant toute décision sur les lits ; en attendant, ne lire la densité d'actes par lit qu'en relatif | DIM, direction | §18.3 |
| 2 | **Rééquilibrer les lits** vers la cardiologie et la réanimation, depuis la chirurgie, l'oncologie et la pédiatrie — cible : un nombre de présents par lit homogène entre services | Direction | §18.3 |
| 3 | **Agir sur la durée en neurologie et en cardiologie** : un jour de DMS en moins libère 43 et 57 lits ; commencer par les séjours au-delà de la médiane | Cadres de santé | §18.1, §18.3 |
| 4 | **Organiser le parcours post-urgences** : consultation à J+7 en cardiologie et en neurologie après un passage aux urgences ; suivi post-opératoire en chirurgie et en pédiatrie | Soins | §19.2 |
| 5 | **Publier la réadmission à 60 jours d'historique**, et trancher avec le DIM le sort des séjours terminés par un décès au dénominateur | DIM | §19.1, §19.2, §7.4 |
| 6 | **Récupérer les sorties manquantes** : 683 séjours « en cours » âgés de 8 jours en moyenne, quatre fois la DMS aux urgences | DIM, DSI | §18.1 |
| 7 | **Corriger les identités** : 136 admissions et 133 réadmissions après un décès enregistré désignent des IPP fusionnés ou un codage de sortie erroné | DIM | §19.1 |
| 8 | **Étendre la surveillance** aux séjours non couverts (58 %) puis à la pneumologie et à la neurologie ; suivre le taux de capteurs en panne par service ; construire l'escalade sur deux constantes | Soins, biomédical | §19.3 |
| 9 | **Ajouter trois contrôles au pipeline** : jour déposé sous la moitié de la médiane (Q11), acte incompatible avec le service (Q12), réadmission après décès (extension de Q7) | Équipe données | §18.2, §21.1, §19.1 |
| 10 | **Recherche** : constituer la cohorte polypathologique (insuffisance cardiaque × diabète × BPCO) ; ne pas exploiter les sex-ratios de l'infarctus, de la BPCO et du cancer bronchique ; accès sur convention pour les maladies rares | Chercheurs, DPO | §20 |
| 11 | **Facturation** : suivre mensuellement la structure des recettes (trois actes = 70 %) et historiser les tarifs avant tout changement de T2A | Direction financière | §21.2, §9.5 |

### 22.2 Ce qu'il faudrait vérifier en premier sur des données réelles

Six signaux de ce jeu ont la signature d'un tirage aléatoire ; sur des données réelles, chacun
est une question à poser à la source avant de publier — et plusieurs sont devenus, ou peuvent
devenir, une règle du rapport qualité (§4) :

| Signal | Ce qu'un CHU réel montrerait | Contrôle |
|---|---|---|
| Mortalité à 16,5 %, uniforme, pédiatrie en tête | 2 à 4 %, concentrée en réanimation et oncologie | Q7 existe ; extension à la réadmission après décès |
| Actes distribués au hasard entre services | Une matrice service × acte creuse | Q12, table de compatibilité |
| Modes d'admission et de sortie identiques partout | Programmé en chirurgie, mutation en sortie de réanimation | Vue existante (`kpi_flux`) : à lire par service |
| Aucune femme pour trois pathologies | 60 à 70 % d'hommes | Contrôle de vraisemblance des sex-ratios |
| Recrutement égal entre huit départements | Un gradient de distance | Sans objet : grain retiré des vues |
| Jamais deux constantes en alerte à la fois | Co-occurrence fièvre / tachycardie | Signal d'escalade à construire |

Le reste — l'activité et sa croissance, le case-mix par service, le besoin relatif en lits,
les trajectoires de réadmission, le bruit de fond des alertes, le profil de la population, la
structure des recettes — se lit comme on lirait un vrai établissement. C'est pour cela que
l'entrepôt existe : chacun de ces chiffres se retrouve en une requête sur une table nommée,
et le prochain dépôt du CHU les mettra à jour sans qu'on y touche.

---

*Énoncé de l'épreuve : [`sujets/FICHE-SUJET.md`](sujets/FICHE-SUJET.md) · Consigne d'évolution :
[`sujets/SUJET-EVOLUTION-nouvelles-kpi.md`](sujets/SUJET-EVOLUTION-nouvelles-kpi.md) · Mise en service et exploitation :
[`README`](../README.md) · Infrastructure Azure : [`terraform/README.md`](../terraform/README.md)*
