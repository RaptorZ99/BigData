"""Contenu des dashboards : requêtes, visualisations et disposition.

Séparé du code de provisionnement pour que la définition métier des tableaux de
bord reste lisible et modifiable sans toucher à la mécanique d'API.

Chaque requête est un simple `SELECT` sur une table gold : la logique de calcul
appartient à l'entrepôt, l'outil de restitution ne fait qu'afficher. Un chiffre
du dashboard est donc toujours retrouvable en SQL, ce qui est exactement ce
qu'on veut pouvoir démontrer. Aucune carte ne ré-agrège une table gold pour en
changer le grain : si une vue manque, c'est un modèle qui manque.

La grille Metabase fait 24 colonnes de large, et les tableaux de bord sont
provisionnés en `width: "full"` (cf. `metabase.py`) : la grille occupe donc toute
la largeur de l'écran, sans marge latérale. Quatre règles de mise en page en
découlent, parce qu'elles sont ce qui distingue un tableau de bord lisible d'un
empilement de graphiques :

  * **aucun chevauchement.** Deux cartes qui se recouvrent sont repoussées par
    Metabase à l'affichage, dans un ordre que le code ne contrôle pas — la
    disposition versionnée cesse alors de décrire ce que l'utilisateur voit. Les
    cartes sont donc réparties en bandes horizontales successives, chacune
    occupant les 24 colonnes ;
  * **chaque bande fait exactement 24 colonnes.** Une bande plus étroite laisse
    un vide à droite ; une bande plus large renvoie sa dernière carte à la ligne ;
  * **les titres tiennent dans leur carte.** Une carte offre environ 3,4
    caractères lisibles par colonne de grille — une tuile de quatre colonnes en
    tient treize, une de cinq colonnes dix-sept. Au-delà, Metabase tronque et un
    chiffre sans son titre ne veut plus rien dire. Le nom reste court, la
    définition complète va dans la description, accessible au survol ;
  * **une carte est dimensionnée pour son contenu.** Un graphique respire sur
    huit unités de hauteur, pas six ; une table de cent lignes en demande douze,
    sinon elle impose un défilement interne — invisible sur une capture, et
    pénible à l'usage.

`tests/test_dashboards.py` vérifie ces règles à chaque exécution de la suite
unitaire, sans démarrer Metabase.
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
    # ── Bande 1 · les cinq chiffres clés ────────────────────────────────────
    # Quatre colonnes pour « Séjours », cinq pour les quatre autres : 24 pile.
    # La tuile la plus étroite revient au titre le plus court — l'inverse
    # tronquait « Séjours en cours ».
    {
        "name": "Séjours",
        "description": "Séjours valides sur la période, après contrôles qualité.",
        "display": "scalar",
        "sql": "SELECT nb_sejours FROM kpi_synthese",
        "row": 2,
        "col": 0,
        "size_x": 4,
        "size_y": 3,
    },
    {
        "name": "DMS (jours)",
        "description": (
            "Durée moyenne de séjour, tous services confondus. Calculée sur les seuls "
            "séjours terminés : une durée partielle tirerait la moyenne vers le bas."
        ),
        "display": "scalar",
        "sql": "SELECT dms_globale_jours FROM kpi_synthese",
        "row": 2,
        "col": 4,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Réadmission 30 j",
        "description": (
            "Part (%) des séjours suivis, pour le même patient, d'une nouvelle admission "
            "dans les 30 jours. Indicateur de qualité des soins : plus il est bas, mieux "
            "c'est. Borne basse — voir l'encart plus bas."
        ),
        "display": "scalar",
        "sql": "SELECT taux_readmission_pct FROM kpi_synthese",
        "row": 2,
        "col": 9,
        "size_x": 5,
        "size_y": 3,
    },
    {
        "name": "Alertes (%)",
        "description": (
            "Part des relevés de constantes hors seuils de vigilance : fréquence "
            "cardiaque < 50 ou > 100 bpm, saturation < 92 %, température > 38,5 °C."
        ),
        "display": "scalar",
        "sql": "SELECT pct_releves_alerte FROM kpi_synthese",
        "row": 2,
        "col": 14,
        "size_x": 5,
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
    # ── Bande 2 · durées de séjour et urgences ──────────────────────────────
    {
        "name": "Durée moyenne de séjour par service",
        "description": (
            "KPI 1 — DMS sur les séjours terminés, au grain du service. Lue telle quelle "
            "dans kpi_dms_service : la carte n'agrège rien."
        ),
        "display": "bar",
        "sql": (
            "SELECT service_label AS service, dms_jours\n"
            "FROM kpi_dms_service\n"
            "ORDER BY dms_jours DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["dms_jours"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Jours",
        },
        "row": 5,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Activité des urgences par jour",
        "description": (
            "KPI 3 — Passages dans l'unité URGENCES par jour d'admission, et part encore "
            "présente (sortie non renseignée)."
        ),
        "display": "line",
        "sql": (
            "SELECT admission_date AS jour,\n"
            "       nb_passages        AS `Passages`,\n"
            "       nb_encore_presents AS `Encore présents`\n"
            "FROM kpi_urgences_jour\n"
            "ORDER BY jour"
        ),
        "visualization_settings": {
            "graph.dimensions": ["jour"],
            "graph.metrics": ["Passages", "Encore présents"],
            # Deux séries dans la même unité (des séjours) : un axe unique, sinon
            # deux courbes de hauteur comparable représenteraient des effectifs
            # dans un rapport de 1 à 5.
            "graph.y_axis.auto_split": False,
            "graph.x_axis.title_text": "Jour d'admission",
            "graph.y_axis.title_text": "Séjours",
        },
        "row": 5,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    # ── Bande 3 · surveillance des constantes ───────────────────────────────
    {
        "name": "Relevés de constantes en alerte par jour",
        "description": (
            "KPI 4 — Relevés portant au moins une constante hors seuil de vigilance. "
            "Environ 8 % des relevés sur la période."
        ),
        "display": "line",
        "sql": (
            "SELECT jour, nb_alertes AS `Relevés en alerte`\nFROM kpi_alertes_jour\nORDER BY jour"
        ),
        "visualization_settings": {
            "graph.dimensions": ["jour"],
            "graph.metrics": ["Relevés en alerte"],
            "graph.x_axis.title_text": "Jour",
            "graph.y_axis.title_text": "Relevés en alerte",
        },
        "row": 13,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Nature des alertes par service",
        "description": (
            "Nombre d'alertes par type et par service. Un même relevé pouvant déclencher "
            "plusieurs alertes, le total dépasse le nombre de relevés en alerte. Seuls "
            "les services équipés de capteurs au chevet apparaissent."
        ),
        "display": "bar",
        "sql": (
            "SELECT service_label AS service,\n"
            "       nb_alertes_frequence_cardiaque AS `Fréquence cardiaque`,\n"
            "       nb_alertes_saturation          AS `Saturation (SpO2)`,\n"
            "       nb_alertes_temperature         AS `Température`\n"
            "FROM kpi_alertes_service\n"
            "ORDER BY service"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["Fréquence cardiaque", "Saturation (SpO2)", "Température"],
            # Barres groupées et non empilées : un relevé peut déclencher
            # plusieurs alertes, un empilement laisserait croire à un total.
            #
            # `auto_split: False` est indispensable ici. Les trois types d'alerte
            # n'ont pas du tout le même effectif ; laissé à lui-même, Metabase
            # place les séries sur DEUX axes Y de graduations différentes, et des
            # barres de hauteur comparable représentent alors des effectifs dans
            # un rapport de 1 à 10. Un axe unique montre l'écart réel, qui est
            # précisément l'information.
            "graph.y_axis.auto_split": False,
            "graph.show_values": True,
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Nombre d'alertes",
        },
        "row": 13,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    # ── Bande 4 · réadmissions, précédées de leur avertissement ─────────────
    # L'encart passe AVANT les cartes : un taux de réadmission lu sans sa limite
    # est un chiffre trompeur, et personne ne lit un avertissement placé sous le
    # graphique qu'il corrige.
    {
        "kind": "text",
        "text": (
            "### ↩️ Réadmissions à 30 jours\n"
            "⚠️ **Le taux affiché est une borne basse.** Une réadmission ne peut être "
            "constatée que si l'entrepôt couvre la période où elle surviendrait. Les "
            "admissions s'arrêtent au dernier jour déposé : une sortie de fin de période "
            "n'a que quelques jours de fenêtre, et aucune sortie ne dispose des 30 jours "
            "complets. Le taux réel est donc **supérieur** à celui-ci."
        ),
        "row": 21,
        "col": 0,
        "size_x": 24,
        "size_y": 2,
    },
    {
        "name": "Taux de réadmission par service",
        "description": (
            "KPI 2 ventilé — le service porté est celui du séjour initial, celui dont on "
            "interroge la prise en charge. La somme des services reproduit exactement le "
            "taux global affiché en tuile."
        ),
        "display": "bar",
        "sql": (
            "SELECT service_label AS service, taux_readmission_30j_pct AS `taux (%)`\n"
            "FROM kpi_readmissions_service\n"
            "ORDER BY `taux (%)` DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["taux (%)"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Taux de réadmission (%)",
        },
        "row": 23,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Modes d'admission et de sortie",
        "description": "Répartition des flux d'entrée et de sortie sur toute la période.",
        "display": "row",
        "sql": (
            "SELECT concat(sens, ' — ', mode) AS flux, sum(nb_sejours) AS nb_sejours\n"
            "FROM kpi_flux\n"
            "GROUP BY flux\n"
            "ORDER BY nb_sejours DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["flux"],
            "graph.metrics": ["nb_sejours"],
            "graph.max_categories_enabled": False,
            "graph.max_categories": 20,
            "graph.show_values": True,
            "graph.x_axis.title_text": "Flux",
            "graph.y_axis.title_text": "Nombre de séjours",
        },
        "row": 23,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    # ── Bande 5 · charge des services ──────────────────────────────────────
    {
        "name": "Charge des services par jour",
        "description": (
            "Séjours ouverts à la fin de chaque journée : la charge réelle du service, "
            "invisible dans un simple comptage d'admissions. La décrue de fin de période "
            "est un effet de bord des données déposées, pas une baisse d'activité."
        ),
        "display": "line",
        "sql": (
            "SELECT jour, service_label AS service, sejours_en_cours\n"
            "FROM kpi_activite_service\n"
            "ORDER BY jour, service"
        ),
        "visualization_settings": {
            "graph.dimensions": ["jour", "service"],
            "graph.metrics": ["sejours_en_cours"],
            "graph.x_axis.title_text": "Jour",
            "graph.y_axis.title_text": "Séjours ouverts",
        },
        "row": 31,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Activité quotidienne par service",
        "description": (
            "Entrées, sorties, décès et charge (séjours ouverts), par service et par jour."
        ),
        "display": "table",
        "sql": (
            "SELECT jour, service_label AS service, admissions, sorties,\n"
            "       deces AS `décès`, sejours_en_cours AS `ouverts`\n"
            "FROM kpi_activite_service\n"
            "ORDER BY jour DESC, service"
        ),
        "row": 31,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    # ── Bande 6 · actes médicaux et facturation (dépôt du 29 août) ─────────
    {
        "kind": "text",
        "text": (
            "### 🩺 Actes médicaux et facturation T2A\n"
            "Depuis le dépôt du 29 août, le CHU transmet les actes réalisés pendant les "
            "séjours et décrit ses services (catégorie, lits, pôle). Le service d'un acte "
            "est celui de son séjour, résolu dans l'entrepôt — jamais par jointure entre "
            "deux tables de faits. **La neurologie n'est pas décrite** : elle apparaît sous "
            "« non renseigne », et sa densité par lit reste vide plutôt qu'inventée."
        ),
        "row": 39,
        "col": 0,
        "size_x": 24,
        "size_y": 2,
    },
    {
        "name": "Activité et DMS par catégorie de service",
        "description": (
            "Séjours et durée moyenne de séjour (séjours terminés) par catégorie — le "
            "niveau intermédiaire de la hiérarchie service → catégorie → pôle."
        ),
        "display": "table",
        "sql": (
            "SELECT categorie AS `catégorie`, nb_services AS `services`,\n"
            "       nb_sejours AS `séjours`, nb_sejours_termines AS `terminés`,\n"
            "       dms_jours AS `DMS (jours)`\n"
            "FROM kpi_activite_categorie\n"
            "ORDER BY nb_sejours DESC"
        ),
        "row": 41,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Actes par service",
        "description": (
            "Nombre d'actes réalisés par service. Le service est celui du séjour, propagé "
            "sur le fait au moment de la construction de l'entrepôt."
        ),
        "display": "bar",
        "sql": (
            "SELECT service_label AS service, nb_actes\n"
            "FROM kpi_actes_service\n"
            "ORDER BY nb_actes DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["service"],
            "graph.metrics": ["nb_actes"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Actes",
        },
        "row": 41,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Actes par type",
        "description": "Répartition des actes par libellé CCAM, du plus fréquent au plus rare.",
        "display": "row",
        "sql": ("SELECT libelle AS acte, nb_actes\nFROM kpi_actes_type\nORDER BY nb_actes DESC"),
        "visualization_settings": {
            "graph.dimensions": ["acte"],
            "graph.metrics": ["nb_actes"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Acte (CCAM)",
            "graph.y_axis.title_text": "Actes",
        },
        "row": 49,
        "col": 0,
        "size_x": 12,
        "size_y": 8,
    },
    {
        "name": "Densité d'actes par lit et montant facturé",
        "description": (
            "Actes par séjour, actes par lit (intensité du plateau technique) et somme des "
            "tarifs T2A, par service. Une densité vide signale une capacité non renseignée."
        ),
        "display": "table",
        "sql": (
            "SELECT service_label AS service, categorie AS `catégorie`,\n"
            "       capacite_lits AS lits, nb_actes AS actes,\n"
            "       actes_par_sejour AS `actes / séjour`, actes_par_lit AS `actes / lit`,\n"
            "       montant_facture_euros AS `facturé (€)`\n"
            "FROM kpi_actes_service\n"
            "ORDER BY montant_facture_euros DESC"
        ),
        "row": 49,
        "col": 12,
        "size_x": 12,
        "size_y": 8,
    },
    # ── Bande 7 · traçabilité, ce qui distingue ce tableau de bord ──────────
    {
        "kind": "text",
        "text": (
            "### 🔎 Fiabilité des chiffres\n"
            "Toute ligne écartée par un contrôle qualité est comptée ici et reste "
            "consultable dans l'entrepôt : aucun chiffre du dashboard n'est le "
            "résultat d'une suppression silencieuse."
        ),
        "row": 57,
        "col": 0,
        "size_x": 24,
        "size_y": 2,
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
        "row": 59,
        "col": 0,
        "size_x": 24,
        "size_y": 14,
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
        "row": 73,
        "col": 0,
        "size_x": 24,
        "size_y": 10,
    },
]


# ── Dashboard 2 : recherche clinique ────────────────────────────────────────

_RECHERCHE_CARDS = [
    {
        "kind": "text",
        "text": (
            "## 🔬 Recherche clinique\n"
            "Cohortes de patients par pathologie et description démographique.\n\n"
            "**Données pseudonymisées et agrégées.** Aucune information identifiante "
            "n'est accessible depuis cet espace.\n\n"
            "**Petits effectifs : la ligne reste, le chiffre part.** Toute cellule "
            "regroupant moins de 5 patients garde sa place dans les tables, mais son "
            "effectif est retiré et remplacé par « masqué ». Vous savez ainsi qu'une "
            "valeur existe et qu'elle est protégée — c'est plus honnête que de faire "
            "disparaître la ligne sans rien dire.\n\n"
            "⚠️ **Jeu de données synthétique.** Les prévalences ont des ordres de grandeur "
            "plausibles, mais elles sont générées : les cohortes servent à valider la chaîne "
            "de traitement, **pas** à conclure quoi que ce soit d'épidémiologique."
        ),
        "row": 0,
        "col": 0,
        "size_x": 24,
        "size_y": 4,
    },
    {
        "name": "Taille des cohortes par pathologie",
        "description": (
            "KPI 5 — Patients distincts concernés par chaque diagnostic CIM-10, tous rangs "
            "confondus. Les cohortes masquées sont absentes du graphique : elles figurent "
            "dans la table voisine."
        ),
        # Barres horizontales : les libellés CIM-10 dépassent 40 caractères et
        # deviendraient illisibles en abscisse.
        "display": "row",
        "sql": (
            "SELECT libelle AS pathologie, nb_patients\n"
            "FROM prevalence_pathologie\n"
            "WHERE diffusable\n"
            "ORDER BY nb_patients DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["pathologie"],
            "graph.metrics": ["nb_patients"],
            "graph.max_categories_enabled": False,
            "graph.max_categories": 20,
            "graph.show_values": True,
            "graph.x_axis.title_text": "Pathologie (CIM-10)",
            "graph.y_axis.title_text": "Patients",
        },
        "row": 4,
        "col": 0,
        "size_x": 12,
        "size_y": 9,
    },
    {
        "name": "Prévalence par pathologie",
        "description": (
            "Les treize pathologies du référentiel, y compris celles dont l'effectif est "
            "masqué. La prévalence rapporte la cohorte à la population suivie."
        ),
        "display": "table",
        # L'effectif reste une colonne NUMÉRIQUE : le convertir en texte pour y
        # écrire « masqué » ferait perdre le formatage français des nombres, et
        # 2 234 s'afficherait 2234. L'état de masquage a donc sa propre colonne.
        "sql": (
            "SELECT code_cim10 AS `code`, libelle AS pathologie,\n"
            "       nb_patients     AS `patients`,\n"
            "       prevalence_pct  AS `prévalence (%)`,\n"
            "       if(diffusable, '', 'masqué (< 5)') AS `diffusion`\n"
            "FROM prevalence_pathologie\n"
            "ORDER BY nb_patients DESC NULLS LAST"
        ),
        "row": 4,
        "col": 12,
        "size_x": 12,
        "size_y": 9,
    },
    {
        "name": "Distribution par âge et sexe",
        "description": (
            "Pyramide des âges de la population suivie, chaque patient compté une seule "
            "fois. Lue à son propre grain, et non agrégée depuis la vue par pathologie : "
            "un patient portant cinq diagnostics y serait compté cinq fois."
        ),
        "display": "bar",
        "sql": (
            "SELECT tranche_age AS `tranche d'âge`,\n"
            "       sumIf(nb_patients, sexe = 'F') AS Femmes,\n"
            "       sumIf(nb_patients, sexe = 'M') AS Hommes\n"
            "FROM cohorte_demographie_globale\n"
            "WHERE diffusable\n"
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
        "row": 13,
        "col": 0,
        "size_x": 12,
        "size_y": 9,
    },
    {
        "name": "Part des femmes par pathologie",
        "description": (
            "Composition des cohortes par sexe, exprimée en part de femmes. Le ratio est "
            "plus lisible que deux séries d'effectifs : les cohortes vont de 8 à plus de "
            "2 000 patients, et deux barres absolues côte à côte ne laisseraient pas lire "
            "la composition des petites."
        ),
        "display": "row",
        # La somme des tranches d'âge n'est légitime que si aucune cellule de la
        # pathologie n'est masquée. C'est vrai ici, et deux contrôles dbt le
        # garantissent : `assert_pas_de_suppression_partielle` interdit qu'une
        # pathologie soit publiée à moitié, `assert_part_de_femmes_non_biaisee`
        # compare le ratio publié à celui recalculé depuis silver.
        "sql": (
            "SELECT libelle AS pathologie,\n"
            "       round(100.0 * sumIf(nb_patients, sexe = 'F')\n"
            "             / sum(nb_patients), 1) AS `part de femmes (%)`\n"
            "FROM cohorte_demographie\n"
            "WHERE diffusable\n"
            "GROUP BY pathologie\n"
            "ORDER BY `part de femmes (%)` DESC"
        ),
        "visualization_settings": {
            "graph.dimensions": ["pathologie"],
            "graph.metrics": ["part de femmes (%)"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Pathologie",
            "graph.y_axis.title_text": "Part de femmes (%)",
        },
        "row": 13,
        "col": 12,
        "size_x": 12,
        "size_y": 9,
    },
    {
        "kind": "text",
        "text": (
            "### 🔒 Protection des petits effectifs\n"
            "Le seuil de diffusion est de **5 patients**. En dessous, l'effectif est "
            "retiré : un chiffre aussi faible, croisé avec l'âge et le sexe, pourrait "
            "permettre de ré-identifier une personne.\n\n"
            "Le compteur ci-dessous mesure l'effet du dispositif à chaque traitement, "
            "table par table — sans jamais dire quelles cellules sont concernées."
        ),
        "row": 22,
        "col": 0,
        "size_x": 24,
        "size_y": 3,
    },
    {
        "name": "Cellules masquées par le seuil (k = 5)",
        "description": "Effet mesuré du k-anonymat sur chacune des tables diffusées.",
        "display": "table",
        "sql": (
            "SELECT table_cible        AS `table diffusée`,\n"
            "       motif,\n"
            "       cellules_calculees AS `calculées`,\n"
            "       cellules_diffusees AS `diffusées`,\n"
            "       cellules_masquees  AS `masquées`,\n"
            "       seuil_k            AS `seuil k`\n"
            "FROM k_anonymat_controle\n"
            "ORDER BY `table diffusée`"
        ),
        "row": 25,
        "col": 0,
        "size_x": 24,
        "size_y": 4,
    },
    {
        "name": "Description détaillée des cohortes",
        "description": (
            "KPI 6 — Pathologie × tranche d'âge × sexe, sur le diagnostic PRINCIPAL, "
            "c'est-à-dire le motif d'hospitalisation. Les cellules sous le seuil "
            "apparaissent avec leur effectif masqué."
        ),
        "display": "table",
        "sql": (
            "SELECT code_cim10 AS `code`, libelle AS pathologie,\n"
            "       tranche_age AS `tranche d'âge`, sexe,\n"
            "       nb_patients AS patients,\n"
            "       if(diffusable, '', 'masqué (< 5)') AS `diffusion`\n"
            "FROM cohorte_demographie\n"
            "ORDER BY pathologie, tranche_age_debut, sexe"
        ),
        "row": 29,
        "col": 0,
        "size_x": 24,
        "size_y": 14,
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
