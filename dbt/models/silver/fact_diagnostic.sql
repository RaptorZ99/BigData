{{ config(order_by='(code_cim10, stay_id)') }}
-- Étoile 3 — fact_diagnostic, grain : un diagnostic posé sur un séjour.
-- Dimensions directes : dim_patient (patient_pseudo propagé depuis le séjour),
-- dim_cim10 (code_cim10). `stay_id` reste en dimension dégénérée.
--
-- La propagation de `patient_pseudo` au moment du build est ce qui permet aux
-- requêtes de cohortes de compter des patients sans jamais joindre deux tables
-- de faits entre elles.
WITH dedup AS
(
    SELECT
        stay_id,
        code_cim10,
        diag_type,
        argMax(_source_file, _ingest_date) AS source_file,
        max(_ingest_date)                  AS last_ingest_date
    FROM {{ source('bronze', 'diagnostics') }}
    GROUP BY stay_id, code_cim10, diag_type
)
SELECT
    d.stay_id                                   AS stay_id,
    s.patient_pseudo                            AS patient_pseudo,
    d.code_cim10                                AS code_cim10,
    d.diag_type                                 AS diag_type,
    -- Cast explicite : comparer une colonne LowCardinality produit un
    -- LowCardinality(UInt8), type que ClickHouse refuse de matérialiser.
    CAST(d.diag_type = 'principal' AS Bool)     AS is_principal,
    -- Dénormalisation minimale du séjour parent : évite une jointure fait-à-fait
    -- côté gold pour croiser diagnostics et période d'activité.
    s.admission_date                            AS admission_date,
    s.service_code                              AS service_code,
    d.source_file                               AS _source_file,
    d.last_ingest_date                          AS _ingest_date,
    now()                                       AS _built_at
FROM dedup AS d
-- Jointure interne = cascade : un diagnostic dont le séjour a été écarté (ou
-- qui référence un séjour inconnu) ne peut pas entrer dans l'entrepôt.
INNER JOIN {{ ref('fact_sejour') }} AS s USING (stay_id)
