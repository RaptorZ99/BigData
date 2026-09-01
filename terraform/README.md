# Terraform — infrastructure Azure de l'EDS

Toute l'infrastructure du déploiement Azure. Rien ne se crée à la main ;
`terraform destroy` ne laisse rien derrière.

Le mode d'emploi complet est dans [`docs/CLOUD.md`](../docs/CLOUD.md) ; les choix
d'architecture et leur justification dans
[`docs/PLAN-CLOUD.md`](../docs/PLAN-CLOUD.md).

## Démarrage

```bash
make cloud-bootstrap                                        # une seule fois
make image-push                                             # l'image que les jobs exécutent
terraform -chdir=terraform init -backend-config=backend.hcl
make cloud-plan && make cloud-apply
```

Mode d'emploi détaillé, vérifications et reprise sur incident :
[`docs/CLOUD.md`](../docs/CLOUD.md).

## Organisation

| Fichier | Contenu |
|---|---|
| `main.tf` | Groupe de ressources, et deux `check` qui avertissent d'une planification incohérente |
| `providers.tf` | AzureRM 5.x : `subscription_id` obligatoire, aucun fournisseur auto-enregistré |
| `backend.tf` | État distant, authentifié par identité Entra ID |
| `variables.tf` | 28 variables, toutes documentées, toutes avec un défaut sûr |
| `locals.tf` | Nommage, adresses, **budget mémoire de la VM** déduit de sa taille |
| `network.tf` | Réseau, deux sous-réseaux, groupe de sécurité, IP publique |
| `storage.tf` | Compte de blobs versionné, conteneurs, jeton SAS, **droits par conteneur** |
| `keyvault.tf` | Coffre en RBAC, huit secrets générés |
| `identity.tf` | Identité gérée des jobs |
| `vm.tf` | VM, cloud-init, extinction planifiée, job de réveil et son rôle sur mesure |
| `containerapp.tf` | Environnement dans le réseau, trois jobs |
| `observability.tf` | Log Analytics, quota d'ingestion journalier |
| `budget.tf` | Budget d'abonnement, alertes à 50 / 80 / 100 % |
| `outputs.tf` | URL, adresses, commandes prêtes à coller |
| `cloud-init/` | Gabarits déposés sur la VM : compose, Caddyfile, XML ClickHouse |

## Les variables qui comptent

| Variable | Défaut | Effet |
|---|---|---|
| `subscription_id` | — | **Seule variable obligatoire** |
| `vm_size` | `Standard_B2als_v2` | 2 vCPU / 4 Gio, 24,38 €/mois |
| `location` | `swedencentral` | Une policy d'abonnement restreint les régions ; parmi celles autorisées, c'est la moins chère qui propose la série B |
| `auto_shutdown_time` | `""` | Arrêt du soir, heure de Paris. **N'éteint que** — à coupler avec `auto_startup_cron` |
| `auto_startup_cron` | `""` | Démarrage du matin, cron **UTC**. Crée `job-eds-reveil` et son rôle sur mesure |
| `acme_hostname` | `""` | Vide = certificat auto-signé ; un domaine = Let's Encrypt |
| `eds_image` | `louis336/eds-chu:latest` | Image **publique** : aucun secret de registre. À épingler sur un commit avant une démonstration |
| `budget_contact_emails` | `[]` | Vide = aucune alerte de budget |
| `metabase_allowed_cidrs` | `["0.0.0.0/0"]` | Restreindre l'accès aux tableaux de bord |

## Ce qui n'est pas ici, et pourquoi

| Absent | Raison |
|---|---|
| Sauvegarde de la VM | Tout ce qu'elle contient se reconstruit en dix minutes |
| Disque de données séparé | Même raison — deux postes de coût pour du reconstructible |
| Points de terminaison privés | Facturés en supplément sur un environnement Container Apps |
| Haute disponibilité | Quota de 6 vCPU par région sur l'offre étudiante : une seule VM |
| Registre d'images privé | Un ACR Basic coûterait 4,35 €/mois pour aucun gain : l'image ne contient que du code, elle est publique |
| Espace de noms hiérarchique (ADLS Gen2) | Azure interdit alors le versioning des blobs, et le dépôt du CHU est la seule chose non reconstructible du système |

## Points de vigilance

- **L'état contient les secrets** (mots de passe générés, URL SAS). Il vit dans un
  conteneur privé, versionné, authentifié par identité. Il ne doit jamais approcher
  Git — `.gitignore` couvre `*.tfstate`, `terraform.tfvars` et `backend.hcl`.
- **`custom_data` de la VM est ignoré après création.** Le modifier recréerait la
  machine à chaque `apply` sans que la modification prenne effet autrement. Les
  évolutions de configuration passent par `systemctl restart eds-stack`, qui relit
  les secrets et redéploie la pile.
- **La propagation RBAC n'est pas instantanée** : une attente explicite de 30 s
  précède l'écriture des secrets. Sans elle, le premier `apply` échoue et le second
  passe — un déploiement qui ne marche qu'à la deuxième tentative n'est pas
  reproductible.
- **Le jeton SAS a une date d'expiration.** Il se renouvelle au `terraform apply`
  suivant, 15 jours avant son terme ; la VM le prend en compte au redémarrage.
- **Le premier `apply` peut échouer sur le compte de stockage.** Le provider en lit le
  plan de données juste après l'avoir créé, avant que la clé ne soit utilisable
  (`AuthenticationFailed`), puis marque la ressource *tainted* — l'`apply` suivant la
  détruit et la recrée, et la boucle se referme. Sortie :
  `terraform untaint azurerm_storage_account.eds`, attendre une minute, réappliquer.
- **`terraform plan` doit rester vide après un `apply`.** Une dérive permanente signale
  un attribut qu'Azure renseigne d'office et que la configuration ne déclare pas — le
  profil de charge `Consumption` des Container Apps, par exemple. Un plan bruyant finit
  par ne plus être lu.
