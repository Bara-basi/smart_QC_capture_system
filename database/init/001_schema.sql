-- Smart QC Capture System PostgreSQL schema.
-- Demo data may be discarded; rerun this file only on an empty database.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$ BEGIN
    CREATE TYPE user_character AS ENUM ('inspector', 'salesperson', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE photo_status AS ENUM ('uploaded', 'approved', 'rejected', 'superseded');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feishu_user_id VARCHAR(128) NOT NULL,
    tenant_key VARCHAR(128) NOT NULL DEFAULT '',
    open_id VARCHAR(128) NOT NULL UNIQUE,
    union_id VARCHAR(128),
    name VARCHAR(100) NOT NULL,
    department_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    character user_character NOT NULL DEFAULT 'inspector',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_key, feishu_user_id)
);

CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_no VARCHAR(100) NOT NULL UNIQUE,
    contract_year_code VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The mapped columns make the capture workflow queryable. `feishu_fields`
-- retains every Bitable column (including future columns and rich field types).
CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    contract_no VARCHAR(100) NOT NULL,
    product_type VARCHAR(100) NOT NULL,
    inspection_status VARCHAR(100),
    inspector_open_id VARCHAR(128),
    inspector_union_id VARCHAR(128),
    inspector_name VARCHAR(100),
    feishu_record_id VARCHAR(128) NOT NULL UNIQUE,
    feishu_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Maps the Feishu inspection-task fields to English column names.
-- The only additions are the Bitable record ID, audit timestamps, and IDs
-- expanded from the 质检员 person field.
CREATE TABLE inspection_photo_tasks (
    feishu_record_id VARCHAR(128) PRIMARY KEY,
    contract_no TEXT NOT NULL,
    sequence_no TEXT,
    task_id TEXT,
    product_type TEXT,
    specification TEXT,
    quantity TEXT,
    inspection_stage TEXT,
    inspector_name TEXT,
    inspection_status TEXT,
    inspector_open_id VARCHAR(128),
    inspector_union_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE photo_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_feishu_record_id VARCHAR(128) REFERENCES inspection_photo_tasks(feishu_record_id) ON DELETE SET NULL,
    photographer_open_id VARCHAR(128) REFERENCES users(open_id),
    captured_at TIMESTAMPTZ NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    contract_no VARCHAR(100) NOT NULL,
    product_type VARCHAR(100) NOT NULL,
    inspection_item VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'feishu_h5_camera',
    factory_initials VARCHAR(32),
    sequence_no TEXT,
    specification TEXT,
    photographer_name VARCHAR(100),
    oss_object_key TEXT NOT NULL UNIQUE,
    preview_oss_object_key TEXT NOT NULL UNIQUE,
    original_filename TEXT,
    content_type VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
    sha256 CHAR(64) NOT NULL,
    status photo_status NOT NULL DEFAULT 'uploaded',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    search_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feishu_status_sync_outbox (
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

CREATE INDEX ix_order_items_contract_product ON order_items (contract_no, product_type);
CREATE INDEX ix_order_items_inspector_status ON order_items (inspector_union_id, inspection_status);
CREATE INDEX ix_photo_tasks_contract_product ON inspection_photo_tasks (contract_no, product_type);
CREATE INDEX ix_photo_tasks_inspector_status ON inspection_photo_tasks (inspector_union_id, inspection_status);
CREATE INDEX ix_photo_records_contract ON photo_records (contract_no, captured_at DESC);
CREATE INDEX ix_photo_records_lookup ON photo_records (factory_initials, product_type, inspection_item, captured_at DESC);
CREATE INDEX ix_photo_records_search ON photo_records USING GIN (to_tsvector('simple', search_text));
CREATE INDEX ix_photo_records_search_trgm ON photo_records USING GIN (search_text gin_trgm_ops);
CREATE INDEX ix_feishu_status_sync_pending ON feishu_status_sync_outbox (next_attempt_at, id) WHERE synced_at IS NULL;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_orders_updated_at BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_order_items_updated_at BEFORE UPDATE ON order_items FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_inspection_photo_tasks_updated_at BEFORE UPDATE ON inspection_photo_tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
