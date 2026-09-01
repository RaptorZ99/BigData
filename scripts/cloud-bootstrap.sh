#!/usr/bin/env bash
# Amorçage du déploiement Azure — à exécuter une seule fois par abonnement.
#
# Deux choses que Terraform ne peut pas faire lui-même :
#
#   1. **Enregistrer les fournisseurs.** AzureRM 5.0 n'en enregistre plus aucun
#      par défaut, et c'est une opération d'abonnement, lente et à droits élevés,
#      qui n'a rien à faire dans le cycle de vie d'une infrastructure.
#   2. **Créer le stockage de son propre état.** Le socle de l'état ne peut pas
#      être géré par l'état qu'il héberge.
set -euo pipefail

RG_ETAT="rg-eds-tfstate"
CONTENEUR="tfstate"
# Une policy d'abonnement restreint les régions déployables ; swedencentral en fait
# partie et c'est la moins chère des deux qui proposent la série B (cf. terraform/variables.tf).
REGION="${AZURE_LOCATION:-swedencentral}"

echo "→ Abonnement"
SUB=$(az account show --query id -o tsv)
echo "   $SUB  ($(az account show --query name -o tsv))"

echo "→ Enregistrement des fournisseurs (quelques minutes au premier passage)"
for P in Microsoft.App Microsoft.OperationalInsights Microsoft.KeyVault \
         Microsoft.Storage Microsoft.Network Microsoft.Compute \
         Microsoft.ManagedIdentity Microsoft.Consumption Microsoft.DevTestLab; do
  ETAT=$(az provider show -n "$P" --query registrationState -o tsv 2>/dev/null || echo Unknown)
  if [ "$ETAT" != "Registered" ]; then
    echo "   $P : $ETAT → enregistrement"
    az provider register -n "$P" --wait
  else
    echo "   $P : déjà enregistré"
  fi
done

echo "→ Stockage de l'état Terraform"
# Un groupe existant garde sa région : `az group create` échoue si on lui en demande
# une autre. Cas rencontré pour de vrai — un premier passage dans une région refusée
# par la policy d'abonnement laisse le groupe derrière lui. On s'aligne sur l'existant
# plutôt que d'échouer sur un détail sans conséquence.
EXISTANT=$(az group show -n "$RG_ETAT" --query location -o tsv 2>/dev/null || true)
if [ -n "$EXISTANT" ] && [ "$EXISTANT" != "$REGION" ]; then
  echo "   groupe déjà en $EXISTANT : on conserve cette région pour l'état"
  REGION="$EXISTANT"
fi
az group create -n "$RG_ETAT" -l "$REGION" -o none

# Nom déterministe, dérivé de l'abonnement : rejouer ce script ne crée pas un
# second compte, et deux personnes sur le même abonnement retombent sur le même.
COMPTE="stedstf$(echo -n "$SUB" | shasum | cut -c1-12)"
if ! az storage account show -n "$COMPTE" -g "$RG_ETAT" -o none 2>/dev/null; then
  az storage account create -n "$COMPTE" -g "$RG_ETAT" -l "$REGION" \
    --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false -o none
fi

# Versionné : un état écrasé par erreur reste récupérable.
az storage account blob-service-properties update \
  --account-name "$COMPTE" -g "$RG_ETAT" --enable-versioning true -o none

# Être propriétaire de l'abonnement ne donne PAS accès aux données d'un compte de
# stockage : le plan de contrôle et le plan de données ont des rôles distincts. Sans
# cette attribution, `terraform init` échoue en 403 AuthorizationPermissionMismatch,
# alors même qu'on a tous les droits sur la ressource.
MOI=$(az ad signed-in-user show --query id -o tsv)
PORTEE=$(az storage account show -n "$COMPTE" -g "$RG_ETAT" --query id -o tsv)
az role assignment create --assignee-object-id "$MOI" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$PORTEE" -o none 2>/dev/null || true

# `--auth-mode login` : identité Entra ID, aucune clé de compte ne circule.
# Quelques tentatives : la propagation du rôle ci-dessus n'est pas instantanée.
for _ in 1 2 3 4 5 6 7 8; do
  az storage container create --account-name "$COMPTE" -n "$CONTENEUR" \
    --auth-mode login -o none 2>/dev/null && break
  sleep 10
done

cat > terraform/backend.hcl <<EOF
resource_group_name  = "$RG_ETAT"
storage_account_name = "$COMPTE"
container_name       = "$CONTENEUR"
key                  = "eds-chu.tfstate"
EOF

if [ ! -f terraform/terraform.tfvars ]; then
  sed "s|00000000-0000-0000-0000-000000000000|$SUB|" \
    terraform/terraform.tfvars.example > terraform/terraform.tfvars
  echo "   terraform/terraform.tfvars créé (abonnement pré-rempli)"
fi

echo
echo "✓ Amorçage terminé. Suite :"
echo "    terraform -chdir=terraform init -backend-config=backend.hcl"
echo "    make cloud-plan && make cloud-apply"
