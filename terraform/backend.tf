# L'état contient les mots de passe générés et l'URL SAS du lake : il ne peut
# rester ni sur le poste, ni approcher Git. Il vit dans un compte de stockage
# privé, créé par `make cloud-bootstrap` — que Terraform ne peut pas créer
# lui-même, faute de pouvoir s'y stocker. Cet amorçage par `az` est délibéré :
# le socle de l'état ne peut pas être géré par l'état qu'il héberge.
#
# `use_azuread_auth` : authentification par identité Entra ID plutôt que par clé
# de compte. Aucune clé de stockage ne circule, ni dans un fichier ni dans un
# secret de CI.
#
# Les valeurs sont fournies à l'initialisation :
#   terraform init -backend-config=backend.hcl
terraform {
  backend "azurerm" {
    use_azuread_auth = true
  }
}
