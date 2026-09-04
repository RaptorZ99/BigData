# Le CHU fait évoluer ses données

**PROJET FIL ROUGE EDS CHU · ÉVOLUTION · MODULE BIG DATA M2**

*Faites évoluer votre entrepôt — sans tout refaire, sans rien casser*

> `Nouveau dépôt : 2026-08-29` · `Prérequis : votre pipeline bronze→silver→gold tourne`

---

## 1. Contexte

Votre EDS tourne. Le CHU **ajoute des données** : les services sont désormais décrits plus finement, et un nouveau flux d'**actes médicaux** arrive. Un nouveau dépôt est déposé à la date `2026-08-29`. À vous de faire **évoluer votre modèle existant** pour l'exploiter.

---

## 2. Les nouvelles données

### `referentiels/2026-08-29/description_service.csv` — CSV

*— enrichit la description des services.*

| COLONNE | TYPE | DESCRIPTION |
|---------|------|-------------|
| `service_code` | texte | Clé de jointure avec le service |
| `categorie` | texte | Type de service, **regroupe plusieurs services** (`medecine`, `chirurgie`, `reanimation`, `urgences`…) |
| `capacite_lits` | entier | Nombre de lits du service |
| `pole` | texte | Pôle hospitalier, **regroupe plusieurs catégories** |

> **Une hiérarchie, pas une redondance** — `service_label`, `categorie` et `pole` décrivent le service à **trois niveaux d'agrégation croissants** : **`service_label`** (le plus fin, 1 par service) → **`categorie`** (regroupe plusieurs services) → **`pole`** (regroupe plusieurs catégories). Ils servent à **analyser à différents niveaux** (par service, par catégorie, par pôle), pas à répéter la même information.

### `referentiels/2026-08-29/ccam.csv` — CSV

*— nomenclature des actes.*

| COLONNE | TYPE | DESCRIPTION |
|---------|------|-------------|
| `code_ccam` | texte | Code de l'acte médical |
| `libelle` | texte | Libellé de l'acte |
| `tarif_euros` | entier | Tarif de l'acte en euros (facturation T2A) |

### `actes/2026-08-29/actes.parquet` — Parquet

*— nouveau flux de faits.*

| COLONNE | TYPE | DESCRIPTION |
|---------|------|-------------|
| `stay_id` | texte | Référence au séjour |
| `code_ccam` | texte | Acte réalisé (voir référentiel) |
| `acte_ts` | horodatage | Date/heure de l'acte |

---

## 3. Ce qu'on vous demande

- **Ingérer** le nouveau dépôt via votre pipeline **incrémental** (sans retraiter l'existant).
- **Compléter** votre dimension `dim_service` avec la description (catégorie, capacité, pôle).
- **Ajouter une dimension** `dim_ccam` (nomenclature des actes).
- **Ajouter une table de faits** `fact_acte`.
- **Non-régression** : vos KPI existants (DMS, urgences, prévalence…) doivent continuer à fonctionner.

---

## 4. KPIs demandés (liés aux évolutions)

### 1. Activité et DMS par catégorie de service

Nombre de séjours et durée moyenne de séjour, regroupés par **catégorie** de service.

→ *exploite `categorie` de `dim_service` (complétée).*

### 2. Nombre d'actes par service

Nombre d'actes réalisés par service, et nombre moyen d'actes par séjour.

→ *exploite `fact_acte` (le service de l'acte vient du séjour).*

### 3. Nombre d'actes par type d'acte

Répartition des actes par code / libellé d'acte (les plus fréquents).

→ *exploite `fact_acte` + `dim_ccam`.*

### 4. Densité d'actes par lit

Nombre d'actes rapporté au nombre de lits du service (intensité du plateau technique).

→ *exploite `capacite_lits` de `dim_service`.*

### 5. Montant facturé par service (T2A)

Somme des tarifs des actes réalisés, par service.

→ *exploite `tarif_euros` de `dim_ccam`.*

> ⚠ **Deux pièges à éviter** — (1) le référentiel de description peut être **incomplet** : que faites-vous d'un service non décrit ? (2) « actes par service » : le service est porté par le **séjour**, pas par l'acte — récupérez-le **sans relier deux tables de faits entre elles**. Justifiez vos choix.

---

*EDS CHU — Consigne d'évolution · à traiter sur votre pipeline existant*
