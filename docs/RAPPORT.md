# Entrepôt de Données de Santé du CHU — dossier de conception

**M2 Big Data · épreuve E05** — Partie 1 : analyse, architecture et restitution.

---

## Sommaire

1. [Contexte et analyse du besoin](#1-contexte-et-analyse-du-besoin)
2. [Les données sources](#2-les-données-sources)
3. [Architecture](#3-architecture)
4. [Traitements et qualité](#4-traitements-et-qualité)
5. [Les indicateurs](#5-les-indicateurs)
6. [Restitution et cloisonnement](#6-restitution-et-cloisonnement)
7. [Gouvernance RGPD](#7-gouvernance-rgpd)
8. [Limites et recommandations](#8-limites-et-recommandations)

---

## 1. Contexte et analyse du besoin

### 1.1 Le problème posé

Le CHU dispose de données réparties dans quatre systèmes distincts — dossier patient,
urgences, laboratoire, monitoring des chambres — qui n'exportent ni dans le même format ni
avec les mêmes conventions. Chaque jour, ces systèmes déposent leurs fichiers dans un
espace commun. En l'état, répondre à une question aussi simple que « quelle est notre durée
moyenne de séjour en cardiologie ? » suppose d'ouvrir plusieurs fichiers, de les rapprocher
à la main et d'espérer que personne n'a introduit d'incohérence.

La direction veut deux choses de cet entrepôt, et elles ne se ressemblent pas :

- **Le pilotage hospitalier** a besoin de suivre l'activité au jour le jour : combien de
  passages aux urgences, combien de temps les patients restent, combien reviennent après
  leur sortie, combien d'alertes sur les constantes. Ce sont des chiffres d'exploitation,
  qui doivent être justes et disponibles rapidement.
- **La recherche clinique** a besoin de constituer des cohortes : combien de patients pour
  telle pathologie, quel âge, quel sexe. Ce sont des chiffres d'étude, qui doivent être
  comparables dans le temps et surtout **anonymes**.

### 1.2 Ce que cette différence implique

Ces deux usages n'ont pas besoin des mêmes données, et c'est ce qui structure toute
l'architecture. Le pilotage travaille sur l'activité : les séjours, les services, les
constantes. La recherche travaille sur des populations : des effectifs, des tranches d'âge,
jamais un patient identifiable.

Nous en avons tiré une décision de conception : **deux bases distinctes en sortie**, avec
deux comptes de lecture séparés. Ce n'est pas un raffinement cosmétique — c'est ce qui
permet de garantir qu'un chercheur ne peut pas, même par accident, remonter à un séjour
individuel, et qu'un cadre de santé ne consulte pas de données d'étude.

### 1.3 La contrainte RGPD

Les données de santé relèvent de l'article 9 du RGPD : leur traitement est interdit par
principe, sauf exceptions encadrées. Concrètement, cela impose quatre obligations que nous
avons traitées comme des contraintes de conception, pas comme une couche ajoutée à la fin :

| Obligation | Traduction technique retenue |
|---|---|
| Pseudonymisation | L'identité est remplacée par un pseudonyme **avant** toute écriture dans notre zone de travail |
| Minimisation | Une donnée qui ne sert aucun indicateur n'est pas conservée |
| Cloisonnement | Les droits d'accès sont portés par le moteur de base de données, pas seulement par l'outil de visualisation |
| Petits effectifs | Une cohorte de moins de cinq patients n'est jamais diffusée |

Le fichier `patients.csv` arrive avec le NIR, le nom, le prénom et la date de naissance
complète. Ces quatre colonnes sont, chacune, directement ou quasi-identifiantes. Notre
première décision a été de faire en sorte qu'elles ne franchissent jamais la porte de
l'entrepôt.

---

## 2. Les données sources

### 2.1 Ce que le CHU dépose

Trois jours de dépôt nous ont été fournis (26, 27 et 28 août 2026), organisés par domaine
puis par jour. Nous avons commencé par profiler l'intégralité de ces fichiers avant
d'écrire la moindre ligne de code : c'est ce profilage qui a révélé les pièges décrits
ci-dessous, et qui a dimensionné les règles de qualité.

| Fichier | Format | Volume | Contenu |
|---|---|---|---|
| `patients.csv` | CSV | 16 200 lignes | ⚠ Identité en clair : IPP, NIR, nom, prénom, date de naissance, sexe, département |
| `sejours.csv` | CSV | 15 000 lignes | Un passage à l'hôpital : dates d'admission et de sortie, service, modes d'entrée et de sortie |
| `diagnostics.json` | JSON imbriqué | 37 380 codes | Un ou plusieurs codes CIM-10 par séjour, avec leur type (principal ou associé) |
| `monitoring.parquet` | Parquet | 66 677 lignes | Constantes au chevet : fréquence cardiaque, saturation, température |
| `services.csv`, `cim10.csv` | CSV | 8 et 10 lignes | Nomenclatures : code → libellé |

Le monitoring est le flux qui dicte les choix techniques : sur trois jours il représente
déjà plus de lignes que tout le reste réuni, et en production il croîtrait linéairement
avec le nombre de lits équipés.

> **CIM-10** — Classification Internationale des Maladies, 10ᵉ révision. C'est la
> nomenclature de l'OMS utilisée pour coder les diagnostics : `I21` désigne l'infarctus du
> myocarde, `C34` un cancer du poumon. La lettre porte le chapitre (I pour cardiovasculaire,
> C pour tumeurs, J pour respiratoire…), les chiffres précisent la pathologie.

### 2.2 Ce que le profilage a révélé

Cinq observations ont directement orienté la conception.

**Les fichiers patients sont cumulatifs.** Le CHU ne dépose pas les nouveaux patients du
jour : il redépose l'intégralité de sa base. On passe de 4 800 lignes le premier jour à
5 400 puis 6 000, chaque fichier contenant tous les patients des jours précédents. Au total
16 200 lignes pour 6 000 patients réels. Sans déduplication, chaque patient serait compté
deux ou trois fois dans les cohortes.

**Les identifiants de séjour ne se recoupent pas d'un jour à l'autre.** Chaque fichier
apporte 5 000 séjours nouveaux. L'ingestion peut donc être strictement incrémentale.

**Le monitoring déborde de son jour de dépôt.** Le fichier du 26 août contient des relevés
allant jusqu'au 28. Ce n'est pas une erreur — ce sont les constantes futures des séjours
ouverts ce jour-là — et surtout ce ne sont pas des doublons : aucune paire
(séjour, horodatage) n'apparaît deux fois. Le partitionnement par jour de dépôt reste donc
valide.

**Seuls deux services sont monitorés.** Réanimation et cardiologie, soit 1 506 séjours sur
15 000, avec un relevé toutes les trente minutes. Tout indicateur bâti sur le monitoring ne
concerne que ces deux services, et il faut le dire explicitement pour éviter une lecture
faussée.

**Les anomalies suivent des motifs identifiables.** Les valeurs aberrantes de constantes ne
sont pas dispersées : la fréquence cardiaque et la saturation deviennent aberrantes
**ensemble, sur les mêmes lignes**, avec des valeurs extrêmes franches (0 ou 500 bpm, 0 ou
120 %). C'est la signature d'une panne de capteur, pas d'un patient en détresse. La
température, elle, reste toujours plausible.

---

## 3. Architecture

### 3.1 Vue d'ensemble

L'architecture suit le patron médaillon, avec une couche de collecte supplémentaire qui
porte la pseudonymisation :

```
source-filestorage  →  lake  →  bronze  →  silver  →  gold  →  Metabase
  (lecture seule)      (copie    (tables    (faits &   (KPI par   (dashboards
                   pseudonymisée) typées)  dimensions)  usage)     cloisonnés)
```

Le modèle de données complet est en annexe : [`docs/img/eds-data-model.png`](img/eds-data-model.png).

### 3.2 Justification des choix

| Décision | Choix retenu | Pourquoi |
|---|---|---|
| **Entrepôt** | ClickHouse | Base orientée colonnes, donc taillée pour l'analytique sur le flux de monitoring. Elle sait lire directement des fichiers CSV, JSON et Parquet, dispose d'une gestion fine des droits, et son SQL couvre nos besoins (fonctions de fenêtrage, `argMax`, agrégats conditionnels). |
| **Chargement** | Le moteur lit les fichiers lui-même | Le lake est monté dans le conteneur ClickHouse ; les fichiers sont chargés par la fonction `file()`. Aucune donnée ne transite par la mémoire de Python. C'est la différence entre un pipeline qui tient la charge et un script qui s'effondre dès que le monitoring grossit. |
| **Transformations** | SQL versionné dans `sql/` | Chaque règle métier est un fichier lisible, exécuté par le moteur. Python n'orchestre que l'ordre. Faire remonter les données côté client pour les transformer en mémoire serait l'anti-pattern classique : cela ne passe pas à l'échelle et rend les calculs impossibles à auditer. |
| **Modélisation silver** | Constellation Kimball | Trois tables de faits — séjour, diagnostic, monitoring — au **grain déclaré**, chacune formant sa propre étoile avec ses dimensions directes. Les dimensions patient, service et CIM-10 sont **conformées**, donc partagées : les deux usages comptent les mêmes patients. Aucune jointure entre deux tables de faits n'est nécessaire, ce qui est précisément l'objectif du modèle dimensionnel. |
| **Incrémentalité** | Partitionnement par jour + journal d'ingestion | Rejouer un jour revient à supprimer sa partition puis à la recharger. Le journal, indexé par empreinte du fichier source, permet de sauter ce qui n'a pas changé et de reprendre ce qui a échoué. |
| **Silver et gold** | Reconstruites à chaque exécution | À ce volume, la reconstruction complète prend moins d'une seconde. On y gagne un déterminisme total : le même bronze produit toujours exactement les mêmes indicateurs. |
| **Cloisonnement** | Deux comptes SQL distincts | La séparation est portée par le moteur. Un utilisateur « recherche » qui écrirait une requête SQL à la main dans Metabase se verrait refuser l'accès par ClickHouse — pas seulement masquer le lien dans l'interface. |
| **Restitution** | Metabase, provisionné par API | Dashboards sans code pour les utilisateurs, mais définis en Python et versionnés côté projet : après un clone, tout se recrée sans un seul clic. |
| **Orchestration** | Interface en ligne de commande + cron | Simple, testable, sans dépendance lourde. La montée vers un ordonnanceur dédié est décrite en §8. |

### 3.3 Pourquoi une constellation plutôt qu'une seule étoile

Le premier réflexe serait de faire du séjour la table centrale et d'y rattacher tout le
reste. Nous ne l'avons pas fait, pour une raison précise : chaque besoin métier interroge
un grain différent.

- « Quelle est la DMS par service ? » se compte **par séjour**.
- « Combien de relevés en alerte hier ? » se compte **par relevé**.
- « Combien de patients atteints de BPCO ? » se compte **par diagnostic**.

Chacun de ces faits porte donc directement les clés des dimensions dont il a besoin. Le
code du service est recopié dans la table des relevés au moment de la construction, et le
pseudonyme du patient dans la table des diagnostics. Cette propagation coûte un peu
d'espace et évite systématiquement les jointures entre tables de faits — qui, sur des grains
différents, produisent des comptages faux dès qu'on agrège.

L'identifiant de séjour reste présent dans les trois faits en **dimension dégénérée** : il
n'a pas de table à lui, mais il permet de relier les étoiles quand une analyse transversale
le demande.

### 3.4 Volumétrie et passage à l'échelle

Sur les trois jours fournis, le pipeline complet s'exécute en quelques secondes. Ce qui
compte davantage, c'est ce qui se passerait en production :

- Le monitoring croît linéairement avec le nombre de lits équipés. Une base orientée
  colonnes le compresse très efficacement (les constantes varient peu d'un relevé au
  suivant) et n'en lit que les colonnes utiles lors d'une agrégation.
- Le partitionnement par jour permet de ne toucher qu'un jour à la fois, aussi bien pour
  l'ingestion que pour une éventuelle purge.
- La reconstruction complète de silver et gold devrait, elle, passer à un traitement
  incrémental si le volume l'exigeait — c'est le principal point d'évolution identifié.

---

## 4. Traitements et qualité

### 4.1 La pseudonymisation, à l'entrée du lake

C'est le traitement le plus important du projet, et il intervient au tout premier moment
utile : pendant la copie depuis le dépôt du CHU.

```python
def pseudonymize_id(patient_id: str, salt: str) -> str:
    digest = hmac.new(salt.encode(), patient_id.encode(), hashlib.sha256).hexdigest()
    return f"P{digest[:16]}"
```

Trois propriétés justifient ce choix :

- **HMAC plutôt qu'un hachage simple.** Un `sha256(sel + identifiant)` naïf est vulnérable
  aux attaques par extension de longueur ; HMAC est la construction standard pour
  authentifier une valeur avec une clé.
- **Déterministe.** Le même IPP produit toujours le même pseudonyme, ce qui préserve les
  jointures entre patients et séjours, y compris entre deux jours d'ingestion différents.
- **Non réversible sans le sel.** Le sel vit dans un fichier non versionné et n'apparaît
  jamais dans les journaux. Le pipeline refuse de démarrer si ce sel est absent ou trop
  court : mieux vaut ne rien ingérer qu'ingérer avec une protection faible.

Dans le même mouvement, le NIR, le nom et le prénom **ne sont simplement jamais écrits**,
et la date de naissance est réduite à l'année. À la sortie de cette étape, le fichier
`patients.csv` du lake contient quatre colonnes : pseudonyme, année de naissance, sexe,
département.

### 4.2 Les règles de qualité

Le principe est simple et constant : **on écarte, on trace, on ne corrige jamais en
silence.** Toute ligne rejetée part dans une table dédiée avec son motif, et reste
consultable.

Trois natures de règles cohabitent, et les confondre rendrait le rapport illisible :

- **Rejet** — la ligne quitte l'entrepôt et se retrouve dans une table `*_rejets` ;
- **Signalement** — la ligne est **conservée** mais marquée, parce qu'elle est légitime ou
  parce que l'anomalie relève de la source ;
- **Contrôle** — vérification attendue à zéro, dont le passage au vert est l'information.

Les chiffres ci-dessous sont ceux de la dernière exécution ; ils sont recalculés à chaque
run dans `ops.quality_report`.

| Règle | Nature | Lues | Conservées | Écartées | Signalées |
|---|---|---:|---:|---:|---:|
| **Q1** Patients redéposés chaque jour | Déduplication | 16 200 | 6 000 | 10 200 | — |
| **Q2** Sortie antérieure à l'admission | Rejet | 15 000 | 14 864 | 136 | — |
| **Q4** Constantes hors plage physiologique | Rejet | 66 677 | 64 799 | 1 369 | — |
| **C1** Relevé dont le séjour est écarté | Rejet en cascade | 66 677 | 64 799 | 520 | — |
| **C2** Diagnostic dont le séjour est écarté | Rejet en cascade | 37 380 | 37 040 | 340 | — |
| **Q3** Séjour sans date de sortie | Signalement | 14 864 | 14 864 | 0 | 1 190 |
| **Q5** Mode de sortie non renseigné | Signalement | 14 864 | 14 864 | 0 | 3 165 |
| **Q7** Admission après un décès antérieur | Signalement | 14 864 | 14 864 | 0 | 192 |
| **Q8** Relevé postérieur à la sortie | Contrôle | 64 799 | 64 799 | 0 | **0** |
| **Q6** Formats et intégrité référentielle (5 règles) | Contrôle | — | — | 0 | **0** |

Les deux règles de rejet du monitoring se recoupent partiellement. Comme chaque ligne
écartée porte **tous** ses motifs, concaténés, le recoupement se vérifie directement :

| Motif de rejet | Lignes |
|---|---:|
| `hr_out_of_range+spo2_out_of_range` | 1 358 |
| `parent_stay_rejected` | 509 |
| `hr_out_of_range+spo2_out_of_range+parent_stay_rejected` | 11 |
| **Total écarté** | **1 878** |

Soit 1 369 relevés hors plage (1 358 + 11) et 520 en cascade (509 + 11), pour **64 799
relevés conservés** sur 66 677.

Ce tableau confirme aussi l'hypothèse formulée au profilage : **la fréquence cardiaque et
la saturation sont toujours aberrantes ensemble**, jamais l'une sans l'autre, et la
température ne l'est jamais. C'est la signature d'un capteur défaillant, non d'un patient
en détresse — ce qui justifie de les écarter plutôt que de les traiter comme des alertes.

Quelques décisions méritent d'être explicitées.

**Une sortie non renseignée n'est pas une anomalie.** C'est un patient encore hospitalisé.
Le sujet le signalait, et le profilage le confirme : 1 190 séjours sont dans ce cas. Ils
sont conservés, marqués comme en cours, et exclus du seul calcul où ils fausseraient le
résultat — la durée moyenne de séjour.

**Les cascades sont nécessaires, pas cosmétiques.** Un relevé de constantes dont le séjour
parent a été écarté ne peut pas recevoir son code de service, puisque ce code vient du
séjour. Le conserver produirait une ligne inexploitable. Il part donc en rejet, avec le
motif `parent_stay_rejected`.

**Une découverte du profilage vaut d'être signalée.** Nous avions relevé 520 relevés de
constantes horodatés après la sortie du patient, et prévu de les signaler comme anomalie.
Après implémentation, ce compteur est tombé à zéro — et l'explication est instructive : ces
520 relevés appartenaient **tous** aux 136 séjours dont la date de sortie précède
l'admission. Une sortie antérieure à l'admission rend mécaniquement tout relevé
« postérieur à la sortie ». L'anomalie Q8 n'était donc qu'un symptôme de Q2. Nous avons
conservé le contrôle, désormais attendu à zéro : c'est son passage au vert qui a de la
valeur.

**Un cas a été délibérément écarté du rejet.** Le profilage montre que 8 362 séjours
chevauchent le séjour précédent du même patient. Sur des données réelles, ce serait une
incohérence majeure. Ici, cela concerne plus de la moitié des séjours : il s'agit d'un
artefact du jeu synthétique. Les rejeter viderait l'entrepôt. Nous les conservons, et nous
le documentons — mais cet artefact a une conséquence directe sur un indicateur, décrite
en §5.3.

### 4.3 Traçabilité

Chaque ligne de bronze et de silver — les huit tables, dimensions comprises — porte trois
colonnes de lignage : le fichier dont elle provient, le jour de dépôt correspondant, et
l'horodatage de son traitement. Les tables gold, qui sont des agrégats, n'ont pas de ligne
individuelle à tracer : elles se rattachent à leur exécution par `ops.quality_report`.

Chaque exécution du pipeline est enregistrée avec son identifiant, son statut et les jours
traités ; `ops.ingest_log` relie chaque fichier au run qui l'a chargé. Chaque règle de
qualité produit un comptage.

Concrètement, cela permet de répondre à « d'où sort ce 14 864 ? » sans ouvrir un seul
fichier : le tableau de bord de pilotage affiche le rapport qualité, et le journal
d'ingestion indique quel fichier a fourni combien de lignes.

---

## 5. Les indicateurs

Chaque indicateur est calculé dans l'entrepôt et exposé sous forme de table agrégée. Les
requêtes des tableaux de bord se réduisent à des `SELECT` simples : aucun calcul métier
n'est enfoui dans l'outil de visualisation, et tout chiffre affiché est reproductible en SQL.

### 5.1 Durée moyenne de séjour

**Définition.** Moyenne, par service et par jour de sortie, de la durée écoulée entre
l'admission et la sortie, exprimée en jours.

**Hypothèse assumée : seuls les séjours terminés entrent dans le calcul.** Un patient encore
hospitalisé a une durée partielle par construction ; l'inclure tirerait la moyenne vers le
bas et donnerait l'illusion d'une amélioration de la performance. Les 1 190 séjours en cours
sont donc exclus du numérateur comme du dénominateur.

**Résultat.** DMS globale de **6,08 jours**, très homogène entre services (de 6,01 en
cardiologie à 6,23 aux urgences).

### 5.2 Activité des urgences

Cet indicateur a la particularité d'admettre **deux définitions légitimes**, qui ne donnent
pas le même chiffre :

- le nombre de séjours **dont le service est URGENCES** (unité d'hospitalisation) ;
- le nombre d'admissions **en mode urgence**, tous services confondus (mode d'entrée).

Sur ces données, la seconde est environ 2,7 fois supérieure à la première : beaucoup de
patients entrent en urgence directement dans un service spécialisé. Plutôt que de trancher
à la place du métier, nous exposons **les deux côte à côte** sur le même graphique. C'est
le type d'ambiguïté qui, laissée implicite, produit deux services qui ne parlent pas des
mêmes chiffres.

### 5.3 Taux de réadmission à 30 jours

C'est l'indicateur qui a demandé le plus de soin, et celui où une définition naïve donne un
résultat faux.

**Définition retenue.** Un séjour est suivi d'une réadmission s'il existe, pour le même
patient, **une** admission postérieure à sa sortie et survenant dans les trente jours.
Dénominateur : les sorties vivantes uniquement — un patient décédé ne peut pas être
réadmis, et l'inclure minorerait artificiellement le taux.

**Le piège.** Notre première implémentation regardait l'admission chronologiquement
suivante, via une fonction de fenêtrage. Sur des données normales, cela revient au même.
Ici, avec 8 362 séjours qui se chevauchent (§4.2), l'admission « suivante » est très souvent
un séjour concurrent commencé **avant** la sortie considérée — et elle masquait alors la
réadmission réelle survenue plus tard. Le comptage passait de 687 à 370, soit près de la
moitié des réadmissions perdues.

Nous avons donc changé de logique : plutôt que la seule admission suivante, on teste
**l'ensemble des admissions du patient**. C'est aussi la définition cliniquement correcte.

**Résultat.** **687 réadmissions sur 11 678 sorties éligibles, soit 5,9 %.** Par service, le
taux varie de 4,78 % en chirurgie à 6,69 % en neurologie.

### 5.4 Surveillance des constantes

**Seuils retenus** — ce sont des hypothèses de travail, à valider avec les équipes
soignantes avant tout usage réel :

| Constante | Seuil d'alerte | Motif clinique |
|---|---|---|
| Fréquence cardiaque | < 40 ou > 130 bpm | Bradycardie ou tachycardie |
| Saturation en oxygène | < 90 % | Désaturation |
| Température | ≥ 38,5 °C | Fièvre |

**À distinguer des rejets de qualité.** Une valeur à 500 bpm n'est pas une alerte clinique :
c'est un capteur en panne, et elle est écartée en amont (règle Q4). Les alertes ne portent
que sur des mesures physiologiquement plausibles.

**Résultat.** **3 053 relevés en alerte sur 64 799**, soit 4,7 %. Ne concerne que la
réanimation et la cardiologie, seuls services équipés.

### 5.5 Cohortes et prévalence

**Taille de cohorte.** Nombre de **patients distincts** — et non de séjours — portant un
diagnostic donné. Un patient hospitalisé trois fois pour la même pathologie compte une fois.

**Prévalence.** Part des patients de l'entrepôt concernés par la pathologie. Le dénominateur
(5 358 patients ayant au moins un séjour) est calculé comme un agrégat indépendant, jamais
par jointure entre deux tables de faits.

**Description démographique.** Croisement pathologie × sexe × tranche d'âge de dix ans.
L'âge est calculé à partir de la seule année de naissance disponible : c'est une
approximation d'un an au plus, conséquence directe et assumée de la minimisation.

Toutes ces tables appliquent le seuil de diffusion décrit en §7.

---

## 6. Restitution et cloisonnement

### 6.1 Deux tableaux de bord, deux publics

**🏥 Pilotage hospitalier** ouvre sur cinq chiffres clés — séjours pris en charge, DMS, taux
de réadmission, part de relevés en alerte, séjours en cours — puis décline l'activité :
DMS par service, activité des urgences dans ses deux acceptions, réadmissions par service,
alertes de constantes dans le temps et par nature, flux d'entrée et de sortie, charge
quotidienne par service.

Deux blocs le distinguent d'un tableau de bord ordinaire : le **rapport qualité** du dernier
traitement et le **journal d'ingestion**. Un utilisateur qui doute d'un chiffre peut voir,
sans quitter l'interface, combien de lignes ont été écartées et par quelle règle.

![Tableau de bord de pilotage](img/dashboard-pilotage.jpg)

Le bas du tableau de bord porte cette traçabilité, accessible sans quitter l'interface et
sans accès à la base d'exploitation :

![Rapport qualité et journal d'ingestion](img/rapport-qualite-dashboard.jpg)

**🔬 Recherche clinique** présente les tailles de cohortes, la prévalence par pathologie, la
distribution par âge et sexe, et le détail par département. Un encart explique le seuil de
diffusion, et un compteur affiche son effet réel.

![Tableau de bord de recherche](img/dashboard-recherche.jpg)

### 6.2 Le cloisonnement, à trois niveaux

| Niveau | Mécanisme | Effet |
|---|---|---|
| **Base de données** | Deux comptes SQL, chacun avec le seul droit de lecture sur sa base gold | Un accès hors périmètre est refusé **par le moteur** |
| **Connexions Metabase** | Une connexion par usage, utilisant le compte SQL correspondant | Aucune requête ne peut viser l'autre base |
| **Contenu Metabase** | Une collection par usage, visible du seul groupe concerné | Chaque utilisateur ne voit que son tableau de bord |

Le niveau qui compte est le premier. Les deux autres organisent l'interface ; celui-là
oppose un refus même à une requête SQL écrite à la main.

**Démonstration.** Connecté en `pilotage@chu.local`, l'accès direct à l'URL du tableau de
bord de recherche est refusé — et réciproquement :

![Accès refusé hors périmètre](img/cloisonnement-acces-refuse.jpg)

Côté moteur, la commande `uv run eds check-cloisonnement` vérifie les cinq scénarios
d'accès et confirme que chaque compte est bien confiné :

```
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Compte        ┃ Base cible         ┃ Attendu ┃ Résultat  ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ chu_pilotage  │ eds_gold_pilotage  │ lecture │ ✓ lecture │
│ chu_pilotage  │ eds_gold_recherche │ refus   │ ✓ refusé  │
│ chu_recherche │ eds_gold_recherche │ lecture │ ✓ lecture │
│ chu_recherche │ eds_gold_pilotage  │ refus   │ ✓ refusé  │
│ chu_recherche │ eds_silver         │ refus   │ ✓ refusé  │
└───────────────┴────────────────────┴─────────┴───────────┘
```

Ni l'un ni l'autre n'a accès aux couches bronze, silver ou d'exploitation : celles-ci
restent réservées au compte technique du pipeline.

---

## 7. Gouvernance RGPD

### 7.1 Minimisation, colonne par colonne

| Donnée source | Devenir | Justification |
|---|---|---|
| `nir` | **Supprimée** | Identifiant national direct, aucun usage analytique |
| `nom`, `prenom` | **Supprimées** | Identifiants directs |
| `patient_id` (IPP) | **Pseudonymisé** | Nécessaire aux jointures, jamais à l'identification |
| `birth_date` | **Réduite à l'année** | L'année suffit aux tranches d'âge ; jour et mois sont des quasi-identifiants inutiles |
| `sex`, `region_code` | Conservés | Requis par la description de cohorte |

La minimisation s'applique aussi **à l'intérieur** de l'entrepôt : la table des constantes
ne porte pas de pseudonyme patient. Aucun indicateur n'en a besoin — les alertes se comptent
par jour et par service — donc la donnée ne descend pas jusque-là.

### 7.2 Protection des petits effectifs

Toute table diffusée à la recherche applique `HAVING uniqExact(patient_pseudo) >= 5` sur
chaque cellule, et les âges sont publiés en tranches de dix ans.

Cette règle ne doit pas rester théorique. Aux grains courants (pathologie, ou pathologie ×
sexe × âge), les cohortes de ce jeu de données comptent plusieurs centaines de patients :
aucune cellule ne tombe sous le seuil, et le mécanisme resterait invisible. Nous avons donc
ajouté une vue au grain le plus fin — **pathologie × sexe × tranche d'âge × département** —
où la règle mord réellement :

| Cellules calculées | Cellules diffusées | Cellules supprimées | Seuil |
|---:|---:|---:|---:|
| 1 600 | 1 596 | **4** | 5 |

Ces quatre cellules, qui regroupaient chacune moins de cinq patients, n'apparaissent nulle
part dans la restitution. Le compteur est recalculé et affiché à chaque exécution.

### 7.3 Contrôles automatiques

Trois vérifications tournent à chaque run et échoueraient bruyamment en cas de régression :

- aucune colonne nommée `nir`, `nom`, `prenom`, `birth_date` ou `patient_id` dans une base
  de l'entrepôt ;
- aucun pseudonyme individuel exposé dans la base de recherche ;
- aucune cellule diffusée sous le seuil de cinq patients.

Ces contrôles sont doublés de tests d'intégration exécutables par `make test-e2e`.

### 7.4 Registre des hypothèses

Ce que nous avons décidé sans que le sujet le tranche, et qu'il faudrait valider avec le
métier :

1. Les seuils d'alerte des constantes (§5.4).
2. L'exclusion des patients décédés du dénominateur des réadmissions.
3. L'exclusion des séjours en cours du calcul de la DMS.
4. Le maintien des séjours qui se chevauchent, jugés artefacts du jeu de données.
5. Le seuil k = 5, retenu d'après l'énoncé ; certaines autorités recommandent un seuil plus
   élevé selon la sensibilité des données.

---

## 8. Limites et recommandations

### 8.1 Limites tenant aux données

**Les données sont synthétiques, et cela se voit.** Les séjours qui se chevauchent (plus de
la moitié) et les 192 admissions postérieures à un décès du même patient sont impossibles
en réalité. Nous les avons conservés — les rejeter viderait l'entrepôt — mais ils rendent
certains indicateurs peu interprétables cliniquement. Le taux de réadmission, en
particulier, est correct au sens de sa définition mais reposerait sur des données
incohérentes en production.

**Trois jours de profondeur, pour un indicateur à trente jours.** Le taux de réadmission à
30 jours ne peut pas être complet sur une fenêtre de trois jours : les réadmissions
survenant après la fin de la période ne sont pas observables. Le chiffre publié est donc
une borne inférieure.

**Le monitoring ne couvre que deux services.** Tout indicateur bâti dessus est
structurellement partiel, ce que les tableaux de bord signalent explicitement.

### 8.2 Limites techniques

| Point | État actuel | Recommandation |
|---|---|---|
| Base applicative de Metabase | H2 embarqué | PostgreSQL en production : H2 ne supporte ni la sauvegarde à chaud ni la montée en charge |
| Secrets | Fichier `.env` local | Coffre-fort (Vault, gestionnaire de secrets du cloud), avec rotation tracée |
| Ordonnancement | cron | Airflow ou Dagster dès que les dépendances entre traitements se complexifient : reprise fine, historique, alerting intégré |
| Reconstruction silver et gold | Intégrale à chaque run | Traitement incrémental (moteur `ReplacingMergeTree`) si le volume devient conséquent |
| Blocage des données dans Metabase | Restriction du droit de requête | Le blocage complet est réservé aux éditions payantes ; ici c'est ClickHouse qui porte l'interdiction réelle, ce qui suffit |
| Ingestion du monitoring | Par fichier quotidien | Ingestion en continu si le CHU passe à un flux temps réel |

### 8.3 Recommandations de gouvernance

**Le sel de pseudonymisation ne peut pas être changé à la légère.** Le modifier invalide
tous les pseudonymes existants et casse les jointures. Une rotation suppose de re-collecter
et de reconstruire l'intégralité de l'entrepôt depuis le dépôt du CHU. La procédure est
décrite dans le document d'exploitation ; elle doit être considérée comme une opération
exceptionnelle.

**Prévoir une durée de conservation.** Le sujet ne l'aborde pas, mais un entrepôt de santé
doit définir une durée au-delà de laquelle les données sont purgées ou archivées. Le
partitionnement par jour rend cette purge triviale à mettre en œuvre.

**Associer le délégué à la protection des données.** La pseudonymisation ne rend pas les
données anonymes au sens du RGPD : elles restent des données personnelles, et leur
traitement suppose une base légale, une analyse d'impact et une inscription au registre.

**Documenter les définitions auprès du métier.** Le cas de l'activité des urgences (§5.2)
montre qu'un même mot recouvre deux chiffres différents. Un glossaire partagé, adossé aux
définitions SQL, éviterait les désaccords ultérieurs.

---

## Annexes

- [Modèle de données détaillé](img/eds-data-model.png)
- [Documentation d'exploitation](EXPLOITATION.md)
- [Plan d'implémentation et profilage complet](../PLAN.md)
