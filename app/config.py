from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#초기 세팅
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+psycopg2://gamematch:gamematch@localhost:5432/gamematch"
    allowed_email_domain: str = "jnu.ac.kr"
    secret_key: str 
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    email_verify_token_expire_hours: int = 24
    app_base_url: str = "http://127.0.0.1:8000"
    email_dev_mode: bool = True
    
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "noreply@example.com"
    mail_from_name: str = "Game Match"

    cors_origins: str = "http://localhost:5173,https://simulooker.github.io"

    # Riot Games API (key는 .env / Render Environment에만 저장)
    riot_api_key: str = ""
    riot_platform: str = "kr"  # kr, na1, ...
    riot_regional: str = "asia"  # asia, americas, europe
    riot_tier_refresh_minutes: int = 10
    nexon_api_key: str = ""
    fc_online_api_base_url: str = "https://open.api.nexon.com/fconline/v1"
    fc_online_refresh_minutes: int = 10
    fc_online_request_timeout_seconds: float = 15.0
    email_resend_cooldown_seconds: int = 60

    @field_validator("database_url", mode="before")

    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg2://", 1)
        return value

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment.lower() != "production":
            return self
        if len(self.secret_key) < 32:
            raise ValueError("production SECRET_KEY must be at least 32 characters")
        if self.email_dev_mode:
            raise ValueError("EMAIL_DEV_MODE must be false in production")
        required_smtp = (
            self.smtp_host,
            self.smtp_user,
            self.smtp_password,
            self.mail_from,
        )
        if not all(required_smtp):
            raise ValueError("SMTP settings are required in production")
        if not self.app_base_url.startswith("https://"):
            raise ValueError("APP_BASE_URL must use HTTPS in production")
        return self

settings = Settings()


