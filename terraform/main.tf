resource "azurerm_resource_group" "eds" {
  name     = "rg-${local.prefixe}"
  location = var.location
  tags     = local.etiquettes
}
