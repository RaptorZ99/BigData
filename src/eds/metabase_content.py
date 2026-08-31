"""Contenu des dashboards : requêtes, visualisations et disposition.

Séparé du code de provisionnement pour que la définition métier des tableaux de
bord reste lisible et modifiable sans toucher à la mécanique d'API.

Chaque requête est un simple `SELECT` sur une table gold : la logique de calcul
appartient à l'entrepôt, l'outil de restitution ne fait qu'afficher. Un chiffre
du dashboard est donc toujours retrouvable en SQL, ce qui est exactement ce
qu'on veut pouvoir démontrer.

La grille Metabase fait 24 colonnes de large.
"""

from __future__ import annotations

# ── Dashboard 1 : pilotage hospitalier ──────────────────────────────────────

_PILOTAGE_CARDS = [
    {
        "kind": "text",
        "text": (
            "## 🏥 Pilotage hospitalier\n"
            "Activité, qualité des soins et surveillance des patients. "
            "Chaque indicateur est calculé dans l'entrepôt et traçable jusqu'au fichier source."
        ),
        "row": 0,
        "col": 0,
        "size_x": 24,
        "size_y": 2,
    },
    {
        "name": "Séjours pris en charge",
        "description": "Séjours valides sur la période, après contrôles qualité.",
        "display": "scalar",
        "sql": "SELECT nb_sejours FROM kpi_synthese",
        "row": 2,
        "col": 0,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Durée moyenne de séjour (jours)",
        "description": "DMS globale, calculée sur les seuls séjours terminés.",
        "display": "scalar",
        "sql": "SELECT dms_globale_jours FROM kpi_synthese",
        "row": 2,
        "col": 5,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Taux de réadmission à 30 jours (%)",
        "description": "Sorties vivantes suivies d'une réadmission dans les 30 jours.",
        "display": "scalar",
        "sql": "SELECT taux_readmission_pct FROM kpi_synthese",
        "row": 2,
        "col": 10,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Relevés en alerte (%)",
        "description": "Part des constantes hors seuils cliniques (FC, SpO2, température).",
        "display": "scalar",
        "sql": "SELECT pct_releves_alerte FROM kpi_synthese",
        "row": 2,
        "col": 15,
        "size_x": 4,
        "size_y": 3,
    },
    {
        "name": "Séjours en cours",
        "description": "Patients encore hospitalisés (sortie non renseignée).",
        "display": "scalar",
        "sql": "SELECT nb_sejours_en_cours FROM kpi_synthese",
        "row": 2,
        "col": 19,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Durée moyenne de séjour par service",
        "description": "DMS pondérée par le nombre de sorties, sur les séjours terminés.",
        "display": "bar",
        "sql": (
            "SELECT service_label AS service,\n"
            "       round(sum(dms_jours * nb_sorties) / sum(nb_sorties), 2) AS dms_jours\n"
            "FROM kpi_dms_service\n"
            "GROUP BY service\n"
            "ORDER BY dms_jours DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["dms_jours"],
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Jours",
        },
        "row": 5,
        "col": 0,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Activité des urgences par jour",
        "description": (
            "Deux lectures : passages par le service des urgences, "
            "et admissions en mode urgence tous services confondus."
        ),
        "display": "line",
        "sql": (
            "SELECT admission_date AS jour,\n"
            "       nb_passages_service_urgences AS `Passages service Urgences`,\n"
            "       nb_admissions_mode_urgence   AS `Admissions en mode urgence`\n"
            "FROM kpi_urgences_jour\n"
            "ORDER BY jour"
        ),
        "visualization_settings": {
            "graph.dimensions": ["jour"],
            "graph.metrics": ["Passages service Urgences", "Admissions en mode urgence"],
            "graph.x_axis.title_text": "Jour d'admission",
            "graph.y_axis.title_text": "Nombre",
        },
        "row": 5,
        "col": 12,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Taux de réadmission à 30 jours par service",
        "description": "Indicateur de qualité des soins : plus il est bas, mieux c'est.",
        "display": "bar",
        "sql": (
            "SELECT service_label AS service,\n"
            "       sum(sorties_eligibles) AS sorties,\n"
            "       sum(readmissions_30j)  AS readmissions,\n"
            "       round(100.0 * sum(readmissions_30j) / sum(sorties_eligibles), 2) AS taux_pct\n"
            "FROM kpi_readmissions_30j\n"
            "GROUP BY service\n"
            "ORDER BY taux_pct DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["taux_pct"],
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Taux de réadmission (%)",
        },
        "row": 11,
        "col": 0,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Relevés de constantes en alerte par jour",
        "description": "Surveillance des patients de réanimation et de cardiologie.",
        "display": "line",
        "sql": (
            "SELECT releve_date AS jour, service_label AS service, nb_alertes\n"
            "FROM kpi_alertes_monitoring\n"
            "ORDER BY jour, service"
        ),
        "visualization_settings": {
            "graph.dimensions": ["jour", "service"],
            "graph.metrics": ["nb_alertes"],
            "graph.x_axis.title_text": "Jour",
            "graph.y_axis.title_text": "Relevés en alerte",
        },
        "row": 11,
        "col": 12,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Nature des alertes par service",
        "description": (
            "Nombre d'alertes par type. Un même relevé pouvant déclencher plusieurs "
            "alertes, le total dépasse le nombre de relevés en alerte."
        ),
        "display": "bar",
        "sql": (
            "SELECT service_label AS service,\n"
            "       sum(nb_alertes_frequence_cardiaque) AS `Fréquence cardiaque`,\n"
            "       sum(nb_alertes_saturation)          AS `Saturation (SpO2)`,\n"
            "       sum(nb_alertes_temperature)         AS `Température`\n"
            "FROM kpi_alertes_monitoring\n"
            "GROUP BY service\n"
            "ORDER BY service"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["Fréquence cardiaque", "Saturation (SpO2)", "Température"],
            # Barres groupées et non empilées : un relevé peut déclencher
            # plusieurs alertes, un empilement laisserait croire à un total.
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Nombre d'alertes",
        },
        "row": 17,
        "col": 0,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Modes d'admission et de sortie",
        "description": "Répartition quotidienne des flux d'entrée et de sortie.",
        "display": "bar",
        "sql": (
            "SELECT concat(sens, ' — ', mode) AS flux, sum(nb_sejours) AS nb_sejours\n"
            "FROM kpi_flux\n"
            "GROUP BY flux\n"
            "ORDER BY nb_sejours DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["flux"],
            "graph.metrics": ["nb_sejours"],
            "graph.x_axis.title_text": "Flux",
            "graph.y_axis.title_text": "Nombre de séjours",
        },
        "row": 17,
        "col": 12,
        "size_x": 12,
        "size_y": 6,
    },
    {
        "name": "Activité quotidienne par service",
        "description": "Entrées, sorties, décès et charge (séjours ouverts) par service.",
        "display": "table",
        "sql": (
            "SELECT jour, service_label AS service, admissions, sorties, deces,\n"
            "       sejours_en_cours AS `séjours ouverts`\n"
            "FROM kpi_activite_service\n"
            "ORDER BY jour DESC, service"
        ),
        "row": 23,
        "col": 0,
        "size_x": 24,
        "size_y": 7,
    },
    {
        "kind": "text",
        "text": (
            "### 🔎 Fiabilité des chiffres\n"
            "Toute ligne écartée par un contrôle qualité est comptée ici et reste "
            "consultable dans l'entrepôt : aucun chiffre du dashboard n'est le "
            "résultat d'une suppression silencieuse."
        ),
        "row": 30,
        "col": 0,
        "size_x": 24,
        "size_y": 3,
    },
    {
        "name": "Contrôles qualité du dernier traitement",
        "description": (
            "Règle par règle : lignes lues, conservées, écartées (retirées) "
            "et signalées (conservées mais marquées)."
        ),
        "display": "table",
        "sql": (
            "SELECT controle, nature,\n"
            "       lignes_lues       AS `lues`,\n"
            "       lignes_conservees AS `conservées`,\n"
            "       lignes_ecartees   AS `écartées`,\n"
            "       lignes_signalees  AS `signalées`\n"
            "FROM kpi_qualite_pipeline\n"
            "ORDER BY `écartées` DESC, `signalées` DESC, controle"
        ),
        "row": 33,
        "col": 0,
        "size_x": 24,
        "size_y": 8,
    },
    {
        "name": "Traçabilité de l'ingestion",
        "description": "Chaque fichier déposé par le CHU, son jour et son volume chargé.",
        "display": "table",
        "sql": (
            "SELECT ingest_date AS `jour de dépôt`, domaine, fichier_source AS fichier,\n"
            "       lignes_chargees AS `lignes chargées`, statut, traite_le AS `traité le`\n"
            "FROM kpi_ingestion\n"
            "ORDER BY `jour de dépôt` DESC, domaine"
        ),
        "row": 41,
        "col": 0,
        "size_x": 24,
        "size_y": 7,
    },
]


# ── Dashboard 2 : recherche clinique ────────────────────────────────────────

_RECHERCHE_CARDS = [
    {
        "kind": "text",
        "text": (
            "## 🔬 Recherche clinique\n"
            "Cohortes de patients par pathologie et description démographique.\n\n"
            "**Données pseudonymisées et agrégées.** Aucune information "
            "identifiante n'est accessible depuis cet espace, et toute cellule "
            "regroupant moins de 5 patients est retirée de la diffusion."
        ),
        "row": 0,
        "col": 0,
        "size_x": 24,
        "size_y": 4,
    },
    {
        "name": "Taille des cohortes par pathologie",
        "description": "Nombre de patients distincts concernés par chaque diagnostic CIM-10.",
        "display": "bar",
        "sql": (
            "SELECT libelle AS pathologie, nb_patients\n"
            "FROM cohorte_pathologie\n"
            "ORDER BY nb_patients DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["pathologie"],
            "graph.metrics": ["nb_patients"],
            "graph.x_axis.title_text": "Pathologie (CIM-10)",
            "graph.y_axis.title_text": "Patients",
        },
        "row": 4,
        "col": 0,
        "size_x": 12,
        "size_y": 7,
    },
    {
        "name": "Prévalence par pathologie",
        "description": "Part des patients de l'entrepôt concernés par chaque pathologie.",
        "display": "bar",
        "sql": (
            "SELECT libelle AS pathologie, prevalence_pct AS `prévalence (%)`\n"
            "FROM prevalence_pathologie\n"
            "ORDER BY `prévalence (%)` DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["pathologie"],
            "graph.metrics": ["prévalence (%)"],
            "graph.x_axis.title_text": "Pathologie (CIM-10)",
            "graph.y_axis.title_text": "Prévalence (%)",
        },
        "row": 4,
        "col": 12,
        "size_x": 12,
        "size_y": 7,
    },
    {
        "name": "Distribution par âge et sexe",
        "description": (
            "Pyramide des âges de la population suivie, patients comptés une seule fois."
        ),
        "display": "bar",
        # Lue depuis la table au grain sexe × âge, et non agrégée depuis la vue
        # par pathologie : `nb_patients` n'est pas additif, un patient portant
        # plusieurs diagnostics y serait compté autant de fois.
        "sql": (
            "SELECT tranche_age AS `tranche d'âge`,\n"
            "       sumIf(nb_patients, sexe = 'F') AS Femmes,\n"
            "       sumIf(nb_patients, sexe = 'M') AS Hommes\n"
            "FROM cohorte_demographie_globale\n"
            "GROUP BY `tranche d'âge`, tranche_age_debut\n"
            "ORDER BY tranche_age_debut"
        ),
        "visualization_settings": {
            "graph.dimensions": ["tranche d'âge"],
            "graph.metrics": ["Femmes", "Hommes"],
            "stackable.stack_type": "stacked",
            "graph.x_axis.title_text": "Tranche d'âge",
            "graph.y_axis.title_text": "Patients",
        },
        "row": 11,
        "col": 0,
        "size_x": 12,
        "size_y": 7,
    },
    {
        "name": "Répartition par sexe et pathologie",
        "description": "Composition des cohortes par sexe.",
        "display": "bar",
        "sql": (
            "SELECT libelle AS pathologie,\n"
            "       sumIf(nb_patients, sexe = 'F') AS Femmes,\n"
            "       sumIf(nb_patients, sexe = 'M') AS Hommes\n"
            "FROM cohorte_demographie\n"
            "GROUP BY pathologie\n"
            "ORDER BY pathologie"
        ),
        "visualization_settings": {
            "graph.dimensions": ["pathologie"],
            "graph.metrics": ["Femmes", "Hommes"],
            "stackable.stack_type": "stacked",
            "graph.x_axis.title_text": "Pathologie",
            "graph.y_axis.title_text": "Patients",
        },
        "row": 11,
        "col": 12,
        "size_x": 12,
        "size_y": 7,
    },
    {
        "name": "Description détaillée des cohortes",
        "description": "Pathologie × sexe × tranche d'âge — cellules d'au moins 5 patients.",
        "display": "table",
        "sql": (
            "SELECT libelle AS pathologie, sexe, tranche_age AS `tranche d'âge`, nb_patients\n"
            "FROM cohorte_demographie\n"
            "ORDER BY pathologie, sexe, tranche_age_debut"
        ),
        "row": 18,
        "col": 0,
        "size_x": 14,
        "size_y": 7,
    },
    {
        "kind": "text",
        "text": (
            "### 🔒 Protection des petits effectifs\n"
            "Au grain le plus fin (pathologie × sexe × tranche d'âge × département), "
            "certaines cellules descendent sous le seuil de 5 patients : elles sont "
            "**supprimées de la diffusion**, car un effectif aussi faible pourrait "
            "permettre de ré-identifier une personne.\n\n"
            "Le compteur ci-dessous mesure cet effet à chaque traitement."
        ),
        "row": 18,
        "col": 14,
        "size_x": 10,
        "size_y": 6,
    },
    {
        "name": "Cellules retirées de la diffusion (seuil k = 5)",
        "description": "Effet mesuré du k-anonymat sur la vue démographique la plus fine.",
        "display": "table",
        "sql": (
            "SELECT cellules_calculees  AS `cellules calculées`,\n"
            "       cellules_diffusees  AS `cellules diffusées`,\n"
            "       cellules_supprimees AS `cellules supprimées`,\n"
            "       seuil_k             AS `seuil k`\n"
            "FROM k_anonymat_controle"
        ),
        "row": 24,
        "col": 14,
        "size_x": 10,
        "size_y": 3,
    },
    {
        "name": "Cohortes par département (grain fin, k >= 5)",
        "description": "Vue la plus détaillée diffusable, après suppression des petits effectifs.",
        "display": "table",
        "sql": (
            "SELECT libelle AS pathologie, region_code AS `département`, sexe,\n"
            "       tranche_age AS `tranche d'âge`, nb_patients\n"
            "FROM cohorte_demographie_region\n"
            "ORDER BY pathologie, `département`, sexe, tranche_age_debut"
        ),
        "row": 27,
        "col": 0,
        "size_x": 24,
        "size_y": 7,
    },
]


DASHBOARDS: dict[str, dict] = {
    "pilotage": {
        "name": "🏥 Pilotage hospitalier",
        "description": (
            "Activité, durées de séjour, réadmissions et surveillance des constantes. "
            "Destiné à la direction et aux cadres de santé."
        ),
        "cards": _PILOTAGE_CARDS,
    },
    "recherche": {
        "name": "🔬 Recherche clinique",
        "description": (
            "Cohortes par pathologie et description démographique, sur données "
            "pseudonymisées et agrégées (seuil de diffusion : 5 patients)."
        ),
        "cards": _RECHERCHE_CARDS,
    },
}
