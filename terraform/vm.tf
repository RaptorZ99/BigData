# La VM porte les trois conteneurs de la restitution : ClickHouse, Metabase, Caddy.
#
# Elle est du **bétail**, pas un animal de compagnie : tout ce qu'elle contient se
# reconstruit (`eds run --full-refresh` pour l'entrepôt, `eds provision-metabase`
# pour les tableaux de bord). D'où l'absence de disque de données séparé et de
# sauvegarde managée — deux postes de coût pour protéger du reconstructible.
#
# Pourquoi une VM et pas un conteneur managé : ClickHouse exige des renommages
# atomiques et des liens durs. Sur un stockage réseau — Azure Files, seul volume
# persistant qu'offre Container Apps — ces opérations échouent
# (ClickHouse/ClickHouse#74572), et c'est le même défaut qui avait imposé un volume
# Docker nommé en local. L'entrepôt veut un système de fichiers, pas un partage.

resource "azurerm_linux_virtual_machine" "warehouse" {
  name                = "vm-warehouse-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = local.etiquettes

  network_interface_ids = [azurerm_network_interface.vm.id]

  # Aucun mot de passe : clé publique uniquement.
  disable_password_authentication = true

  admin_ssh_key {
    username = var.admin_username
    # Le contenu d'un fichier si la variable pointe vers un chemin, sinon la clé
    # elle-même : les deux usages sont naturels et il n'y a pas de raison d'en
    # imposer un.
    public_key = can(file(pathexpand(var.ssh_public_key))) ? file(pathexpand(var.ssh_public_key)) : var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  # Identité système : elle ne sert qu'à lire le coffre. Aucun droit sur le
  # stockage — la machine qui héberge l'entrepôt ne peut pas atteindre le
  # conteneur qui contient les noms et les NIR.
  identity {
    type = "SystemAssigned"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init/cloud-init.yaml.tftpl", {
    swap_size_gb   = var.swap_size_gb
    key_vault_name = local.nom_coffre
    compose = base64encode(templatefile("${path.module}/cloud-init/docker-compose.cloud.yml.tftpl", {
      site_host        = local.hote_site
      memoire_ch       = local.memoire_clickhouse
      memoire_metabase = local.memoire_metabase
      xmx_metabase     = local.xmx_metabase
    }))
    caddyfile = base64encode(templatefile("${path.module}/cloud-init/Caddyfile.tftpl", {
      site_host     = local.hote_site
      directive_tls = local.directive_tls
      acme_email    = var.acme_email
    }))
    ch_limits = base64encode(templatefile("${path.module}/cloud-init/clickhouse-limits.xml.tftpl", {
      max_server_memory = local.memoire_serveur_clickhouse
      mark_cache        = local.cache_marques_clickhouse
    }))
    ch_masking = base64encode(file("${path.module}/cloud-init/clickhouse-masking.xml"))
    ch_network = base64encode(file("${path.module}/cloud-init/clickhouse-network.xml"))
    ch_users   = base64encode(file("${path.module}/cloud-init/clickhouse-users-etl.xml"))
    fetch = base64encode(templatefile("${path.module}/cloud-init/fetch-secrets.sh.tftpl", {
      key_vault_name = local.nom_coffre
    }))
  }))

  lifecycle {
    # `custom_data` ne s'applique qu'à la création : le modifier recréerait la VM
    # à chaque `apply` sans que la modification prenne effet autrement. Les
    # évolutions de configuration passent par `systemctl restart eds-stack`, qui
    # relit les secrets et redéploie la pile.
    ignore_changes = [custom_data]
  }
}

# Extinction planifiée. Gratuite, et c'est le levier de coût le plus simple :
# 22 h → 8 h ramène la facture de 35 à 23 €/mois.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "warehouse" {
  count = var.auto_shutdown_time != "" ? 1 : 0

  virtual_machine_id    = azurerm_linux_virtual_machine.warehouse.id
  location              = azurerm_resource_group.eds.location
  enabled               = true
  daily_recurrence_time = var.auto_shutdown_time
  timezone              = "W. Europe Standard Time"

  notification_settings {
    enabled = false
  }
}
