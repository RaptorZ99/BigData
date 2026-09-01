# Toutes les variables ont un défaut sûr : `terraform apply` avec le seul
# `subscription_id` produit une plateforme fonctionnelle et fermée.

# ── Abonnement et nommage ───────────────────────────────────────────────────
variable "subscription_id" {
  description = "Abonnement Azure cible. Obligatoire depuis AzureRM 5.0."
  type        = string
}

variable "projet" {
  description = "Préfixe de nommage des ressources."
  type        = string
  default     = "eds-chu"
}

variable "environnement" {
  description = "Environnement logique (prod, demo, test)."
  type        = string
  default     = "prod"
}

variable "location" {
  description = <<-TXT
    Région Azure.

    `francecentral` aurait été le choix naturel — données de santé françaises sur le
    territoire national. Il est **impossible** sur l'offre étudiante : aucune VM de
    série B n'y est proposée à cet abonnement (`az vm list-skus` la déclare
    `NotAvailableForSubscription`, restriction de type `Location`), et la plus petite
    taille réellement disponible y coûte 70 €/mois. Même constat en `northeurope` et
    `germanywestcentral`.

    Deux contraintes se cumulent, toutes deux propres à l'offre étudiante :

      1. Une **policy Azure** (« Allowed resource deployment regions ») restreint le
         déploiement à : uaenorth, spaincentral, italynorth, swedencentral,
         germanywestcentral. Toute autre région échoue en `RequestDisallowedByAzure`.
      2. Parmi celles-là, seules `swedencentral` et `spaincentral` proposent la série B
         (`az vm list-skus`) ; `italynorth` et `germanywestcentral` n'en proposent
         aucune, et la plus petite taille qu'on y trouve dépasse 70 €/mois.

    `swedencentral` est donc retenue : elle est dans l'Union européenne — donc dans le
    champ du RGPD — et c'est la moins chère des deux. L'hébergement en France
    redeviendrait possible sur un abonnement payant, sans autre changement que cette
    variable.
  TXT
  type        = string
  default     = "swedencentral"
}

variable "etiquettes" {
  description = "Étiquettes additionnelles, fusionnées avec celles du projet."
  type        = map(string)
  default     = {}
}

# ── Dimensionnement ─────────────────────────────────────────────────────────
variable "vm_size" {
  description = <<-TXT
    Taille de la VM qui héberge ClickHouse, Metabase et Caddy.

      Standard_B2ts_v2   2 vCPU / 1 Gio         6,77 €/mois   trop juste pour la pile
      Standard_B2pls_v2  2 vCPU / 4 Gio (Arm)   21,56 €/mois   exigerait des images arm64
      Standard_B2als_v2  2 vCPU / 4 Gio (AMD)   24,38 €/mois   défaut
      Standard_B2ls_v2   2 vCPU / 4 Gio (Intel) 27,08 €/mois
      Standard_B2s_v2    2 vCPU / 8 Gio         65,82 €/mois   divise l'autonomie par deux

    Prix Linux relevés à l'API tarifaire Azure pour `swedencentral`, base 730 h/mois.
    La variante Arm est la moins chère, mais imposerait des images arm64 pour
    ClickHouse, Metabase et Caddy : trois variables de plus pour 2,80 €/mois.

    Le quota de l'offre étudiante plafonne à 6 vCPU par région : une seule VM.
  TXT
  type        = string
  default     = "Standard_B2als_v2"
}

variable "os_disk_size_gb" {
  description = "Taille du disque OS. Il porte aussi les volumes Docker."
  type        = number
  default     = 32
}

variable "os_disk_type" {
  description = "Type de disque. StandardSSD_LRS 32 Gio ≈ 2,27 €/mois."
  type        = string
  default     = "StandardSSD_LRS"
}

variable "swap_size_gb" {
  description = <<-TXT
    Fichier d'échange. Confort plutôt que nécessité sur 4 Gio — les trois conteneurs
    y tiennent avec ~800 Mo de marge. Il devient indispensable si l'on descend à
    `Standard_B2ts_v2` (1 Gio).
  TXT
  type        = number
  default     = 2
}

variable "auto_shutdown_time" {
  description = <<-TXT
    Extinction quotidienne au format HHMM, fuseau de la région (ex. "2200").
    Vide = la VM reste allumée. Éteindre 22 h → 8 h ramène le coût de 34 à 24 €/mois,
    soit 2,3 mois d'autonomie portés à 3,2 — au prix d'une indisponibilité nocturne,
    à éviter si l'évaluation peut avoir lieu hors heures ouvrées.
  TXT
  type        = string
  default     = ""
}

# ── Réseau et exposition ────────────────────────────────────────────────────
variable "cidr_vnet" {
  description = "Plage du réseau virtuel."
  type        = string
  default     = "10.20.0.0/16"
}

variable "cidr_warehouse" {
  description = "Sous-réseau de la VM."
  type        = string
  default     = "10.20.1.0/24"
}

variable "cidr_jobs" {
  description = <<-TXT
    Sous-réseau des jobs Container Apps, délégué à Microsoft.App/environments.
    /27 est le minimum pour un environnement à profils de charge (le défaut) ;
    onze adresses y sont réservées par la plateforme.
  TXT
  type        = string
  default     = "10.20.2.0/27"
}

variable "admin_username" {
  description = "Compte SSH de la VM."
  type        = string
  default     = "chu"
}

variable "ssh_public_key" {
  description = <<-TXT
    Clé publique SSH, contenu ou chemin. Par défaut, la clé ed25519 du poste.
    Aucun mot de passe n'est activé sur la VM : l'authentification par mot de
    passe est désactivée côté image.
  TXT
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_source_cidrs" {
  description = <<-TXT
    Adresses autorisées à ouvrir SSH. Vide = l'adresse publique du poste qui
    exécute `terraform apply`, détectée automatiquement.
  TXT
  type        = list(string)
  default     = []
}

variable "metabase_allowed_cidrs" {
  description = <<-TXT
    Adresses autorisées à atteindre les tableaux de bord en HTTPS. Ouvert par
    défaut : la démonstration doit être testable depuis n'importe où. Le
    cloisonnement repose sur l'authentification Metabase et les GRANT ClickHouse,
    pas sur le filtrage réseau.
  TXT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "expose_clickhouse_to_admin" {
  description = <<-TXT
    Ouvre le port 8123 aux adresses d'administration. Faux par défaut : la console
    `/play` s'atteint par tunnel SSH (cf. docs/CLOUD.md). Un entrepôt de santé n'a
    pas à écouter sur Internet.
  TXT
  type        = bool
  default     = false
}

# ── TLS ─────────────────────────────────────────────────────────────────────
variable "acme_hostname" {
  description = <<-TXT
    Nom de domaine pour un certificat Let's Encrypt (ex. "eds-chu.duckdns.org").
    Vide = certificat interne sur le nom Azure : le trafic est chiffré, mais le
    navigateur affiche un avertissement à la première visite.

    Let's Encrypt n'est pas utilisable sur `*.cloudapp.azure.com` : ce domaine
    n'est pas sur la Public Suffix List, son quota d'émission est donc partagé
    entre tous les clients Azure et saturé en permanence. `duckdns.org`, lui, y
    figure — chaque sous-domaine y a son propre quota.
  TXT
  type        = string
  default     = ""
}

variable "acme_email" {
  description = "Adresse de contact Let's Encrypt. Requise si acme_hostname est renseigné."
  type        = string
  default     = ""
}

# ── Pipeline ────────────────────────────────────────────────────────────────
variable "eds_image" {
  description = <<-TXT
    Image du pipeline. **Publique** : les jobs la tirent sans aucun identifiant, ce qui
    évite un registre privé (un ACR Basic coûterait 4,35 €/mois) et tout secret dans les
    manifestes.

    ⚠ Elle doit être construite pour **linux/amd64** : Container Apps n'exécute pas
    d'arm64, et un Mac Apple Silicon produit de l'arm64 par défaut. D'où le
    `--platform linux/amd64` de la cible `make image-push`.

    Épingler un commit plutôt que `latest` rend le déploiement reproductible :
    `louis336/eds-chu:8fe156b`.
  TXT
  type        = string
  default     = "louis336/eds-chu:latest"
}

variable "pipeline_cron" {
  description = "Planification du pipeline, après le dépôt nocturne du CHU (UTC)."
  type        = string
  default     = "5 1 * * *"
}

variable "lake_sas_expiry_days" {
  description = <<-TXT
    Durée de vie du jeton SAS confié à ClickHouse pour lire le lake. Il est
    renouvelé par `terraform apply` avant son terme ; un redémarrage de la VM
    suffit ensuite à le prendre en compte.
  TXT
  type        = number
  default     = 180
}

variable "restitution_max_memory" {
  description = <<-TXT
    Plafond mémoire d'une requête des comptes de restitution, en octets.

    1 Go sur une VM de 4 Gio, dont 1,5 Go alloués à ClickHouse : Metabase laisse
    écrire du SQL libre, et une requête maladroite ne doit pas pouvoir priver
    l'autre usage de son tableau de bord. Le GRANT protège la confidentialité,
    cette borne la disponibilité. À réduire si l'on descend en gamme.
  TXT
  type        = number
  default     = 1000000000
}

variable "publish_dbt_docs" {
  description = <<-TXT
    Publie la documentation dbt sur le site statique du compte de stockage.
    Elle contient le graphe des modèles, les descriptions de colonnes et des
    comptages de lignes — aucune donnée patient. L'URL est publique.
  TXT
  type        = bool
  default     = true
}

# ── Budget ──────────────────────────────────────────────────────────────────
variable "budget_amount_eur" {
  description = "Budget mensuel surveillé. Alertes à 50, 80 et 100 %."
  type        = number
  default     = 60
}

variable "budget_contact_emails" {
  description = "Destinataires des alertes de budget. Vide = aucun budget créé."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "Rétention des journaux dans Log Analytics."
  type        = number
  default     = 30
}
