\set ON_ERROR_STOP on
\pset pager off
\pset footer off

BEGIN TRANSACTION READ ONLY;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

\echo '== Migration/schema presence =='
SELECT item, to_regclass(item) IS NOT NULL AS present
FROM unnest(ARRAY[
    'users',
    'orders',
    'order_items',
    'inspection_photo_tasks',
    'photo_records',
    'feishu_status_sync_outbox'
]) AS item;

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'users'
  AND column_name IN ('avatar_url', 'character', 'is_active')
ORDER BY column_name;

\echo '== User/role state (aggregates only) =='
SELECT character, is_active, COUNT(*) AS users
FROM users
GROUP BY character, is_active
ORDER BY character, is_active;

\echo '== Source-data volume =='
SELECT
    (SELECT COUNT(*) FROM orders) AS orders,
    (SELECT COUNT(*) FROM order_items) AS order_items,
    (SELECT COUNT(*) FROM inspection_photo_tasks) AS photo_tasks,
    (SELECT COUNT(*) FROM photo_records) AS photos;

\echo '== Task status distribution =='
SELECT COALESCE(inspection_status, '(null)') AS status, COUNT(*) AS tasks
FROM inspection_photo_tasks
GROUP BY COALESCE(inspection_status, '(null)')
ORDER BY tasks DESC, status;

\echo '== Product category coverage =='
SELECT COALESCE(product_type, '(null)') AS product_type, COUNT(*) AS tasks
FROM inspection_photo_tasks
GROUP BY COALESCE(product_type, '(null)')
ORDER BY tasks DESC, product_type;

\echo '== Assignment integrity =='
SELECT
    COUNT(*) FILTER (WHERE inspector_open_id IS NULL) AS unassigned_tasks,
    COUNT(*) FILTER (WHERE inspector_open_id IS NOT NULL) AS assigned_tasks,
    COUNT(*) FILTER (
        WHERE inspector_open_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM users u WHERE u.open_id = inspection_photo_tasks.inspector_open_id
          )
    ) AS assigned_but_no_local_user,
    COUNT(*) FILTER (
        WHERE inspector_open_id IS NOT NULL
          AND inspector_union_id IS NULL
    ) AS assigned_without_union_id
FROM inspection_photo_tasks;

\echo '== Order join duplication risk =='
SELECT COUNT(*) AS duplicate_contract_product_groups
FROM (
    SELECT contract_no, product_type
    FROM order_items
    GROUP BY contract_no, product_type
    HAVING COUNT(*) > 1
) AS duplicates;

\echo '== Photo reference integrity =='
SELECT
    COUNT(*) FILTER (WHERE task_feishu_record_id IS NULL) AS photos_without_task_id,
    COUNT(*) FILTER (
        WHERE task_feishu_record_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM inspection_photo_tasks t
              WHERE t.feishu_record_id = photo_records.task_feishu_record_id
          )
    ) AS photos_with_unknown_task,
    COUNT(*) FILTER (
        WHERE photographer_open_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM users u
              WHERE u.open_id = photo_records.photographer_open_id
          )
    ) AS photos_without_local_photographer,
    COUNT(*) FILTER (
        WHERE preview_oss_object_key IS NULL OR preview_oss_object_key = ''
    ) AS photos_without_preview_key
FROM photo_records;

\echo '== 200-row gallery cap exposure =='
SELECT
    COUNT(*) AS photographers_over_200_photos,
    COALESCE(MAX(total), 0) AS largest_photographer_archive
FROM (
    SELECT photographer_open_id, COUNT(*) AS total
    FROM photo_records
    GROUP BY photographer_open_id
    HAVING COUNT(*) > 200
) AS archives;

\echo '== Feishu outbox health =='
SELECT
    COUNT(*) FILTER (WHERE synced_at IS NULL) AS pending,
    COUNT(*) FILTER (WHERE synced_at IS NOT NULL) AS synced,
    COUNT(*) FILTER (WHERE synced_at IS NULL AND attempts > 0) AS retried_pending,
    COUNT(*) FILTER (WHERE synced_at IS NULL AND last_error IS NOT NULL) AS pending_with_error,
    COALESCE(MAX(attempts), 0) AS max_attempts
FROM feishu_status_sync_outbox;

\echo '== Database size =='
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;

ROLLBACK;
