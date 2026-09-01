resource "azurerm_virtual_network" "eds" {
  name                = "vnet-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  address_space       = [var.cidr_vnet]
  tags                = local.etiquettes
}

resource "azurerm_subnet" "warehouse" {
  name                 = "snet-warehouse"
  resource_group_name  = azurerm_resource_group.eds.name
  virtual_network_name = azurerm_virtual_network.eds.name
  address_prefixes     = [var.cidr_warehouse]
}

# Les jobs vivent dans le réseau : ils joignent l'entrepôt par son adresse privée,
# et le trafic ne sort jamais sur Internet. C'est ce qui permet à la règle NSG
# `allow-jobs-clickhouse` d'avoir pour source un sous-réseau plutôt qu'`Internet`.
resource "azurerm_subnet" "jobs" {
  name                 = "snet-jobs"
  resource_group_name  = azurerm_resource_group.eds.name
  virtual_network_name = azurerm_virtual_network.eds.name
  address_prefixes     = [var.cidr_jobs]

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# ── Filtrage ────────────────────────────────────────────────────────────────
# Ordre de lecture : ce qui est ouvert, à qui, et pourquoi. Tout le reste tombe
# dans le refus explicite de priorité 4096.
resource "azurerm_network_security_group" "warehouse" {
  name                = "nsg-warehouse-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  tags                = local.etiquettes

  security_rule {
    name                       = "allow-ssh-admin"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefixes    = local.admin_cidrs
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "22"
    description                = "Administration et tunnel vers la console SQL"
  }

  security_rule {
    name                       = "allow-https"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefixes    = var.metabase_allowed_cidrs
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "443"
    description                = "Tableaux de bord Metabase, derriere Caddy"
  }

  security_rule {
    name                       = "allow-http-redirect"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefixes    = var.metabase_allowed_cidrs
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "80"
    description                = "Redirection vers HTTPS et validation ACME"
  }

  security_rule {
    name                       = "allow-jobs-clickhouse"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = var.cidr_jobs
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "8123"
    description                = "Le pipeline pilote l entrepot depuis le sous-reseau des jobs"
  }

  security_rule {
    name                       = "allow-jobs-metabase"
    priority                   = 210
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = var.cidr_jobs
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "3000"
    description                = "Provisionnement Metabase par l API, depuis le job"
  }

  # Ouverture optionnelle de la console SQL. Fermée par défaut : un entrepôt de
  # santé n'a pas à écouter sur Internet, et le tunnel SSH suffit.
  dynamic "security_rule" {
    for_each = var.expose_clickhouse_to_admin ? [1] : []
    content {
      name                       = "allow-admin-clickhouse"
      priority                   = 220
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_address_prefixes    = local.admin_cidrs
      source_port_range          = "*"
      destination_address_prefix = "*"
      destination_port_range     = "8123"
      description                = "Console SQL ouverte a l administration (option)"
    }
  }

  # Azure refuse déjà tout ce qui n'est pas explicitement autorisé. Cette règle ne
  # change donc rien au comportement — elle rend le refus lisible dans le portail,
  # à côté des autorisations, plutôt qu'implicite.
  security_rule {
    name                       = "deny-all-inbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "*"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
    description                = "Refus explicite de tout le reste"
  }
}

resource "azurerm_subnet_network_security_group_association" "warehouse" {
  subnet_id                 = azurerm_subnet.warehouse.id
  network_security_group_id = azurerm_network_security_group.warehouse.id
}

resource "azurerm_public_ip" "eds" {
  name                = "pip-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = local.nom_dns
  tags                = local.etiquettes
}

resource "azurerm_network_interface" "vm" {
  name                = "nic-warehouse-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  tags                = local.etiquettes

  ip_configuration {
    name      = "interne"
    subnet_id = azurerm_subnet.warehouse.id
    # Adresse privée **statique** : c'est celle que les jobs utilisent pour
    # joindre ClickHouse et Metabase. Une adresse dynamique changerait au
    # redémarrage de la VM et casserait le pipeline sans prévenir.
    private_ip_address_allocation = "Static"
    private_ip_address            = local.ip_privee_vm
    public_ip_address_id          = azurerm_public_ip.eds.id
  }
}
