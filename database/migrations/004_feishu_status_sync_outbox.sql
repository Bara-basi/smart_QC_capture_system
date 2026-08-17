-- Persist Feishu status updates so a temporary network/API failure cannot lose them.
CREATE TABLE IF NOT EXISTS feishu_status_sync_outbox (
    id BIGSERIAL PRIMARY KEY,
    table_id VARCHAR(128) NOT NULL,
    record_id VARCHAR(128) NOT NULL,
    field_id VARCHAR(128) NOT NULL,
    field_value TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (table_id, record_id, field_id, field_value)
);

CREATE INDEX IF NOT EXISTS ix_feishu_status_sync_pending
    ON feishu_status_sync_outbox (next_attempt_at, id)
    WHERE synced_at IS NULL;
