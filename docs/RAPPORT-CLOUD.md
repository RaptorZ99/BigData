# Déploiement Azure de l'EDS — rapport d'architecture cloud

**M2 Big Data · épreuve E05** — la chaîne du poste (dépôt du CHU → lake pseudonymisé →
ClickHouse → dbt → Metabase) portée sur Azure, décrite intégralement en Terraform, exploitée
sans se connecter à une machine. **Les chiffres publiés y sont identiques à ceux du
déploiement local** : c'était le critère d'acceptation du portage, et il est tenu.

> Tout ce que ce dossier affirme a été **relevé sur l'abonnement le 3 septembre 2026**
> (`az`, `terraform state`, journaux des jobs, facture) ou lu dans [`terraform/`](../terraform/).
> Le diagramme est généré depuis [`cloud-architecture.puml`](cloud-architecture.puml) ; un
> test (`tests/test_cloud_diagram.py`) échoue s'il oublie une ressource ou un paramètre.

| § | Question |
|---|---|
| [1](#1-pourquoi-un-cloud-et-lequel) | Pourquoi un cloud, et lequel ? |
| [2](#2-larchitecture-en-un-diagramme) | À quoi ressemble l'architecture ? |
| [3](#3-pourquoi-ces-briques-et-pas-dautres) | Pourquoi ces briques, et pas d'autres ? |
| [4](#4-comment-ça-fonctionne) | Comment ça fonctionne, une nuit ordinaire ? |
| [5](#5-qui-peut-lire-quoi--sécurité-et-rgpd) | Qui peut lire quoi ? |
| [6](#6-combien-ça-coûte) | Combien ça coûte ? |
| [7](#7-limites-et-ce-quon-ferait-pour-un-vrai-chu) | Ce qui manque, et ce qu'on ferait pour un vrai CHU |

---

## 1. Pourquoi un cloud, et lequel

Le déploiement local répond déjà au sujet. Le cloud n'apporte que ce qu'un poste **ne peut
pas** offrir — et rien de décoratif :

| Ce que le poste ne peut pas offrir | Ce que le déploiement Azure apporte |
|---|---|
| Un dépôt réaliste | Le CHU dépose dans un **conteneur de stockage objet**, versionné, à suppression réversible — c'est ainsi qu'un hôpital dépose réellement |
| Une planification managée | Un **job serverless** déclenché chaque nuit par Azure, journalisé, avec réessai et déclenchement manuel pour la reprise |
| Des secrets hors des fichiers | Le `.env` devient un **coffre Key Vault**, lu par identité gérée : aucun mot de passe sur disque, ni dans Git, ni dans un manifeste |
| Un cloisonnement que le code ne peut pas contourner | Les droits de lecture sont attribués **par conteneur de stockage** : la machine de l'entrepôt n'a *aucun droit* sur l'identité en clair |
| Une infrastructure reproductible | `terraform apply` construit les 14 ressources ; `terraform destroy` ne laisse rien. 29 variables, **une seule obligatoire** |

**L'abonnement commande l'architecture.** C'est une offre *Azure for Students*, et ses
contraintes ont été relevées, pas supposées :

| Contrainte relevée | Conséquence |
|---|---|
| Une policy n'autorise que 5 régions (`uaenorth`, `spaincentral`, `italynorth`, `swedencentral`, `germanywestcentral`) — la France est exclue | Parmi elles, seules la Suède et l'Espagne proposent des petites VM. **`swedencentral`** : dans l'Union européenne, donc dans le champ du RGPD, et la moins chère |
| Quota de **6 vCPU** par région | Une seule VM de 2 vCPU. Ni cluster, ni haute disponibilité |
| Crédit de 100 $, limite de dépense activée | ≈ 33 €/mois allumée, 8 en pause (§6) ; budget avec alertes ; `make cloud-stop` entre deux démonstrations |
| Marketplace interdit au crédit | Uniquement Ubuntu et des images de conteneurs publiques |

**Ce qui ne change pas — les invariants.** Un seul code, deux cibles (`local`, `azure`) :
même orchestrateur Python, même SQL bronze, mêmes 34 modèles dbt, mêmes tableaux de bord
provisionnés par code. Vérifié sur les deux déploiements : 92 fichiers sur 29 jours, 18 tables
gold, 27 cartes Metabase sans erreur, **26 résultats de carte sur 27 identiques au bit près**
(la 27ᵉ, le journal d'ingestion, diffère par son horodatage de traitement).

> **Deux écarts trouvés en rédigeant ce rapport, corrigés le jour même.** Relire
> l'infrastructure pour la décrire a montré (1) que le droit du job sur le site de
> documentation portait sur le **compte** de stockage entier, et non sur son seul conteneur —
> ramené au conteneur `$web` (§5.2) ; (2) que l'environnement Container Apps n'est pas gratuit :
> il crée une IP publique facturée ~3 €/mois, absente de toutes les estimations (§6).

---

## 2. L'architecture en un diagramme

Vue de **déploiement** au sens du modèle C4 (niveau 4 : *où* tourne chaque brique), avec les
icônes officielles Azure. Chaque boîte porte le nom réel de la ressource et ses paramètres.
Les flèches numérotées **1 → 7** se lisent dans l'ordre d'une nuit ordinaire (§4).

[![Architecture du déploiement Azure](img/eds-cloud-architecture.png)](img/eds-cloud-architecture.svg)

*Cliquer pour la version vectorielle. Source : [`cloud-architecture.puml`](cloud-architecture.puml), régénérée par `make diagram`.*

| Couleur | Signification |
|---|---|
| **Rouge** | Identité en clair. Un seul composant peut le lire : le job de collecte |
| **Vert** | Données pseudonymisées ou agrégées |
| **Gris foncé** | Joignable depuis Internet : l'IP publique, Caddy, le site de documentation |
| Flèches **bleues** | Flux de données du traitement nocturne (1 → 6) |
| Flèches **vertes** | Restitution aux utilisateurs (7) |
| Flèches **violettes**, tiretées | Identités et secrets |
| Flèches **grises**, pointillées | Exploitation, livraison, provisionnement |

Les 14 ressources du groupe, plus deux hors du groupe :

| Ressource | Nom | Rôle |
|---|---|---|
| Groupe de ressources | `rg-eds-chu-prod` | Tout y vit ; le détruire ne laisse rien |
| Réseau virtuel | `vnet-eds-chu-prod` · `10.20.0.0/16` | Deux sous-réseaux : `snet-warehouse` (`/24`, la VM) et `snet-jobs` (`/27`, délégué à Container Apps) |
| Groupe de sécurité | `nsg-warehouse-eds-chu-prod` | Ce qui peut entrer, et d'où (§5.1) |
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

## 3. Pourquoi ces briques, et pas d'autres

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

## 4. Comment ça fonctionne

### 4.1 Une nuit ordinaire — les sept flèches du diagramme

| # | Qui | Quoi | Comment, et pourquoi c'est sûr |
|---|---|---|---|
| **1** | Le CHU — aujourd'hui l'exploitant, par `make cloud-seed` | Dépose ses fichiers dans `filestorage` | `az storage blob upload-batch`, authentifié par Entra ID. Le conteneur est versionné : un fichier écrasé se retrouve |
| **2** | Azure, à 01 h 05 UTC | Démarre `job-eds-pipeline` | Tire l'image publique, injecte les 7 secrets depuis le coffre par l'identité gérée. Zéro réplique le reste du temps |
| **3** | Le job | Lit le dépôt | `Storage Blob Data Reader`, sur ce seul conteneur. Empreinte SHA-256 par fichier : un fichier déjà chargé est ignoré |
| **4** | Le job | Écrit le lake pseudonymisé | `Storage Blob Data Contributor`, sur ce seul conteneur. La pseudonymisation (HMAC-SHA256, sel du coffre) se fait **en flux**, ligne à ligne : l'identité en clair n'est jamais un fichier intermédiaire |
| **5** | Le job | Pilote ClickHouse | HTTP 8123 sur l'IP privée `10.20.1.10`, via le réseau virtuel — le port n'est pas ouvert sur Internet. Chargement bronze par jour (`DROP PARTITION` + `INSERT`), puis `dbt build` : silver, gold, 117 tests |
| **6** | ClickHouse | Lit lui-même le lake | `azureBlobStorage(lake, …)` : une collection nommée porte l'URL SAS côté serveur. Le jeton n'apparaît ni dans le SQL, ni dans `system.query_log` (règle de masquage), ni dans les journaux du pipeline |
| **7** | Direction, chercheurs | Consultent | HTTPS 443 → Caddy → Metabase → ClickHouse avec `chu_pilotage` ou `chu_recherche`, chacun `SELECT` sur sa seule base gold |

La sortie du job part dans Log Analytics avec le `run_id` — le même que dans
`ops.pipeline_runs` et le rapport qualité du tableau de bord.

### 4.2 Ce qui se passe quand la VM démarre

La pile est un service systemd (`eds-stack`). À chaque démarrage, avant Docker Compose, un
script de 50 lignes demande un jeton à l'adresse de métadonnées locale (IMDS), lit dans le
coffre le mot de passe ETL et l'URL SAS, écrit le premier dans `/opt/eds/.env` (`0600`, root)
et la seconde dans la configuration de ClickHouse. Conséquence : **changer un secret ou
renouveler le jeton = redémarrer la VM.** Rien n'est écrit dans `custom_data`, qui finirait
dans l'état Terraform et serait lisible de quiconque a un droit de lecture sur la VM.

### 4.3 Mise en service, de zéro

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

### 4.4 Exploitation et reprise

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

## 5. Qui peut lire quoi — sécurité et RGPD

### 5.1 Réseau : ce qui entre, et d'où

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

### 5.2 Identités et droits — relevés, pas déclarés

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
> cloisonnement décrit au [rapport, §6](RAPPORT.md#6-restitution-et-cloisonnement) — le seul
> que le code ne peut pas contourner.

Les droits des identités de la plateforme sont attribués **au conteneur**, jamais au compte.
Celui du job sur `$web` faisait exception jusqu'à ce jour : il portait sur le compte entier,
donc aussi sur `filestorage` en écriture. Ramené au conteneur, appliqué, et vérifié par une
exécution de `job-eds-provision` qui a republié la documentation. Seul l'exploitant garde un
droit d'écriture sur le compte entier, pour `make cloud-seed` — attribué à la main, hors
Terraform, comme le droit sur le stockage de l'état : c'est le geste d'amorçage, pas la
plateforme.

### 5.3 Secrets : où ils vivent, qui les lit

| Secret | Où | Lu par | Jamais dans |
|---|---|---|---|
| Sel de pseudonymisation | Coffre — **irremplaçable** : le perdre rompt toutes les jointures | Le job, en variable d'environnement | Git, journaux, SQL |
| Six mots de passe (ClickHouse × 3, Metabase × 3) | Coffre, générés par Terraform (28 caractères) | Les jobs ; la VM ne lit que celui de l'ETL | Git, `custom_data`, manifestes ARM — les jobs ne portent que des *références* |
| URL SAS du lake | Coffre, renouvelée par `terraform apply` 15 jours avant son terme | La VM, au démarrage → configuration ClickHouse | Le SQL envoyé, `system.query_log` (masquage `sig=…`) |
| État Terraform | Conteneur privé, versionné, Entra ID | L'exploitant | Git, le poste |

Le coffre est en suppression réversible 7 jours, **sans** protection contre la purge : un
projet pédagogique doit rester destructible. Pour un CHU, la protection serait activée.

### 5.4 Données de santé : où sont-elles ?

| Zone | Contenu | Identifiant |
|---|---|---|
| `filestorage` | Les exports du CHU tels que déposés | **Oui** — NIR, nom, prénom, date de naissance |
| `lake` | Copie de travail | Non — `patient_pseudo` (HMAC), année de naissance ; NIR, nom et prénom n'y sont jamais copiés |
| ClickHouse (VM) | bronze, silver, gold, ops | Non — construit uniquement depuis `lake` |
| Metabase, `$web` | Agrégats, métadonnées | Non |
| Journaux, état Terraform | Exploitation | Non |

La région est `swedencentral` : Union européenne, donc RGPD. Un CHU réel exigerait un
hébergeur certifié HDS en France — possible sur un abonnement payant en changeant la seule
variable `location` (§7).

---

## 6. Combien ça coûte

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

## 7. Limites, et ce qu'on ferait pour un vrai CHU

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
| **Mode nuit non activé** | Deux variables suffisent ; laissé éteint pour que la plateforme réponde à toute heure pendant l'évaluation | L'activer : 22,6 €/mois |
| **Une seule région, réplication locale (LRS)** | Coût | Réplication géo-redondante du dépôt, plan de reprise |
| **Supervision limitée aux alertes de budget** | Aucun test de disponibilité | Alerte Azure Monitor sur `job-eds-pipeline` en échec et sur la VM arrêtée |

**Trois recommandations de gouvernance**, qui relèvent de l'organisation et non du code :

1. Le sel de pseudonymisation est le seul élément **non reconstructible** de la plateforme :
   activer la protection contre la purge du coffre, et documenter qui a le droit de le lire.
2. Faire délivrer au CHU un jeton d'écriture sur `filestorage`, et rien d'autre : le dépôt
   devient son geste, pas celui de l'exploitant.
3. Exiger que `terraform plan` soit vide avant toute démonstration : c'est la preuve que le
   code décrit ce qui tourne, et donc que ce rapport est encore vrai.
