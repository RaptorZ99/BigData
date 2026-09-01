# Le crédit étudiant est fini. Trois filets, du plus souple au plus dur :
#
#   1. ces alertes préviennent ;
#   2. `make cloud-stop` ramène la facture à ~5 €/mois en une commande ;
#   3. la limite de dépense de l'offre étudiante désactive les ressources à crédit
#      épuisé — la facturation ne peut pas devenir négative.
#
# Sans destinataire, aucun budget n'est créé : une alerte qui ne part nulle part
# n'est pas une alerte.
resource "azurerm_consumption_budget_subscription" "eds" {
  count = length(var.budget_contact_emails) > 0 ? 1 : 0

  name            = "budget-${local.prefixe}"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.budget_amount_eur
  time_grain      = "Monthly"

  time_period {
    # Un budget mensuel démarre au premier du mois courant.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  # 50 % : informatif. 80 % : il est temps d'éteindre entre deux démonstrations.
  # 100 % : dépassement, la suite est facturée sur le crédit restant.
  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.budget_contact_emails
    }
  }

  lifecycle {
    # `timestamp()` change à chaque plan : sans cela, la date de début ferait
    # apparaître une modification à chaque exécution.
    ignore_changes = [time_period]
  }
}
