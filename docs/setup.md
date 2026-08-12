# 依赖与部署准备

## 后端（Python 3.11+）

- Web/API：`fastapi`、`uvicorn[standard]`
- 配置与校验：`pydantic-settings`、`pydantic`
- 数据库：`sqlalchemy[asyncio]`、`asyncpg`、`alembic`
- 飞书：`lark-oapi`
- OSS：`oss2`（或使用 STS 时搭配阿里云凭据 SDK）
- HTTP/任务：`httpx`、`apscheduler`；生产环境任务量较大时使用 `celery` + `redis`
- 测试与质量：`pytest`、`pytest-asyncio`、`ruff`

## 前端（Node.js 20 LTS+）

- 框架与构建：`vue`、`vite`、`typescript`、`@vitejs/plugin-vue`、`vue-tsc`
- 页面与状态：`vue-router`、`pinia`、`axios`、`vant`
- 飞书网页 JS SDK：按飞书官方 CDN 引入 H5 JSSDK（用于免登、图片预览等容器能力）；它不是 Node 服务端 SDK，不应打入前端依赖包。

## 基础设施

- PostgreSQL 16+
- Redis 7+（仅在启用队列/分布式定时任务时需要）
- 阿里云 OSS 私有 Bucket
- 反向代理与 TLS：Nginx、Caddy 或云负载均衡
- Docker / Docker Compose（建议用于 API、前端静态站点、PostgreSQL、Redis 的本地和生产一致部署）

生产部署建议拆分为：Vue 构建后的静态文件、无状态 FastAPI 服务、独立 PostgreSQL、独立 Redis（如启用）、OSS。先部署数据库迁移，再发布 API 和前端。
# Feishu web login (local development with one ngrok tunnel)

Start FastAPI on port 8000 and Vite on port 5173. Vite proxies every `/api/*`
request to FastAPI, so expose **only port 5173**. Target IPv4 explicitly to
avoid a stale IPv6 Vite process being selected by `localhost`:

```powershell
ngrok http 127.0.0.1:5173
```

Set `WEB_ORIGIN` in `backend/.env` to the resulting HTTPS ngrok origin (without
a trailing slash), for example `https://example.ngrok-free.app`. Configure this
exact redirect URL in the Feishu application security settings:

```text
https://example.ngrok-free.app/api/v1/auth/feishu/callback
```

In the Feishu developer console, enable web OAuth / web application login and
request and publish the self-built-app permissions **Get user user ID** and the
required Contact permission for reading a user's employment/department data.
The former is required by the implementation: `user_id` is stable for one user
within a tenant across Feishu apps. The system additionally records `open_id`
(app-specific), `union_id` (developer-scoped), and `open_department_id` values.

At the web application's root path, the client checks its session and redirects
unauthenticated visitors to Feishu automatically. After the callback succeeds,
the user is upserted to PostgreSQL as an `inspector` and receives an eight-hour
signed, HTTP-only session cookie. User and tenant tokens are not stored.

## Permissions for the initial user record

In **Permissions > API permissions**, request and publish these self-built-app
permissions (the Chinese labels can differ slightly by console version):

- `contact:user.id:readonly` — **获取用户 user ID**. Required; this is the
  tenant-stable identity stored as `feishu_user_id`.
- `contact:user.base:readonly` — **获取用户基本信息**. Needed when the Contact
  API is used to read the current member.
- `contact:user.department:readonly` — **获取用户组织架构信息（高级）**. Needed
  for `department_ids` / `open_department_id` values.

Also set the app's Contact permission range to include the signing-in users (or
all members). `contact:department.base:readonly` is only needed later if the
system must resolve each stored department ID to a department *name*.

Department synchronization is currently disabled by default
(`FEISHU_SYNC_DEPARTMENTS=false`) so it cannot prevent login. When revisiting
it, the error returned by Feishu additionally requires one application-identity
Contact scope such as `contact:contact.base:readonly`; this is separate from
the field-level permissions above.

## Feishu Bitable order webhook

The order table and the inspection-task table use different Feishu Table IDs.
They are configured independently in `backend/.env.feishu`; do not use the
inspection-task table ID for the order view.

Before enabling the automation, grant and publish the application-identity
permission `contact:contact.base:readonly`. Bitable person cells provide an
`open_id`; the API resolves it through Contacts and stores both `union_id` and
name for the inspector.

For local development, keep FastAPI on `8000`, Vite on `5173`, and expose Vite
through ngrok as described above. Configure the Bitable Automation HTTP action
to POST to:

```text
https://<your-ngrok-domain>/api/v1/integrations/feishu/order-sync
```

Add an `X-QC-Sync-Secret` request header whose value matches
`FEISHU_SYNC_WEBHOOK_SECRET`, and send the triggering order record ID:

```json
{"record_id":"{{record_id}}"}
```

The endpoint reads that record from the order view, upserts it by Feishu record
ID, then reads matching-contract rows in the inspection-task view. All source
columns are preserved in `feishu_fields`; the queryable fields are
`contract_no`, `product_type`, `inspection_status`, and inspector open/union ID
and name. On a server, route this HTTPS path directly to FastAPI behind a
reverse proxy instead of depending on the Vite development proxy.
