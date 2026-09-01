resource "azurerm_log_analytics_workspace" "eds" {
  name                = "log-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  # Garde-fou de coût : un pipeline qui partirait en boucle ne peut pas faire
  # exploser la facture d'ingestion. Un demi-gigaoctet par jour est deux ordres de
  # grandeur au-dessus de ce que le projet produit.
  daily_quota_gb = 0.5

  tags = local.etiquettes
}
