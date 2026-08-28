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

Start FastAPI on port 8001 and Vite on port 5173. Vite proxies every `/api/*`
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
request the needed Contact permissions for reading organization data. The login
flow uses the app-scoped `open_id` as a safe fallback when the optional **Get
user user ID** permission is not available, so basic website login is not
blocked by that permission. The system additionally records `user_id` when
provided, `union_id` (developer-scoped), and `open_department_id` values.

At the web application's root path, the client checks its session and redirects
unauthenticated visitors to Feishu automatically. After the callback succeeds,
the user is returned to the application page that initiated login (for example
`/gallery`), is upserted to PostgreSQL as an `inspector`, and receives an
eight-hour signed, HTTP-only session cookie. User and tenant tokens are not stored.

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

以 Ubuntu/Debian 为例，安装 Docker Engine 和 Compose v2 后，先确认服务可用：

```bash
sudo systemctl enable --now docker
docker --version
docker compose version
sudo usermod -aG docker "$USER" # 重新登录后可免 sudo 使用 docker
```

Caddy 会在域名正确解析、80/443 可访问后自动申请和续期 Let's Encrypt 证书。若服务器已有 Nginx/Apache 占用 80 或 443，应停用它，或改由现有反代转发至 Caddy。

### 无域名（公网 IP）模式

若服务器在香港或境外，可使用公网 IP，例如 `http://203.0.113.10`，不需要购买域名。
将 `.env.production` 的 `APP_ORIGIN` 设为该完整地址，并将 `backend/.env` 的
`WEB_ORIGIN` 设为完全相同的值；Caddy 会以 HTTP 提供服务，不会申请 TLS 证书。
飞书网页应用首页、可信来源/安全设置和 OAuth 回调地址都必须改为：

```text
http://203.0.113.10/
http://203.0.113.10/api/v1/auth/feishu/callback
```

该模式降低了传输保护等级，建议仅用于企业内部飞书用户和非敏感网络；登录 Cookie
仍为 HTTP-only，但不会带 Secure 属性。飞书控制台若拒绝 IP 作为网页应用主页或回调
地址，则该飞书租户只能使用 HTTPS 域名，不能通过代码规避。中国大陆服务器即使仅
通过 IP 提供网站，通常也需要办理 IP 地址备案；请向服务器接入商确认。

### 2. 填写配置

在仓库根目录执行：

```bash
cp .env.production.example .env.production
cp backend/.env.example backend/.env
chmod 600 .env.production backend/.env
```

编辑 `.env.production`，设置 `APP_ORIGIN`（域名 HTTPS；IP 模式请使用下文的
`.env.ip` 与 HTTPS IP 证书）、运维邮箱及强 PostgreSQL 密码。编辑
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

如需自动抓取 ERP 订单，还在 `backend/.env` 追加：

```dotenv
ERP_BASE_URL=https://<ERP地址>/
ERP_USERNAME=<ERP账号>
ERP_PASSWORD=<ERP密码>
ERP_TOKEN_FILE=/app/data/erp_session.json
ERP_PURCHASE_SNAPSHOT_FILE=/app/data/erp_purchase_snapshot.json
```

`./data` 会挂载到容器内的 `/app/data`，用于持久保存 ERP 登录 Cookie 和抓取快照；该目录已被 Git 忽略。若不希望在配置文件保存 ERP 密码，可不设置 `ERP_PASSWORD`，在登录 Cookie 失效时手动刷新。

### 3. 配置飞书网页应用

将以下值配置到同一个自建应用并发布生效：

- H5 首页地址：`https://qc.example.com/`（IP 模式则替换为 `http://公网IP/`）
- 可信域名：`qc.example.com`（IP 模式按飞书控制台实际允许的 IP 来源配置）
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

## 启动 ERP 订单抓取定时任务

ERP 抓取脚本会把新合同和产品任务写入飞书多维表格，并更新已有任务的 `质检阶段`；飞书自动化随后调用 Webhook 将数据导入本系统。因此飞书自动化和此定时任务应同时启用。

首次部署时，在 API 容器人工验证（均在仓库根目录运行）：

```bash
# 仅抓取 2 条并保存快照，不写飞书
docker compose --env-file .env.production -f docker-compose.production.yml \
  exec -T api python scripts/sync_erp_purchases.py --dry-run --limit 2

# 首次正式同步；必要时创建飞书可写的“采购时间”字段
docker compose --env-file .env.production -f docker-compose.production.yml \
  exec -T api python scripts/sync_erp_purchases.py --ensure-schema
```

确认没有 `ERROR:` 后，使用宿主机 cron 每 15 分钟运行一次。`flock` 防止上一次抓取未结束时并发执行，日志放在不会提交 Git 的 `data/`：

```bash
crontab -e
*/15 * * * * flock -n /tmp/smart-qc-erp-sync.lock sh -lc 'cd /opt/smart-qc-capture-system && docker compose --env-file .env.production -f docker-compose.production.yml exec -T api python scripts/sync_erp_purchases.py >> data/erp-sync.log 2>&1'
```

API 容器重启或更新后不需要重设 cron。查看任务结果：

```bash
tail -n 100 data/erp-sync.log
docker compose --env-file .env.production -f docker-compose.production.yml exec -T api \
  sh -c 'ls -l /app/data/erp_session.json /app/data/erp_purchase_snapshot.json'
```

## 无域名部署：公网 IP + HTTPS

如果不想注册或备案域名，可以使用服务器的**固定公网 IP** 访问。不能改用裸
HTTP 或自签名 HTTPS：飞书对生产服务要求 HTTPS，而 iPhone 通常不会信任自签名
证书。飞书网页应用文档允许配置公网地址；其社区的 Web 应用示例也展示了 IP
形式的回调地址。[飞书网页应用配置指南](https://open.feishu.cn/document/uYjL24iN/uMTMuMTMuMTM/development-guide/step1)

Let’s Encrypt 从 2026 年起正式支持公网 IP 证书，但 IP 证书仅有效约 6 天，
必须自动续期。[Let’s Encrypt 说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html)
本仓库的 `Caddyfile.ip` 和 `docker-compose.ip.yml` 已支持这一模式；证书由宿主机
上的 Certbot 管理，Caddy 只读取证书。

### IP 模式配置

1. 确保 IP 是固定的公网 IPv4，且 TCP 80、443 从互联网可达；复制
   `.env.ip.example` 为 `.env.ip`，填写 `APP_IP`、邮箱和数据库密码。
2. 复制 `backend/.env.example` 为 `backend/.env`，并设置：

   ```dotenv
   ENVIRONMENT=production
   DEBUG=false
   DATABASE_URL=postgresql+asyncpg://qc_user:<URL编码后的数据库密码>@postgres:5432/smart_qc_capture_system
   WEB_ORIGIN=https://<APP_IP>
   SECRET_KEY=<至少32字节随机值>
   ```

3. 在宿主机安装 **Certbot 5.4 或更新版本**。首次申请证书前，80 端口不能被其他
   服务占用；使用 standalone 方式：

   ```bash
   sudo certbot certonly --standalone --preferred-profile shortlived --ip-address <APP_IP>
   ```

   Certbot 的 IP 证书参数和版本要求见其[官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

4. 启动 IP 部署：

   ```bash
   docker compose --env-file .env.ip \
     -f docker-compose.production.yml -f docker-compose.ip.yml up -d --build
   ```

5. 设置宿主机每日续期。首次证书完成后，Caddy 会通过 `certbot-webroot/` 提供 ACME
   校验文件。先把首次申请时的 `standalone` 验证方式改为 `webroot`；否则 Caddy
   占用 80 端口后，`certbot renew` 会失败：

   ```bash
   sudo certbot reconfigure --webroot \
     --webroot-path /opt/smart-qc-capture-system/certbot-webroot \
     --preferred-profile shortlived --ip-address <APP_IP> \
     --deploy-hook 'cd /opt/smart-qc-capture-system && docker compose --env-file .env.ip -f docker-compose.production.yml -f docker-compose.ip.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile'
   sudo certbot renew --dry-run
   ```

   然后设置每日续期；证书更新后 Caddy 会自动重载，过程中无需停服务：

   ```bash
   sudo crontab -e
   # 每天 03:15 尝试续期；deploy-hook 已由 certbot reconfigure 持久保存
   15 3 * * * certbot renew --quiet
   ```

飞书后台改为配置：H5 首页 `https://<APP_IP>/`，OAuth 回调
`https://<APP_IP>/api/v1/auth/feishu/callback`，Webhook
`https://<APP_IP>/api/v1/integrations/feishu/order-sync`。如果控制台的“可信域名”
字段不接受 IP，请保留首页/回调为 IP 后先在测试应用验证；该字段的具体校验会随飞书
租户与控制台版本而变化。

此方案省去自有域名，但不应被视为规避当地法规或云厂商要求；若服务器在中国大陆，
仍应以云厂商和当地监管对公网 IP 服务的要求为准。
