{{ config(order_by='(code_cim10, region_code, sexe, tranche_age_debut)') }}
-- Grain fin diffusé : les cellules qui atteignent le seuil.
-- Distribution sexe × âge × département, par pathologie.
SELECT code_cim10, libelle, region_code, sexe, tranche_age_debut, tranche_age, nb_patients
FROM {{ ref('cellules_demographie') }}
WHERE diffusable
