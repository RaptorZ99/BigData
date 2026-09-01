locals {
  # Suffixe stable, dérivé de l'abonnement et du projet : deux déploiements de ce
  # dépôt sur le même abonnement ne se marchent pas dessus, et le nom ne change
  # pas d'un `apply` à l'autre.
  suffixe = substr(sha1("${var.subscription_id}-${var.projet}-${var.environnement}"), 0, 8)

  prefixe = "${var.projet}-${var.environnement}"

  # Le compte de stockage et le coffre ont des noms globalement uniques et un
  # alphabet restreint (minuscules et chiffres pour l'un, tirets tolérés pour l'autre).
  nom_stockage = "steds${local.suffixe}"
  nom_coffre   = "kv-eds-${local.suffixe}"
  nom_dns      = "eds-chu-${local.suffixe}"

  # Adresse d'administration : celle fournie, ou l'adresse publique du poste qui
  # lance `terraform apply`. Sans ce repli, la règle SSH serait soit absente,
  # soit ouverte à Internet — deux mauvaises réponses.
  admin_cidrs = length(var.admin_source_cidrs) > 0 ? var.admin_source_cidrs : [
    "${chomp(data.http.ip_publique[0].response_body)}/32"
  ]

  # Nom de domaine servi par Caddy. Sans nom propre, on prend celui d'Azure et un
  # certificat interne : Let's Encrypt sature sur `*.cloudapp.azure.com`, dont le
  # quota d'émission est partagé entre tous les clients (cf. PLAN-CLOUD.md §5.5).
  hote_azure = "${local.nom_dns}.${var.location}.cloudapp.azure.com"
  hote_site  = var.acme_hostname != "" ? var.acme_hostname : local.hote_azure
  # Directive TLS de Caddy : vide = certificat Let's Encrypt automatique.
  directive_tls = var.acme_hostname != "" ? "" : "tls internal"

  ip_privee_vm = cidrhost(var.cidr_warehouse, 10)

  etiquettes = merge({
    projet      = var.projet
    environment = var.environnement
    gere_par    = "terraform"
    # Données de santé : l'étiquette rappelle à quiconque parcourt le portail que
    # ce périmètre relève de l'article 9 du RGPD.
    donnees = "sante-article-9"
  }, var.etiquettes)
}

data "http" "ip_publique" {
  count = length(var.admin_source_cidrs) > 0 ? 0 : 1
  url   = "https://api.ipify.org"
}

# ── Budget mémoire de la VM ─────────────────────────────────────────────────
# Réparti à partir de la RAM réelle de la taille choisie. Il ne s'agit pas de
# réglages cosmétiques : sans limites, ClickHouse dimensionne ses caches sur la
# mémoire visible et se fait arrêter par le noyau à la première requête un peu
# large — sur une machine partagée avec une JVM, c'est une question de minutes.
locals {
  ram_mo = {
    "Standard_B2ts_v2"  = 1024
    "Standard_B2ats_v2" = 1024
    "Standard_B2pts_v2" = 1024
    "Standard_B2ls_v2"  = 4096
    "Standard_B2als_v2" = 4096
    "Standard_B2pls_v2" = 4096
    "Standard_B2s_v2"   = 8192
    "Standard_B2as_v2"  = 8192
  }
  ram_disponible = lookup(local.ram_mo, var.vm_size, 4096)

  # ~350 Mo pour Ubuntu et Docker, le reste partagé : 45 % à ClickHouse, 35 % à
  # Metabase, le solde en marge. Caddy tient dans 64 Mo.
  budget_conteneurs  = local.ram_disponible - 350
  memoire_clickhouse = floor(local.budget_conteneurs * 0.45)
  memoire_metabase   = floor(local.budget_conteneurs * 0.35)
  # Le tas de la JVM, sous la limite du conteneur : il faut de la place pour le
  # métaspace et les piles, sinon le conteneur est tué avant que la JVM ne le voie.
  xmx_metabase = floor(local.memoire_metabase * 0.7)

  # ClickHouse se borne lui-même en plus de la limite Docker : arrêter une requête
  # avec un message clair vaut mieux que se faire tuer par le noyau sans trace.
  memoire_serveur_clickhouse = floor(local.memoire_clickhouse * 0.8) * 1024 * 1024
  # Défaut ClickHouse : 5 Gio. Sur cette machine, ce seul cache suffirait à la remplir.
  cache_marques_clickhouse = 268435456
}
