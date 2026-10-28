# 共享域名入口

该目录把域名入口从 QC 项目中拆出。共享 Caddy 独占宿主机 TCP `80/443`，
按域名转发到三个项目：

| 域名变量 | 上游容器 | 项目 |
| --- | --- | --- |
| `QC_DOMAIN` | `qc-capture-web:80` | QC 质检拍照系统 |
| `ADMIN_DOMAIN` | `mtalloy-website-admin:80` | `/opt/mtalloy-admin` |
| `WEBSITE_DOMAIN` | `mtalloy-website:80` | `/opt/mtalloy-website` |

`WEBSITE_APEX_DOMAIN` 会永久跳转到 `WEBSITE_DOMAIN`。三个业务域名必须分别添加
A/AAAA 记录，指向服务器公网地址；不要继续把端口 `8080`、`8081` 暴露到公网。

## 1. 配置域名

```bash
cd /opt/QC_capture_system
cp deploy/shared-edge/.env.example deploy/shared-edge/.env
chmod 600 deploy/shared-edge/.env
```

将示例域名改成公司真实域名。然后创建 QC 的域名环境文件：

```bash
cp .env.domain.example .env.domain
chmod 600 .env.domain
```

把 `.env.domain` 的 `APP_ORIGIN` 设为真实的 `https://QC_DOMAIN`，并保持数据库配置
与现有生产环境一致。

还必须同步修改应用中的公开地址，否则网页虽然能打开，飞书登录、相机和 Webhook
仍会失败：

```dotenv
# backend/.env
WEB_ORIGIN=https://qc.example.com
```

admin 项目 `/opt/mtalloy-admin/.env` 的 `APP_ORIGIN` 也要改成
`https://admin.example.com`。

飞书自建应用需要同步修改：

- H5 首页：`https://QC_DOMAIN/`
- 可信域名：`QC_DOMAIN`
- OAuth 回调：`https://QC_DOMAIN/api/v1/auth/feishu/callback`
- 多维表格 Webhook：`https://QC_DOMAIN/api/v1/integrations/feishu/order-sync`

## 2. 切换到域名入口

先只校验 Compose 展开和 Caddy 配置，不修改运行中的服务：

```bash
cd /opt/QC_capture_system
docker compose --env-file .env.domain \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.domain.yml config >/tmp/qc-domain.compose.yml

docker run --rm \
  -e ACME_EMAIL=ops@example.com \
  -e QC_DOMAIN=qc.example.com \
  -e ADMIN_DOMAIN=admin.example.com \
  -e WEBSITE_DOMAIN=www.example.com \
  -e WEBSITE_APEX_DOMAIN=example.com \
  -v "$PWD/deploy/shared-edge/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

切换会有一个很短的入口中断，因为 `80/443` 必须从旧 QC Caddy 转交给共享入口。
建议在维护窗口执行：

```bash
# 1. 构建并启动 QC 内部 Web；此时它不再发布宿主机端口。
cd /opt/QC_capture_system
docker compose --env-file .env.domain \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.domain.yml \
  up -d --build

# 2. 启动共享入口，由它重新占用 80/443。
cd /opt/QC_capture_system/deploy/shared-edge
docker compose up -d
```

第一次启动共享入口时 Caddy 会申请三张证书，通常需要 DNS 已生效并可从公网访问
TCP `80/443`。查看日志：

```bash
cd /opt/QC_capture_system/deploy/shared-edge
docker compose ps
docker compose logs -f edge
```

## 3. 验收

```bash
curl -fsS https://qc.example.com/health
curl -fsSI https://admin.example.com/
curl -fsSI https://www.example.com/
curl -fsSI https://example.com/
```

还应确认：

- QC 首页、飞书 OAuth、相机、上传和图片预览正常。
- admin 登录、Cookie 和媒体接口正常。
- 官网静态页面与图片正常。
- `docker ps` 中只有共享入口发布 `0.0.0.0:80/443`，QC、admin、官网内部端口
  不再直接暴露公网。

## 回滚

如果新域名验收失败，可先停共享入口，再恢复原来的 IP 模式：

```bash
cd /opt/QC_capture_system/deploy/shared-edge
docker compose down

cd /opt/QC_capture_system
docker compose --env-file .env.ip \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.ip.yml \
  up -d --force-recreate
```
