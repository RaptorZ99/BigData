# Identité des trois jobs. Assignée par l'utilisateur (et non par le système) pour
# que les attributions de rôles existent **avant** la création des jobs : une
# identité système ne naît qu'avec la ressource qui la porte, ce qui interdit de
# lui donner des droits en amont.
resource "azurerm_user_assigned_identity" "pipeline" {
  name                = "id-pipeline-${local.prefixe}"
  resource_group_name = azurerm_resource_group.eds.name
  location            = azurerm_resource_group.eds.location
  tags                = local.etiquettes
}
