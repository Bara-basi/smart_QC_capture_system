# 智能质检拍照系统

面向不锈钢产品质检员的拍照任务系统。业务订单从飞书多维表格同步；系统按产品类别生成拍照清单；质检员在飞书内的 H5 页面完成拍照并提交；图片归档至阿里云 OSS，可按合同和产品检索。

## 目录

```text
backend/   Python API、业务逻辑和第三方适配器
frontend/  Vue 3 飞书 H5 页面
database/  数据库迁移及初始化数据
docs/      接口、数据模型和部署说明
```

开始前请复制 `backend/.env.example` 为 `backend/.env`，并按 `docs/configuration.md` 填入配置。依赖和部署步骤见 `docs/setup.md`。
