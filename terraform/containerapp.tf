# Les trois jobs du pipeline.
#
# Pourquoi des jobs Container Apps plutôt qu'un `cron` sur la VM :
#
#   * ils sont **serverless** — zéro réplique entre deux exécutions, donc zéro coût.
#     Soixante secondes par jour à 0,5 vCPU consomment 0,5 % de l'offre mensuelle
#     gratuite (180 000 vCPU-s) : le pipeline planifié ne coûte rien ;
#   * ils sont **dans le réseau** — le job joint l'entrepôt par son adresse privée,
#     ce qui permet de ne jamais exposer ClickHouse sur Internet ;
#   * ils sont **journalisés** — la sortie part dans Log Analytics, interrogeable
#     en KQL, avec le `run_id` qui relie chaque ligne à `ops.pipeline_runs` ;
#   * ils se **déclenchent à la main** — `az containerapp job start` est le geste de
#     reprise sur incident, et il exécute exactement le même code que la planification.

resource "azurerm_container_app_environment" "eds" {
  name                = "cae-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location

  infrastructure_subnet_id = azurerm_subnet.jobs.id

  # La destination doit être déclarée explicitement : rattacher un espace de travail
  # sans elle est refusé. Le défaut de la plateforme est son propre stockage de
  # journaux, sans requête KQL possible.
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.eds.id

  internal_load_balancer_enabled = false

  # Azure ajoute d'office ce profil à tout environnement, et Terraform voudrait le
  # retirer à chaque plan tant qu'on ne le déclare pas. Le déclarer supprime un
  # « diff perpétuel » — le genre de bruit qui finit par faire ignorer les plans.
  #
  # Le profil Consommation ne coûte rien en soi : seul un profil *dédié* déclenche
  # les frais de gestion de plan.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  tags = local.etiquettes
}

locals {
  # Variables communes aux trois jobs : elles décrivent *où* travailler, jamais
  # *avec quoi* — les secrets passent par des références au coffre.
  env_pipeline = {
    EDS_STORAGE_BACKEND        = "azure"
    EDS_STORAGE_ACCOUNT        = azurerm_storage_account.eds.name
    EDS_SOURCE_CONTAINER       = azurerm_storage_container.filestorage.name
    EDS_LAKE_CONTAINER         = azurerm_storage_container.lake.name
    EDS_WEB_CONTAINER          = "$web"
    DBT_TARGET                 = "azure"
    CLICKHOUSE_HOST            = local.ip_privee_vm
    CLICKHOUSE_PORT            = "8123"
    CLICKHOUSE_ETL_USER        = "chu_etl"
    MB_URL                     = "http://${local.ip_privee_vm}:3000"
    MB_CLICKHOUSE_HOST         = "clickhouse"
    MB_CLICKHOUSE_PORT         = "8123"
    MB_ADMIN_EMAIL             = "admin@chu.local"
    MB_PILOTAGE_EMAIL          = "pilotage@chu.local"
    MB_RECHERCHE_EMAIL         = "recherche@chu.local"
    EDS_RESTITUTION_MAX_MEMORY = tostring(var.restitution_max_memory)
    # `DefaultAzureCredential` choisit l'identité assignée par cet identifiant.
    # Sans lui, une VM ou un conteneur portant plusieurs identités ne saurait
    # laquelle présenter.
    AZURE_CLIENT_ID = azurerm_user_assigned_identity.pipeline.client_id
  }

  # Secret du coffre → variable d'environnement. Le manifeste du job ne contient
  # que des références : aucun mot de passe n'apparaît dans l'état ARM, ni dans
  # le portail.
  secrets_pipeline = {
    "eds-salt"                      = "EDS_SALT"
    "clickhouse-etl-password"       = "CLICKHOUSE_ETL_PASSWORD"
    "clickhouse-pilotage-password"  = "CLICKHOUSE_PILOTAGE_PASSWORD"
    "clickhouse-recherche-password" = "CLICKHOUSE_RECHERCHE_PASSWORD"
    "mb-admin-password"             = "MB_ADMIN_PASSWORD"
    "mb-pilotage-password"          = "MB_PILOTAGE_PASSWORD"
    "mb-recherche-password"         = "MB_RECHERCHE_PASSWORD"
  }

  secret_ids = merge(
    { "eds-salt" = azurerm_key_vault_secret.eds_salt.versionless_id },
    {
      for cle, secret in azurerm_key_vault_secret.mots_de_passe :
      "${cle}-password" => secret.versionless_id
    }
  )
}

# ── Le geste quotidien ──────────────────────────────────────────────────────
resource "azurerm_container_app_job" "pipeline" {
  name                         = "job-eds-pipeline"
  resource_group_name          = azurerm_resource_group.eds.name
  location                     = azurerm_resource_group.eds.location
  container_app_environment_id = azurerm_container_app_environment.eds.id
  workload_profile_name        = "Consumption"
  tags                         = local.etiquettes

  # Trente minutes : très au-dessus des quelques dizaines de secondes que prend
  # un run, mais un dépôt volumineux ne doit pas être coupé en plein chargement.
  replica_timeout_in_seconds = 1800
  # Un seul réessai. Le pipeline est idempotent, mais un fichier malformé
  # échouerait à l'identique : l'aléa réseau mérite une seconde chance, pas une
  # erreur de données — elle doit remonter.
  replica_retry_limit = 1

  schedule_trigger_config {
    cron_expression = var.pipeline_cron
    parallelism     = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pipeline.id]
  }

  dynamic "secret" {
    for_each = local.secrets_pipeline
    content {
      name                = secret.key
      key_vault_secret_id = local.secret_ids[secret.key]
      identity            = azurerm_user_assigned_identity.pipeline.id
    }
  }

  template {
    container {
      name   = "eds"
      image  = var.eds_image
      cpu    = 0.5
      memory = "1Gi"
      args   = ["run"]

      dynamic "env" {
        for_each = local.env_pipeline
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets_pipeline
        content {
          name        = env.value
          secret_name = env.key
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.job_secrets_user,
    azurerm_role_assignment.job_filestorage_lecteur,
    azurerm_role_assignment.job_lake_contributeur,
  ]
}

# ── Mise en service et convergence ──────────────────────────────────────────
# Déclenché à la main : il crée bases, comptes cloisonnés, connexions Metabase,
# groupes, utilisateurs, permissions et tableaux de bord — puis publie la
# documentation dbt. Entièrement idempotent : le rejouer réaligne l'existant.
resource "azurerm_container_app_job" "provision" {
  name                         = "job-eds-provision"
  resource_group_name          = azurerm_resource_group.eds.name
  location                     = azurerm_resource_group.eds.location
  container_app_environment_id = azurerm_container_app_environment.eds.id
  workload_profile_name        = "Consumption"
  tags                         = local.etiquettes

  replica_timeout_in_seconds = 1800
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pipeline.id]
  }

  dynamic "secret" {
    for_each = local.secrets_pipeline
    content {
      name                = secret.key
      key_vault_secret_id = local.secret_ids[secret.key]
      identity            = azurerm_user_assigned_identity.pipeline.id
    }
  }

  template {
    container {
      name   = "eds"
      image  = var.eds_image
      cpu    = 0.5
      memory = "1Gi"
      # Le point d'entrée est `eds` : on le contourne pour enchaîner trois
      # commandes en une exécution.
      command = ["/bin/sh", "-c"]
      args = [
        var.publish_dbt_docs
        ? "eds provision-warehouse && eds provision-metabase && eds publish-dbt-docs"
        : "eds provision-warehouse && eds provision-metabase"
      ]

      dynamic "env" {
        for_each = local.env_pipeline
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets_pipeline
        content {
          name        = env.value
          secret_name = env.key
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.job_secrets_user,
    azurerm_role_assignment.job_lake_contributeur,
  ]
}

# ── La preuve du cloisonnement, rejouable ───────────────────────────────────
# Le sujet demande une démonstration du cloisonnement des droits. Plutôt qu'une
# capture d'écran, un job : il se connecte réellement avec chaque compte, tente
# les accès interdits et exige un refus explicite du moteur.
resource "azurerm_container_app_job" "controle" {
  name                         = "job-eds-controle"
  resource_group_name          = azurerm_resource_group.eds.name
  location                     = azurerm_resource_group.eds.location
  container_app_environment_id = azurerm_container_app_environment.eds.id
  workload_profile_name        = "Consumption"
  tags                         = local.etiquettes

  replica_timeout_in_seconds = 600
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pipeline.id]
  }

  dynamic "secret" {
    for_each = local.secrets_pipeline
    content {
      name                = secret.key
      key_vault_secret_id = local.secret_ids[secret.key]
      identity            = azurerm_user_assigned_identity.pipeline.id
    }
  }

  template {
    container {
      name   = "eds"
      image  = var.eds_image
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["check-cloisonnement"]

      dynamic "env" {
        for_each = local.env_pipeline
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets_pipeline
        content {
          name        = env.value
          secret_name = env.key
        }
      }
    }
  }

  depends_on = [azurerm_role_assignment.job_secrets_user]
}
