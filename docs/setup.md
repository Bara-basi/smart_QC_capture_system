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

## 生产服务器部署（Docker Compose + Caddy）

生产环境不需要 ngrok，也不运行 Vite。`docker-compose.production.yml` 会构建 Vue
静态站点；Caddy 在同一个 HTTPS 域名下提供网页，并将 `/api/*` **直接**反向代理到
FastAPI。浏览器访问的仍是 `/api/v1/...`，因此会话 Cookie、JSAPI 签名页和 API
全部同源，不需要 CORS 或开发代理。

### 1. 准备服务器与域名

- 使用可从公网访问的 Linux 服务器，安装 Docker Engine 与 Docker Compose v2。
- 为 `qc.example.com` 创建 A（需要 IPv6 时再创建 AAAA）记录，指向服务器公网 IP。
- 云安全组和系统防火墙仅放行 TCP `80`、`443` 与管理用 SSH；不要暴露 `8000`、PostgreSQL 或 Redis。
- 将仓库复制到服务器，例如 `/opt/smart-qc-capture-system`。生产数据库 Docker volume 应纳入备份策略。

Caddy 会在域名正确解析、80/443 可访问后自动申请和续期 Let's Encrypt 证书。若服务器已有 Nginx/Apache 占用 80 或 443，应停用它，或改由现有反代转发至 Caddy。

### 2. 填写配置

在仓库根目录执行：

```bash
cp .env.production.example .env.production
cp backend/.env.example backend/.env
chmod 600 .env.production backend/.env
```

编辑 `.env.production`，设置真实域名、运维邮箱及强 PostgreSQL 密码。编辑
`backend/.env` 时至少改为：

```dotenv
ENVIRONMENT=production
DEBUG=false
DATABASE_URL=postgresql+asyncpg://qc_user:<与POSTGRES_PASSWORD相同的密码>@postgres:5432/smart_qc_capture_system
WEB_ORIGIN=https://qc.example.com
SECRET_KEY=<至少32字节的随机值>
FEISHU_APP_SECRET=<真实值>
FEISHU_SYNC_WEBHOOK_SECRET=<长随机值>
OSS_ACCESS_KEY_ID=<RAM子账号或STS凭据>
OSS_ACCESS_KEY_SECRET=<对应密钥>
```

密码若含有 `@`、`:`、`/`、`?`、`#` 等字符，必须进行 URL 编码后再写入
`DATABASE_URL`。`WEB_ORIGIN` 必须是用户实际打开的唯一 HTTPS 地址，且不能带末尾 `/`。

### 3. 配置飞书网页应用

将以下值配置到同一个自建应用并发布生效：

- H5 首页地址：`https://qc.example.com/`
- 可信域名：`qc.example.com`
- OAuth 回调地址：`https://qc.example.com/api/v1/auth/feishu/callback`
- 多维表格自动化 Webhook：`https://qc.example.com/api/v1/integrations/feishu/order-sync`

Webhook 必须带 `X-QC-Sync-Secret`，其值与 `FEISHU_SYNC_WEBHOOK_SECRET`
一致。前端会以当前完整页面 URL 请求签名；后端只会为 `WEB_ORIGIN` 的 HTTPS
页面签名，因此域名、协议或端口不一致都会导致 `chooseImage` 失败。

### 4. 启动与验收

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps
curl -fsS https://qc.example.com/health
```

首次创建的 PostgreSQL 数据卷会自动执行 `database/init/001_schema.sql`。若迁移的是已有数据库，在发布前按序执行 `database/migrations/*.sql`（先在备份或预发环境验证）。可用容器执行：

```bash
for f in database/migrations/*.sql; do
  docker compose --env-file .env.production -f docker-compose.production.yml exec -T postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$f"
done
```

验收时在飞书手机客户端打开首页，确认 OAuth 回跳、任务列表、`chooseImage`、上传、缩略图和原图预览均正常；再从飞书多维表格触发一条测试 Webhook。排障日志：

```bash
docker compose --env-file .env.production -f docker-compose.production.yml logs -f caddy api
```
