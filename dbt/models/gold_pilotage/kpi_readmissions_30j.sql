{{ config(order_by='(service_code, discharge_date)') }}
-- Taux de réadmission à 30 jours, par service et jour de sortie.
--
-- ⚠ FENÊTRE D'OBSERVATION — la limite majeure de cet indicateur.
--
-- Une réadmission ne peut être constatée que si l'entrepôt couvre la période où elle
-- surviendrait. Or les admissions s'arrêtent au dernier jour déposé, tandis que les
-- sorties s'étalent bien au-delà : une sortie postérieure à la dernière admission
-- connue a une probabilité **structurellement nulle** d'être suivie d'une réadmission
-- observable. Elle ne mesure donc rien, et l'agréger avec les autres dilue
-- mécaniquement le taux.
--
-- Chaque ligne porte pour cette raison `jours_observables`. Les indicateurs de synthèse
-- ne retiennent que les sorties dont la fenêtre est non vide, et le tableau de bord
-- affiche la couverture.
--
-- Définition retenue : un séjour est suivi d'une réadmission s'il existe, pour le même
-- patient, une admission postérieure à la sortie et survenant dans les 30 jours.
--
-- On teste l'ensemble des admissions du patient, et non la seule admission
-- chronologiquement suivante : c'est la définition cliniquement correcte, et elle
-- résiste à des séjours qui se chevaucheraient — l'admission « suivante » serait alors
-- un séjour concurrent commencé avant la sortie, qui masquerait la réadmission réelle.
--
-- Dénominateur : sorties vivantes uniquement — un patient décédé ne peut pas être
-- réadmis, l'inclure minorerait artificiellement le taux.
WITH (SELECT max(admission_date) FROM {{ ref('fact_sejour') }}) AS derniere_admission
SELECT
    e.service_code                                          AS service_code,
    d.service_label                                         AS service_label,
    e.discharge_date                                        AS discharge_date,

    -- Part de la fenêtre de 30 jours réellement couverte par les données. Le « + 1 »
    -- compte le jour de sortie lui-même : une sortie le dernier jour déposé peut encore
    -- être suivie d'une réadmission quelques heures plus tard. 0 = la sortie est
    -- postérieure à la dernière admission connue : la ligne ne peut rien constater.
    greatest(0, least(30, dateDiff('day', e.discharge_date, derniere_admission) + 1))
                                                            AS jours_observables,
    dateDiff('day', e.discharge_date, derniere_admission) + 1 >= 30
                                                            AS fenetre_complete,

    count()                                                 AS sorties_eligibles,
    countIf(e.est_readmis)                                  AS readmissions_30j,
    round(100.0 * countIf(e.est_readmis) / count(), 1)      AS taux_readmission_pct
FROM
(
    SELECT
        service_code,
        assumeNotNull(discharge_date) AS discharge_date,
        arrayExists(
            adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY,
            admissions_du_patient
        ) AS est_readmis
    FROM
    (
        SELECT
            service_code,
            discharge_ts,
            discharge_date,
            discharge_mode,
            -- Toutes les admissions du patient (au plus une dizaine par patient).
            groupArray(admission_ts) OVER (PARTITION BY patient_pseudo)
                AS admissions_du_patient
        FROM {{ ref('fact_sejour') }}
    )
    WHERE discharge_ts IS NOT NULL
      AND (discharge_mode IS NULL OR discharge_mode != 'deces')
) AS e
INNER JOIN {{ ref('dim_service') }} AS d ON d.service_code = e.service_code
GROUP BY service_code, service_label, discharge_date, jours_observables, fenetre_complete
