-- Dashboard and capture-sheet lookups must not scan all tasks/photos as the
-- archive grows. These indexes match the authenticated inspector queries.
CREATE INDEX IF NOT EXISTS ix_photo_tasks_inspector_open_created
    ON inspection_photo_tasks (inspector_open_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_photo_records_photographer_task
    ON photo_records (photographer_open_id, task_feishu_record_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS ix_photo_records_contract_photographer
    ON photo_records (contract_no, photographer_open_id, captured_at DESC);
