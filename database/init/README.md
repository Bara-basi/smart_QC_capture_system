# 数据库初始化

目标数据库为 `smart_qc_capture_system`。首次启动 PostgreSQL 容器前，设置 `POSTGRES_DB=smart_qc_capture_system`，并将本目录挂载到 `/docker-entrypoint-initdb.d:ro`；官方镜像会自动执行 `001_schema.sql`。

对于已经运行的数据库，请在本机执行（根据实际密码填写 `PGPASSWORD`）：

```powershell
$env:PGPASSWORD = '<postgres password>'
psql -h localhost -p 15432 -U qc_user -d smart_qc_capture_system -f database/init/001_schema.sql
```

表：`users`、`orders`、`order_items`、`inspection_photo_tasks`、`photo_records`。其中拍照任务表是由商品检验规则生成的必拍清单；照片记录表保存 OSS 对象键、哈希、文件大小、状态和拍摄元数据，支持防漏拍、错拍及审计追溯。
