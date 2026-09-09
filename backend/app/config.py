from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://apex:apex_dev_password@postgres:5432/apex_partnership"
    baileys_gateway_url: str = "http://baileys-gateway:3000"
    webhook_shared_secret: str = "dev-webhook-secret"
    apex_bot_phone: str = "27730315355"
    tutorial_pdf_path: str = "/app/tutorial-placeholder.pdf"
    apex_staff_group_phone: str = ""
    cors_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
