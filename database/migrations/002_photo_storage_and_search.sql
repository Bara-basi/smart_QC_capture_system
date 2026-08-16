-- Apply once to existing databases before enabling photo upload.
-- Older deployments used an unrelated UUID `task_id`; retain it and add the
-- canonical Feishu task identifier used by the current capture workflow.
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS task_feishu_record_id VARCHAR(128);
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS source VARCHAR(50) NOT NULL DEFAULT 'feishu_h5_camera';
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS factory_initials VARCHAR(32);
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS sequence_no TEXT;
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS specification TEXT;
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS photographer_name VARCHAR(100);
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS preview_oss_object_key TEXT;
ALTER TABLE photo_records ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_photo_records_lookup ON photo_records (factory_initials, product_type, inspection_item, captured_at DESC);
CREATE INDEX IF NOT EXISTS ix_photo_records_search ON photo_records USING GIN (to_tsvector('simple', search_text));
