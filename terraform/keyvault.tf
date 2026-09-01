# Les secrets ne vivent nulle part ailleurs : ni dans le dépôt, ni dans un `.env`
# sur la VM, ni dans `user_data`. La VM et les jobs les lisent au démarrage, par
# leur identité gérée.
#
# Le seul endroit où ils apparaissent aussi est l'état Terraform — d'où le
# backend privé et l'interdiction de le committer.

data "azurerm_client_config" "actuel" {}

resource "azurerm_key_vault" "eds" {
  name                = local.nom_coffre
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  tenant_id           = data.azurerm_client_config.actuel.tenant_id
  sku_name            = "standard"

  # RBAC plutôt que politiques d'accès : les droits se lisent au même endroit que
  # ceux du stockage, et se révoquent de la même façon.
  rbac_authorization_enabled = true

  # Le sel de pseudonymisation est irremplaçable : le perdre invalide tous les
  # pseudonymes et rompt toutes les jointures de l'entrepôt. Sept jours de
  # suppression réversible, et pas de protection contre la purge — un projet
  # pédagogique doit rester destructible.
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  tags = local.etiquettes
}

# Celui qui exécute Terraform doit pouvoir écrire les secrets.
resource "azurerm_role_assignment" "tf_secrets_officer" {
  scope                = azurerm_key_vault.eds.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.actuel.object_id
}

# La propagation d'une attribution de rôle n'est pas instantanée : sans cette
# attente, le premier `apply` échoue en écrivant les secrets, et le second passe.
# Un déploiement qui ne marche qu'à la deuxième tentative n'est pas reproductible.
resource "time_sleep" "propagation_rbac" {
  depends_on      = [azurerm_role_assignment.tf_secrets_officer]
  create_duration = "30s"
}

# ── Les secrets, tous générés ───────────────────────────────────────────────
# Sel de pseudonymisation : 64 caractères hexadécimaux, l'équivalent de
# `openssl rand -hex 32` du chemin local.
resource "random_id" "sel" {
  byte_length = 32
}

# Metabase exige majuscule, minuscule, chiffre et caractère spécial — un
# hexadécimal seul ne suffirait pas. Même contrainte que le `Makefile` local.
resource "random_password" "secrets" {
  for_each = toset([
    "clickhouse-etl",
    "clickhouse-pilotage",
    "clickhouse-recherche",
    "mb-admin",
    "mb-pilotage",
    "mb-recherche",
  ])

  length           = 28
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  override_special = "!#%-_"
}

resource "azurerm_key_vault_secret" "eds_salt" {
  name         = "eds-salt"
  value        = random_id.sel.hex
  key_vault_id = azurerm_key_vault.eds.id
  content_type = "Sel HMAC-SHA256 de pseudonymisation — irremplacable"
  depends_on   = [time_sleep.propagation_rbac]
}

resource "azurerm_key_vault_secret" "mots_de_passe" {
  for_each = random_password.secrets

  name         = "${each.key}-password"
  value        = each.value.result
  key_vault_id = azurerm_key_vault.eds.id
  depends_on   = [time_sleep.propagation_rbac]
}

# L'URL SAS que ClickHouse utilise pour lire le lake. Elle ne transite jamais par
# le SQL : la VM la récupère au démarrage et l'écrit dans une collection nommée,
# côté serveur.
resource "azurerm_key_vault_secret" "lake_sas_url" {
  name         = "lake-sas-url"
  value        = "https://${azurerm_storage_account.eds.name}.blob.core.windows.net/${data.azurerm_storage_account_blob_container_sas.lake.sas}"
  key_vault_id = azurerm_key_vault.eds.id
  content_type = "URL de lecture du lake, portee au conteneur, en lecture seule"
  depends_on   = [time_sleep.propagation_rbac]
}

# ── Qui peut lire quoi ──────────────────────────────────────────────────────
resource "azurerm_role_assignment" "job_secrets_user" {
  scope                = azurerm_key_vault.eds.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

resource "azurerm_role_assignment" "vm_secrets_user" {
  scope                = azurerm_key_vault.eds.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.warehouse.identity[0].principal_id
}
