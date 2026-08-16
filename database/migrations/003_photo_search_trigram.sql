-- Accelerate token/substring searches, including Chinese metadata terms.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
UPDATE photo_records
SET search_text = concat_ws(
    ' ', contract_no, factory_initials, sequence_no, product_type,
    specification, inspection_item, photographer_name
)
WHERE search_text = '';
CREATE INDEX IF NOT EXISTS ix_photo_records_search_trgm
    ON photo_records USING GIN (search_text gin_trgm_ops);
