-- Q2 : la règle qui motive les rejets doit être sans exception.
-- Un test singulier échoue dès qu'il renvoie une ligne.
SELECT stay_id, admission_ts, discharge_ts
FROM {{ ref('fact_sejour') }}
WHERE discharge_ts IS NOT NULL
  AND discharge_ts < admission_ts
