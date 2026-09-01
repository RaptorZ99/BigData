-- Q4 : aucune constante conservée ne doit sortir des plages physiologiques
-- (FC 20-250 bpm · SpO2 50-100 % · température 30-45 °C).
SELECT stay_id, ts, heart_rate, spo2, temp_c
FROM {{ ref('fact_monitoring') }}
WHERE heart_rate NOT BETWEEN 20 AND 250
   OR spo2       NOT BETWEEN 50 AND 100
   OR temp_c     NOT BETWEEN 30 AND 45
