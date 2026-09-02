{{ config(order_by='(code_cim10, stay_id)') }}
-- Étoile 3 — fact_diagnostic, grain : un code CIM-10 posé sur un séjour.
-- Dimensions directes : dim_patient (patient_pseudo propagé depuis le séjour),
-- dim_cim10 (code_cim10). `stay_id` reste en dimension dégénérée.
--
-- La propagation de `patient_pseudo` au moment du build est ce qui permet aux
-- requêtes de cohortes de compter des patients sans jamais joindre deux tables
-- de faits entre elles.
--
-- Le patient et le service sont résolus depuis `stg_sejours`, qui porte TOUS les
-- séjours déposés — y compris ceux dont les horodatages ont été écartés par Q2. Un
-- diagnostic est un fait clinique : il ne disparaît pas parce qu'une date de sortie
-- a été mal saisie (voir l'encadré de `stg_sejours`).
WITH dedup AS
(
    SELECT
        stay_id,
        code_cim10,
        -- Le grain est (séjour, code) : un même code ne peut pas être à la fois
        -- principal et associé sur un séjour. Si la source affirme les deux, le
        -- principal l'emporte — c'est le rang qui décrit le motif d'hospitalisation,
        -- et il est lu par la description de cohorte.
        if(countIf(diag_type = 'principal') > 0,
           'principal',
           argMax(diag_type, _ingest_date))    AS diag_type,
        argMax(_source_file, _ingest_date)     AS source_file,
        max(_ingest_date)                      AS last_ingest_date
    FROM {{ source('bronze', 'diagnostics') }}
    GROUP BY stay_id, code_cim10
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
    toDate(s.admission_ts)                      AS admission_date,
    s.service_code                              AS service_code,
    d.source_file                               AS _source_file,
    d.last_ingest_date                          AS _ingest_date,
    now()                                       AS _built_at
FROM dedup AS d
-- Jointure interne : un diagnostic référençant un séjour absent du dépôt n'a pas de
-- patient rattachable, donc pas sa place dans l'entrepôt. Contrôle C2, attendu à 0.
INNER JOIN {{ ref('stg_sejours') }} AS s USING (stay_id)
