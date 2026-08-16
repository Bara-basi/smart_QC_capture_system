from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.feishu"), extra="ignore")

    app_name: str = "QC Photo System"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""
    feishu_bitable_table_id: str = ""
    feishu_bitable_order_table_id: str = ""
    feishu_bitable_order_view_id: str = ""
    feishu_bitable_inspection_task_view_id: str = ""
    feishu_sync_webhook_secret: str = ""
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_preview_bucket: str = "smart-qc-capture-system-preview-images"
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_prefix: str = "orders"
    web_origin: str = ""
    secret_key: str = ""
    session_max_age_seconds: int = 28800
    feishu_sync_departments: bool = False


settings = Settings()
