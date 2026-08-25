ALTER TABLE users
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;

CREATE INDEX IF NOT EXISTS ix_photo_records_photographer_task
    ON photo_records (photographer_open_id, task_feishu_record_id)
    WHERE task_feishu_record_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_photo_tasks_inspector_open_id
    ON inspection_photo_tasks (inspector_open_id, created_at DESC);
