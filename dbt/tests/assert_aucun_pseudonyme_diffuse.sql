-- Minimisation à l'intérieur même de l'entrepôt : le pseudonyme n'est pas identifiant,
-- mais aucun indicateur n'en a besoin — il ne descend donc pas jusqu'aux bases de
-- restitution. Le contrôle porte sur le schéma, pas sur les données.
-- depends_on: {{ ref('cohorte_demographie') }}
-- depends_on: {{ ref('kpi_synthese') }}
SELECT database, table, name
FROM system.columns
WHERE database IN ('eds_gold_pilotage', 'eds_gold_recherche')
  AND name IN ('nir', 'nom', 'prenom', 'birth_date', 'patient_id', 'patient_pseudo')
