{{ config(materialized='ephemeral') }}
-- Définition unique de la réadmission à 30 jours, au grain du séjour.
--
-- Un séjour est « suivi d'une réadmission » s'il existe, pour le même patient, une
-- admission postérieure à sa sortie et survenant dans les 30 jours.
--
-- On teste l'ensemble des admissions du patient, et non la seule admission
-- chronologiquement suivante : c'est la définition cliniquement correcte, et elle
-- résiste à des séjours qui se chevaucheraient — l'admission « suivante » serait alors
-- un séjour concurrent commencé avant la sortie, qui masquerait la réadmission réelle.
--
-- Un séjour en cours ne peut évidemment pas être suivi d'une réadmission : sa sortie
-- n'a pas eu lieu. Il reste au dénominateur, et compte pour 0 au numérateur.
--
-- Modèle éphémère : la règle est écrite une fois et alimente le taux global comme sa
-- ventilation par service. Les deux ne peuvent pas diverger.
SELECT
    stay_id,
    service_code,
    ifNull(
        arrayExists(
            adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY,
            admissions_du_patient
        ),
        false
    ) AS est_readmis
FROM
(
    SELECT
        stay_id,
        service_code,
        discharge_ts,
        -- Toutes les admissions du patient (au plus une dizaine par patient).
        groupArray(admission_ts) OVER (PARTITION BY patient_pseudo)
            AS admissions_du_patient
    FROM {{ ref('fact_sejour') }}
)
