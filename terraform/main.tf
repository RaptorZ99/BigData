resource "azurerm_resource_group" "eds" {
  name     = "rg-${local.prefixe}"
  location = var.location
  tags     = local.etiquettes
}

# ── Contrôles de cohérence, évalués au `plan` ───────────────────────────────
# Un bloc `check` produit un avertissement, pas une erreur : il signale une
# configuration probablement involontaire sans bloquer un déploiement délibéré.

check "extinction_sans_demarrage" {
  assert {
    condition     = var.auto_shutdown_time == "" || var.auto_startup_cron != ""
    error_message = <<-TXT
      `auto_shutdown_time` est défini mais pas `auto_startup_cron` : la VM s'éteindra
      chaque soir et **restera éteinte** jusqu'à un `make cloud-start` manuel. Azure ne
      propose pas de démarrage planifié pour une VM autonome — c'est le job
      `job-eds-reveil` qui joue ce rôle ici. Renseignez `auto_startup_cron`, ou assumez
      le redémarrage manuel.
    TXT
  }
}

locals {
  # Heure de déclenchement du pipeline, extraite du deuxième champ du cron (UTC).
  # `try` : un cron du type "0 */6 * * *" n'a pas d'heure unique — on renonce alors au
  # contrôle plutôt que de faire échouer le plan sur une configuration légitime.
  heure_pipeline_utc = try(tonumber(split(" ", var.pipeline_cron)[1]), null)

  # Fenêtre pendant laquelle la VM est allumée, ramenée en UTC. `auto_shutdown_time` est
  # en heure de Paris ; on retranche 2 h (heure d'été). Le contrôle est indicatif : un
  # décalage d'une heure en hiver ne le rend pas faux pour autant.
  heure_reveil_utc = try(tonumber(split(" ", var.auto_startup_cron)[1]), null)
  heure_arret_utc  = try(tonumber(substr(var.auto_shutdown_time, 0, 2)) - 2, null)
}

check "pipeline_hors_fenetre_dextinction" {
  assert {
    # Le pipeline doit se déclencher entre le réveil et l'extinction. Le contrôle est
    # sauté si l'une des trois heures n'est pas exploitable (cron en intervalle, mode
    # nuit désactivé) : mieux vaut ne rien dire que dire faux.
    condition = (
      var.auto_shutdown_time == "" ||
      local.heure_pipeline_utc == null ||
      local.heure_reveil_utc == null ||
      local.heure_arret_utc == null ||
      (local.heure_pipeline_utc >= local.heure_reveil_utc &&
      local.heure_pipeline_utc < local.heure_arret_utc)
    )
    error_message = <<-TXT
      Le pipeline est planifié dans la fenêtre d'extinction : il se déclencherait sans
      entrepôt à joindre et échouerait chaque nuit. Décalez `pipeline_cron` dans les
      heures où la VM est allumée — par exemple "30 7 * * *" (09 h 30 à Paris) pour une
      extinction à 22 h. Rappel : `pipeline_cron` est en **UTC**, `auto_shutdown_time`
      en heure de Paris.
    TXT
  }
}
