from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./sentinel.db"
    redis_url: str = ""
    jwt_secret: str = Field(min_length=32)
    collector_key: str = Field(min_length=32)
    admin_password: str = Field(min_length=12)
    admin_username: str = "admin"
    demo_enabled: bool = False
    rules_path: str = "rules/detections.yaml"
    token_minutes: int = 60
    opensearch_url: str = ""
    opensearch_username: str = ""
    opensearch_password: str = ""
    ai_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ai_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ai_max_daily_requests: int = Field(default=100, ge=1, le=10000)
    notifications_enabled: bool = False
    slack_webhook_url: str = ""
    discord_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_starttls: bool = True
    refresh_days: int = 7
    event_retention_days: int = Field(default=30, ge=1, le=3650)
    job_retention_days: int = Field(default=7, ge=1, le=365)
    database_host: str = ""
    database_username: str = "sentinel"
    database_password: str = ""
    database_name: str = "sentinel"

    def model_post_init(self, context):
        if self.database_host:
            from sqlalchemy import URL

            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.database_username,
                password=self.database_password,
                host=self.database_host,
                database=self.database_name,
                query={"sslmode": "require"},
            ).render_as_string(hide_password=False)

    opensearch_aws_auth: bool = False
    aws_region: str = "ap-south-2"
