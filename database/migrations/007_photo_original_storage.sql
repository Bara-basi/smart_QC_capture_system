-- Store a second full-resolution copy without the QC watermark.
-- Existing rows remain NULL because an overlay cannot be removed from an
-- already-rendered JPEG; the API reports those as unavailable rather than
-- serving a watermarked image under the no-watermark option.
ALTER TABLE photo_records
    ADD COLUMN IF NOT EXISTS original_oss_object_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_photo_records_original_oss_object_key
    ON photo_records (original_oss_object_key)
    WHERE original_oss_object_key IS NOT NULL;
