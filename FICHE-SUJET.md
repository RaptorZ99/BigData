# Entrepôt de Données de Santé (EDS)

**MODULE BIG DATA · M2 · ÉPREUVE E05**

*Cas métier — Centre Hospitalier Universitaire (CHU)*

> `Projet fil rouge de la semaine` · `Données fournies : source-filestorage/` · `Livrables : Partie 1 + Partie 2`

---

## 1. Contexte

Le **CHU** souhaite se doter d'un **Entrepôt de Données de Santé (EDS)**. Ses données sont aujourd'hui éparpillées dans plusieurs systèmes (dossier patient, urgences, laboratoire, monitoring des chambres) et exportées **chaque jour** sous forme de fichiers, dans des formats différents. La direction veut en tirer deux usages : **le pilotage hospitalier** et **la recherche clinique**.

> ⚠ **Données de santé — catégorie particulière (RGPD, art. 9)**
> La conformité n'est pas une option : c'est une **contrainte de conception** présente à chaque étape de votre chaîne de traitement.

---

## 2. Votre mission

| # | Mission | Description |
|---|---------|-------------|
| **1** | **Récupérer** | Automatiser la collecte des fichiers déposés chaque jour. |
| **2** | **Fiabiliser** | Structurer des données hétérogènes en informations exploitables. |
| **3** | **Restituer** | Produire des indicateurs via des dashboards. |
| **4** | **Automatiser** | Rejouer le traitement seul, de façon fiable et tracée. |

---

## 3. Les données fournies

Le CHU **dépose chaque jour** ses fichiers dans un espace de stockage (le *filestorage*). Vous disposez de **plusieurs jours** de dépôt. Les formats sont **volontairement mélangés** — c'est la réalité d'un hôpital.

```
source-filestorage/
├── patients/<AAAA-MM-JJ>/patients.csv                CSV
├── sejours/<AAAA-MM-JJ>/sejours.csv                  CSV
├── diagnostics/<AAAA-MM-JJ>/diagnostics.json         JSON
├── monitoring/<AAAA-MM-JJ>/monitoring.parquet        Parquet · volumineux
└── referentiels/<AAAA-MM-JJ>/{services,cim10}.csv    CSV
```

> **Accès en lecture seule**
> Vous ne pouvez que **lire** ce que le CHU dépose. À vous de recopier ces fichiers vers votre propre zone de travail avant de les traiter.

### Dictionnaire de données

#### `patients.csv` — CSV

> ⚠ **Contient l'identité RÉELLE des patients**

| COLONNE | TYPE | DESCRIPTION |
|---------|------|-------------|
| `patient_id` | texte | **IPP** — identifiant interne (en clair). Clé de jointure avec `sejours` |
| `nir` | texte | ⚠ **N° sécurité sociale** — directement identifiant |
| `nom` | texte | ⚠ **Nom** — directement identifiant |
| `prenom` | texte | ⚠ **Prénom** — directement identifiant |
| `birth_date` | date | Date de naissance **complète** |
| `sex` | texte | Sexe (`M` / `F`) |
| `region_code` | texte | Département de résidence |

*Ces identifiants ne doivent **jamais** entrer dans l'entrepôt : à anonymiser dès l'entrée du lake (cf. § 5 et § 7).*

#### `sejours.csv` — CSV

*Un séjour = un passage à l'hôpital*

| COLONNE | TYPE | DESCRIPTION |
|---------|------|-------------|
| `stay_id` | texte | Identifiant du séjour |
| `patient_id` | texte | Référence au patient |
| `service_code` | texte | Service d'hospitalisation (cf. référentiel) |
| `admission_ts` | horodatage | Date/heure d'admission |
| `discharge_ts` | horodatage | Date/heure de sortie — peut être vide (séjour en cours) |
| `admission_mode` | texte | `urgence`, `programme`, `mutation` |
| `discharge_mode` | texte | `domicile`, `mutation`, `transfert`, `deces`… |

#### `diagnostics.json` — JSON

Structure imbriquée : un ou plusieurs codes par séjour.

```json
[
  {
    "stay_id": "S00000123",
    "diagnostics": [
      { "code_cim10": "...", "type": "principal" },
      { "code_cim10": "...", "type": "associe" }
    ]
  }
]
```

#### `monitoring.parquet` — Parquet

*Flux volumineux (constantes au chevet)*

| COLONNE | TYPE |
|---------|------|
| `stay_id` | texte |
| `ts` | horodatage |
| `heart_rate` | entier (bpm) |
| `spo2` | entier (%) |
| `temp_c` | décimal (°C) |

#### `referentiels/` — `services.csv` · `cim10.csv` — CSV

Nomenclatures, déposées le premier jour.

- **services** : code → libellé du service
- **cim10** : code diagnostic → libellé

> ⚠ **Les données brutes reflètent la vraie vie**
> Elles ne sont pas forcément propres ni cohérentes. Une partie du travail consiste précisément à détecter et traiter les problèmes de qualité (voir ci-dessous).

### Contrôles qualité attendus (indicatifs)

Vous n'êtes pas médecins : on vous donne les règles métier et les catégories de contrôles. À vous de les implémenter (couche silver), de tracer ce que vous écartez, et d'en repérer d'autres en explorant.

| DOMAINE | CONTRÔLE ATTENDU | RÈGLE / BORNE |
|---------|------------------|---------------|
| patients | Doublons (retour quotidien du même patient) | Dédupliquer, garder la version la plus récente |
| sejours | Cohérence temporelle | Écarter si `discharge_ts` < `admission_ts` |
| sejours | Séjour en cours | `discharge_ts` vide = légitime, pas une erreur |
| monitoring | Valeurs hors plage physiologique | FC 20–250 bpm · SpO2 50–100 % · temp 30–45 °C |
| tous | Valeurs manquantes / formats | Dates valides, sexe normalisé (M/F)… |

> **Ce qu'on évalue**
> À vous de détecter les lignes concernées. Le traitement attendu est simple : on les écarte (et on déduplique les patients). Seule exception : un séjour sans date de sortie n'est pas une anomalie (patient encore hospitalisé), on le conserve.

---

## 4. Le besoin métier

### Pilotage hospitalier

- Durée Moyenne de Séjour (DMS) par service
- Activité des urgences : passages par jour
- Taux de réadmission à 30 jours (qualité des soins)
- Surveillance des constantes : relevés en alerte / jour
- Toute autre vue d'activité pertinente

### Recherche clinique

- Prévalence par pathologie : taille des cohortes par diagnostic
- Description de cohorte : distribution par âge et sexe

*Les indicateurs doivent être fiables, cohérents avec les sources, et vous devez pouvoir justifier chaque chiffre.*

---

## 5. Contraintes

| CONTRAINTE | CE QU'ON ATTEND |
|------------|-----------------|
| **Incrémental** | Ingérer chaque jour les nouveaux fichiers, sans retraiter ni dupliquer les anciens. |
| **Volume** | Le monitoring est bien plus gros que le reste : l'architecture doit tenir la charge. |
| **RGPD — pseudonymisation** | Les patients arrivent avec leur identité en clair (nom, NIR…). Aucune donnée identifiante ne doit entrer dans l'entrepôt : pseudonymisez dès l'entrée du lake, avec un pseudonyme stable (pour préserver les jointures). |
| **RGPD — minimisation** | Ne conservez que ce qui est utile à l'usage. |
| **RGPD — cloisonnement** | Pilotage et recherche ne voient pas les mêmes données → droits d'accès distincts. |
| **RGPD — petits effectifs** | En recherche, ne diffusez pas les cohortes de moins de 5 patients. |
| **Traçabilité** | Savoir d'où vient chaque donnée et quand elle a été traitée. |

---

## 6. Architecture conseillée

Vous êtes libres de vos choix, mais voici la trajectoire attendue — que vous devrez justifier dans votre dossier. Le patron « médaillon » :

```
Filestorage            Lake          Bronze            Silver           Gold          Dashboards
dépôt quotidien   →  copie brute  →  fichiers →   →  nettoyé, dédup, →  KPI      →   interface
(lecture seule)                      tables typées    qualité           agrégés       d'analyse
```

| Étape | Description |
|-------|-------------|
| **Filestorage** | dépôt quotidien (lecture seule) |
| **Lake** | copie brute |
| **Bronze** | fichiers → tables typées |
| **Silver** | nettoyé, dédup, qualité |
| **Gold** | KPI agrégés |
| **Dashboards** | interface d'analyse |

### Stack conseillé (tourne sur un laptop)

- **Entrepôt** : ClickHouse en local (Docker) — warehouse colonne, UI SQL intégrée (`:8123/play`)
- **Ingestion / orchestration** : Python — recopier les fichiers puis envoyer le SQL
- **Restitution** : Metabase (Docker) — dashboards sans code

### Rôle des couches

| COUCHE | RÔLE |
|--------|------|
| **Lake** | copie brute, telle quelle |
| **Bronze** | tables typées, peu transformées |
| **Silver** | nettoyé, cohérent, enrichi |
| **Gold** | indicateurs par usage |

> **Principe à respecter**
> La transformation (bronze→silver→gold) s'exécute dans ClickHouse (en SQL). Python pilote (copie + envoi des requêtes). Ne sortez pas les données du moteur pour les transformer en mémoire (pandas) : ça ne passe pas à l'échelle — c'est l'anti-pattern classique du Big Data.

---

## 7. Livrables attendus

### Partie 1 — Interface d'analyse

- **Un dossier** : besoin, sources, schéma d'architecture justifié, traitements, indicateurs, visualisations, limites & recommandations.
- **Une interface** : ≥ 2 dashboards (pilotage + recherche) avec démonstration du cloisonnement des droits.

### Partie 2 — Automatisation

- **L'automatisation du pipeline** (collecte + transformation planifiées), avec gestion des erreurs, journalisation, traçabilité.
- **Une documentation d'utilisation et de maintenance** (lancement, reprise sur incident).

> ★ **Bonus fortement valorisé — anonymisation automatisée à l'entrée du lake**
> Un process qui, à l'ingestion, pseudonymise l'identifiant patient (hachage déterministe avec sel → stable et non réversible), généralise la date de naissance (→ année) et supprime les identifiants directs (nom, prénom, NIR). Aucune donnée identifiante ne doit jamais atteindre l'entrepôt.

---

## 8. Critères d'évaluation (indicatif)

| CRITÈRE | CE QU'ON REGARDE |
|---------|------------------|
| **Analyse du besoin** | Vous avez compris ce que veut l'hôpital |
| **Architecture** | Choix cohérents et justifiés, schéma clair |
| **Qualité des traitements** | Anomalies détectées et traitées, données fiables |
| **Fiabilité des indicateurs** | Chiffres justes, cohérents, reproductibles |
| **Restitution** | Dashboards lisibles, adaptés aux deux publics |
| **Automatisation** | Rejouable, incrémentale, robuste aux erreurs |
| **RGPD / gouvernance** | Pseudonymisation, cloisonnement, petits effectifs, traçabilité |
| **Documentation** | Claire, suffisante pour reprendre le projet |

---

*Commencez par explorer les fichiers pour comprendre ce que vous avez entre les mains avant de coder quoi que ce soit. — Bon courage.*
