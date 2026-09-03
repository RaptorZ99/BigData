# Les cibles `make cloud-*` lisent ces trois sorties : les noms ne sont écrits
# qu'ici, et ne peuvent donc pas diverger entre le Makefile et l'infrastructure.
output "nom_groupe" {
  description = "Groupe de ressources."
  value       = azurerm_resource_group.eds.name
}

output "nom_vm" {
  description = "Machine virtuelle de restitution."
  value       = azurerm_linux_virtual_machine.warehouse.name
}

output "url_metabase" {
  description = "Tableaux de bord. Certificat interne par défaut : un avertissement à accepter une fois."
  value       = "https://${local.hote_site}"
}

output "ip_publique" {
  description = "Adresse publique de la VM."
  value       = azurerm_public_ip.eds.ip_address
}

output "url_documentation_dbt" {
  description = "Documentation dbt (graphe des modèles). Publiée par job-eds-provision."
  value       = var.publish_dbt_docs ? azurerm_storage_account.eds.primary_web_endpoint : "désactivée"
}

output "compte_stockage" {
  description = "Compte de stockage portant le dépôt du CHU et le lake."
  value       = azurerm_storage_account.eds.name
}

output "coffre" {
  description = "Coffre Key Vault. Les secrets s'y lisent avec `az keyvault secret show`."
  value       = azurerm_key_vault.eds.name
}

output "commandes" {
  description = "Les gestes d'exploitation, prêts à coller."
  value = {
    deposer_les_fichiers  = "az storage blob upload-batch --account-name ${azurerm_storage_account.eds.name} --auth-mode login -d ${azurerm_storage_container.filestorage.name} -s source-filestorage"
    provisionner          = "az containerapp job start -n ${azurerm_container_app_job.provision.name} -g ${azurerm_resource_group.eds.name}"
    lancer_le_pipeline    = "az containerapp job start -n ${azurerm_container_app_job.pipeline.name} -g ${azurerm_resource_group.eds.name}"
    prouver_cloisonnement = "az containerapp job start -n ${azurerm_container_app_job.controle.name} -g ${azurerm_resource_group.eds.name}"
    rejouer_un_jour       = "az containerapp job start -n ${azurerm_container_app_job.pipeline.name} -g ${azurerm_resource_group.eds.name} --args 'run,--date,2026-08-27'"
    ssh                   = "ssh ${var.admin_username}@${azurerm_public_ip.eds.ip_address}"
    console_sql           = "ssh -N -L 8123:localhost:8123 ${var.admin_username}@${azurerm_public_ip.eds.ip_address}   # puis http://localhost:8123/play"
    mots_de_passe         = "az keyvault secret show --vault-name ${azurerm_key_vault.eds.name} -n mb-pilotage-password --query value -o tsv"
    eteindre              = "az vm deallocate -g ${azurerm_resource_group.eds.name} -n ${azurerm_linux_virtual_machine.warehouse.name}"
    rallumer              = "az vm start -g ${azurerm_resource_group.eds.name} -n ${azurerm_linux_virtual_machine.warehouse.name}"
  }
}

output "journaux_kql" {
  description = "Requête à coller dans Log Analytics pour suivre le dernier run."
  value       = <<-KQL
    ContainerAppConsoleLogs_CL
    | where ContainerGroupName_s startswith "job-eds-pipeline"
    | where TimeGenerated > ago(24h)
    | project TimeGenerated, Log_s
    | order by TimeGenerated asc
  KQL
}

output "cout_mensuel_estime_eur" {
  description = "Estimation, tarifs Linux relevés à l'API Azure pour la région choisie."
  value = {
    vm             = var.vm_size
    note           = "VM ${var.vm_size} + disque ${var.os_disk_size_gb} Gio + deux IP publiques (la VM, et celle que l environnement Container Apps cree dans son groupe gere). Jobs, stockage et journaux : sous les offres gratuites."
    allumee_24h_24 = var.auto_shutdown_time == "" ? "~33 EUR/mois" : "~23 EUR/mois (extinction ${var.auto_shutdown_time})"
    eteinte        = "~8 EUR/mois (disque + deux IP conserves)"
  }
}
