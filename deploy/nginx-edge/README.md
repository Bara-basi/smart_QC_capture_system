# QC 独立 Nginx 入口

该目录把公网入口从 QC 项目的 Caddy 中拆出。独立 Nginx 接管宿主机
`80/443`，QC 的 Caddy 只作为共享 Docker 网络内的 HTTP Web 服务。

## 保持不变的访问方式

| 公网地址 | Nginx 上游 | 行为 |
| --- | --- | --- |
| `https://47.96.9.22` | `qc-capture-web:80` | 保留当前 QC IP 访问 |
| `https://www.mtalloypiping.com` | `mtalloy-website-admin:80` | 原域名、原上游不变 |
| `https://mtalloypiping.com` | 无 | 继续 301 到 `www` |
| `https://qc.mtsco.cn` | `qc-capture-web:80` | 备案完成后启用 |

入口 Nginx 只替换 Caddy 的公网代理位置。`mtalloypiping.com` 的 DNS、CDN、
admin 容器、Nginx、环境变量和数据都不修改。

## 当前阶段

`qc.mtsco.cn` 目前只放在 `templates/` 中，不参与 Nginx 启动。必须先完成：

1. 确认 `mtsco.cn` 的域名持有者和 ICP 备案有效；
2. `qc.mtsco.cn` 解析到服务器公网 IP；
3. 为 `qc.mtsco.cn` 签发证书；
4. 再把模板复制到 `conf.d/30-qc-domain.conf` 并重载。

在备案完成前，QC 继续通过 `https://47.96.9.22` 使用，不影响入口端口迁移。

## 1. 准备现有证书

Nginx 使用 `certs/` 中的稳定文件，避免直接依赖 Caddy 的内部存储路径：

```bash
cd /opt/QC_capture_system/deploy/nginx-edge
chmod 700 prepare-existing-certificates.sh publish-certificate.sh
./prepare-existing-certificates.sh
```

脚本只把当前有效的 IP、根域名和 `www` 证书复制到被 Git 忽略的 `certs/`
目录，不改 Caddy 证书。确认权限：

```bash
find certs -type f -printf '%m %p\n'
```

私钥应为 `600`，证书应为 `644`。

## 2. 在临时端口验证官网入口

临时配置只绑定本机 `28080/28443`，不会影响线上 `80/443`：

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
docker compose exec nginx nginx -t
docker compose exec nginx wget -qO- http://127.0.0.1:8080/healthz
```

验证官网的 HTTPS、跳转和静态资源。`--resolve` 会让请求连接临时端口，但保留正式
Host 和 SNI：

```bash
curl -fsSI \
  --resolve www.mtalloypiping.com:28443:127.0.0.1 \
  https://www.mtalloypiping.com:28443/

curl -sSI \
  --resolve mtalloypiping.com:28443:127.0.0.1 \
  https://mtalloypiping.com:28443/
```

第二条应继续返回 `301`，目标为 `https://www.mtalloypiping.com/...`。静态资源、
新闻和 admin API 也应逐项检查；不要只看首页。

## 3. 解除 QC Caddy 的公网端口

`docker-compose.internal-web.yml` 用 `!override` 清空 Caddy 的宿主机端口映射，
并让 `WEB_ORIGIN` 跟随 `APP_ORIGIN`。备案完成前继续使用 `.env.ip`：

```bash
cd /opt/QC_capture_system
docker compose --env-file .env.ip \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.internal-web.yml \
  config >/tmp/qc-internal.compose.yml
```

确认展开结果中的 `caddy` 没有 `ports`、只有 `expose: 80`，`WEB_ORIGIN` 仍是当前
IP 地址。

## 4. 维护窗口切换

先停临时 Nginx，再把 QC Caddy 改为内部 Web，最后由正式 Nginx 接管 `80/443`：

```bash
cd /opt/QC_capture_system/deploy/nginx-edge
docker compose -f docker-compose.yml -f docker-compose.test.yml down

cd /opt/QC_capture_system
docker compose --env-file .env.ip \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.internal-web.yml \
  up -d --build

cd deploy/nginx-edge
docker compose up -d
```

第二步会让旧 Caddy 失去宿主机端口，第三步立即由 Nginx 接管，中间有很短的入口
中断。切换后检查：

```bash
docker compose ps
curl -fsS https://47.96.9.22/health
curl -fsSI https://www.mtalloypiping.com/
curl -fsSI https://mtalloypiping.com/
```

QC 还需在飞书手机端验证 OAuth、拍照、上传和原图预览；官网需验证首页、新闻、
图片、后台登录和 `api/health`。

## 5. 证书续期

入口切换后旧 Caddy 不再负责公网证书续期。现有证书到期前必须把三组证书纳入
Certbot：

- `47.96.9.22`
- `mtalloypiping.com`
- `www.mtalloypiping.com`

证书续期后通过部署钩子把新文件发布给 Nginx 并重载：

```bash
sudo certbot reconfigure --cert-name 47.96.9.22 \
  --webroot \
  --webroot-path /opt/QC_capture_system/certbot-webroot \
  --preferred-profile shortlived \
  --ip-address 47.96.9.22 \
  --deploy-hook /opt/QC_capture_system/deploy/nginx-edge/publish-certificate.sh
```

`publish-certificate.sh` 会读取 Certbot 的 `RENEWED_LINEAGE`，更新 `certs/` 下对应
证书并执行 `nginx -s reload`。Nginx 继续使用现有的
`certbot-webroot/.well-known/acme-challenge/` 路径，因此 IP 证书的 webroot 验证
无需改路径。如果 `www` 通过 CDN 时 HTTP-01 校验无法回源，应为官网使用 DNS-01
校验，而不是关闭 CDN 或改变官网域名。

官网两个证书也应各自通过 Certbot 新建或接管，并在签发时保存同一个 deploy hook。
切换前必须先确认 `certbot renew --dry-run` 对三个证书全部通过，再由宿主机现有
每日 `certbot renew` 自动续期。

## 6. 启用 qc.mtsco.cn

ICP 备案和 DNS 生效后：

1. 为 `qc.mtsco.cn` 单独签发证书；
2. 执行 `./publish-certificate.sh qc.mtsco.cn`；
3. 把 `templates/qc.mtsco.cn.conf` 复制为
   `conf.d/30-qc-domain.conf`；
4. 将 QC 的 `.env.domain`、`WEB_ORIGIN` 和飞书后台切到
   `https://qc.mtsco.cn`；
5. 执行 `docker exec mtsco-edge-nginx nginx -t`，验证通过后再 reload。

## 回滚

如果切换失败：

```bash
cd /opt/QC_capture_system/deploy/nginx-edge
docker compose down

cd /opt/QC_capture_system
docker compose --env-file .env.ip \
  -f docker-compose.production.yml \
  -f docker-compose.build-proxy.yml \
  -f docker-compose.ip.yml \
  up -d --force-recreate
```

回滚只会恢复 QC Caddy 的原有公网入口；`mtalloypiping.com` 项目本身始终未修改。
