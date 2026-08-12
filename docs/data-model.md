# 核心数据模型（草案）

| 实体 | 关键字段 | 用途 |
| --- | --- | --- |
| users | feishu_user_id, name, role | 管理员、质检员、业务员身份 |
| orders | contract_no, feishu_record_id, sync_version, status | 合同订单及飞书来源 |
| products | order_id, name, category, quantity | 合同内的产品 |
| photo_templates | product_category, version, active | 类别的拍照模板 |
| photo_template_items | template_id, name, required, sort_order | 每个模板的拍照项 |
| inspection_tasks | product_id, assignee_id, status, template_snapshot | 分配给质检员的任务 |
| task_photo_items | task_id, item_name, required, status | 任务生成时固定的清单 |
| photos | task_photo_item_id, oss_object_key, checksum, captured_at | OSS 图片索引与审计元数据 |
| sync_cursors | source, cursor, last_synced_at | 飞书增量同步水位 |

建议在 `orders.contract_no`、`products.name`、`photos.oss_object_key` 上建立检索索引，并为常用的合同号 + 产品名查询建立联合索引。
