-- Traçabilité : chaque ligne de silver sait de quel fichier et de quel jour elle vient.
-- Le rapport l'affirme pour l'ensemble de la couche ; le contrôle le vérifie table
-- par table plutôt que sur un échantillon.
{% set tables = [
    'dim_patient', 'dim_service', 'dim_cim10',
    'fact_sejour', 'fact_diagnostic', 'fact_monitoring',
    'sejours_rejets', 'monitoring_rejets'
] %}
{% for t in tables %}
SELECT '{{ t }}' AS table_cible, count() AS sans_lignage
FROM {{ ref(t) }}
WHERE _source_file = '' OR _ingest_date = toDate(0)
HAVING sans_lignage > 0
{% if not loop.last %}UNION ALL{% endif %}
{% endfor %}
