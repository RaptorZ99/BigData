-- Chargement d'un jour de diagnostics : le JSON imbriqué est aplati **par le
-- moteur**, une ligne par code CIM-10.
--
-- `JSONAsString` lit un tableau JSON de premier niveau comme une ligne par objet ;
-- `JSONExtractArrayRaw` + `arrayJoin` déplient ensuite le tableau `diagnostics`
-- de chaque séjour. Aucun parsing côté Python : le fichier ne transite pas par
-- la mémoire de l'orchestrateur.
INSERT INTO eds_bronze.diagnostics
SELECT
    JSONExtractString(json, 'stay_id')      AS stay_id,
    JSONExtractString(diag, 'code_cim10')   AS code_cim10,
    JSONExtractString(diag, 'type')         AS diag_type,
    '{source_file}'                         AS _source_file,
    toDate('{ingest_date}')                 AS _ingest_date,
    now()                                   AS _loaded_at
FROM
(
    SELECT
        json,
        arrayJoin(JSONExtractArrayRaw(json, 'diagnostics')) AS diag
    FROM file('{source_file}', 'JSONAsString', 'json String')
);
