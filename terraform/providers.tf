# AzureRM 5.x (sorti le 27 juillet 2026) impose deux choses qui n'existaient pas en 4.x :
#
#   * `subscription_id` explicite — plus d'abonnement déduit du contexte `az` ;
#   * `resource_provider_registrations` par défaut à `none`.
#
# Le second point est volontairement conservé : enregistrer un fournisseur est une
# opération d'abonnement, lente et à droits élevés, qui n'a rien à faire dans le
# cycle de vie d'une infrastructure. `make cloud-bootstrap` s'en charge une fois.

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"

  features {
    key_vault {
      # Le coffre porte le sel de pseudonymisation : la seule chose du projet qui
      # ne soit pas reconstructible. On ne purge jamais à la destruction — un
      # `terraform destroy` malheureux doit rester rattrapable.
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    storage {
      # Le provider interroge par défaut les propriétés des services Blob, File, Queue
      # et Table d'un compte de stockage, par leur plan de données. Sur cet abonnement,
      # le service **Fichiers** n'existe pas — `az storage account
      # file-service-properties show` répond `ResourceNotFound` — et la lecture échoue
      # en 400, ce qui bloque la création du compte alors qu'il est parfaitement sain.
      #
      # Le projet n'utilise aucun partage de fichiers : uniquement des blobs, gérés par
      # le plan de contrôle (conteneurs, rétention, site statique). Couper ces appels ne
      # retire donc aucune fonctionnalité, et supprime une dépendance à un service dont
      # nous n'avons pas besoin.
      data_plane_available = false
    }

    virtual_machine {
      # Le disque OS suit la VM : il ne contient que du reconstructible
      # le laisser derrière ne ferait que coûter.
      delete_os_disk_on_deletion = true
    }
  }
}
