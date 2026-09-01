# Le compte de stockage porte les deux zones du pipeline, et la frontière RGPD la
# plus forte du déploiement :
#
#   filestorage — le dépôt du CHU, identité en clair
#   lake        — la copie pseudonymisée, seule zone que l'entrepôt peut lire
#
# Les droits sont attribués **au conteneur**, pas au compte. Conséquence : la
# machine qui héberge ClickHouse et Metabase n'a aucun moyen de lire les noms et
# les NIR. Ce n'est pas une règle de code, c'est une propriété de l'IAM.

resource "azurerm_storage_account" "eds" {
  name                     = local.nom_stockage
  resource_group_name      = azurerm_resource_group.eds.name
  location                 = azurerm_resource_group.eds.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Espace de noms hiérarchique (ADLS Gen2) : **désactivé**, à dessein.
  #
  # Azure refuse `versioning_enabled` sur un compte hiérarchique. Or le conteneur
  # `filestorage` est la seule source de vérité du système — tout le reste se
  # reconstruit à partir de lui. Entre des répertoires POSIX dont on ne se sert pas
  # (les droits sont attribués au conteneur, pas au dossier) et l'historique des
  # versions du dépôt du CHU, le choix n'est pas disputé.
  #
  # Effet de bord bienvenu : `azureBlobStorage()` lit un compte de blobs classique,
  # le cas le mieux éprouvé côté ClickHouse.
  is_hns_enabled = false

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true

  # La clé de compte reste activée : c'est elle qui signe le jeton SAS confié à
  # ClickHouse. Le moteur ne sait pas utiliser une identité gérée (sa version
  # 26.3 tente `WorkloadIdentityCredential`, réservé à Kubernetes) — cf.
  # docs/PLAN-CLOUD.md §5.2. Le pipeline, lui, n'utilise que l'identité gérée.
  shared_access_key_enabled = true

  blob_properties {
    # Le dépôt du CHU est la seule source de vérité du système : tout le reste se
    # reconstruit. Il est donc versionné et sa suppression est réversible.
    versioning_enabled = true

    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  tags = local.etiquettes
}

# Site statique : la documentation dbt, un fichier HTML autonome. Métadonnées, graphe
# des modèles et comptages de lignes — aucune donnée patient.
#
# AzureRM 5.0 a sorti ce réglage du compte de stockage pour en faire une ressource
# à part : il modifie le plan de données, pas le plan de contrôle.
resource "azurerm_storage_account_static_website" "docs" {
  count              = var.publish_dbt_docs ? 1 : 0
  storage_account_id = azurerm_storage_account.eds.id
  index_document     = "index.html"
}

resource "azurerm_storage_container" "filestorage" {
  name                  = "filestorage"
  storage_account_id    = azurerm_storage_account.eds.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "lake" {
  name                  = "lake"
  storage_account_id    = azurerm_storage_account.eds.id
  container_access_type = "private"
}

# ── Le jeton que lit ClickHouse ─────────────────────────────────────────────
# Portée minimale : un conteneur, en lecture et liste seulement, daté.
#
# `time_rotating` fige la date de début entre deux rotations : sans lui, un
# `timestamp()` régénérerait le jeton à chaque `terraform plan` et ferait
# apparaître une modification qui n'en est pas une.
resource "time_rotating" "lake_sas" {
  rotation_days = var.lake_sas_expiry_days - 15
}

data "azurerm_storage_account_blob_container_sas" "lake" {
  connection_string = azurerm_storage_account.eds.primary_connection_string
  container_name    = azurerm_storage_container.lake.name
  https_only        = true

  start  = time_rotating.lake_sas.rfc3339
  expiry = timeadd(time_rotating.lake_sas.rfc3339, "${var.lake_sas_expiry_days * 24}h")

  permissions {
    read   = true
    list   = true
    add    = false
    create = false
    write  = false
    delete = false
  }
}

# ── Droits de données ───────────────────────────────────────────────────────
# Portée : le **conteneur**, jamais le compte. C'est ce qui rend la frontière RGPD
# opposable — un droit accordé au compte ouvrirait les deux zones d'un coup.
#
# Depuis AzureRM 5.0, l'identifiant d'un conteneur *est* son identifiant de
# gestion Azure : l'attribut `resource_manager_id` des versions 3 et 4 a disparu
# avec la migration des ressources de stockage vers l'API de gestion.
#
# Le job lit l'identité en clair…
resource "azurerm_role_assignment" "job_filestorage_lecteur" {
  scope                = azurerm_storage_container.filestorage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

# …et n'écrit que dans le lake, pseudonymisé.
resource "azurerm_role_assignment" "job_lake_contributeur" {
  scope                = azurerm_storage_container.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

# La documentation dbt est publiée par le job dans le conteneur du site statique.
resource "azurerm_role_assignment" "job_web_contributeur" {
  count                = var.publish_dbt_docs ? 1 : 0
  scope                = azurerm_storage_account.eds.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

# La VM, elle, n'a AUCUNE attribution de rôle sur ce compte. Elle ne peut lire
# que le lake, et seulement par le jeton SAS ci-dessus. C'est volontaire, et
# c'est le point le plus fort du cloisonnement : l'entrepôt ne peut pas atteindre
# l'identité en clair, même si son code le voulait.
