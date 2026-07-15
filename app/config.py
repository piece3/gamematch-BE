from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

#초기 세팅
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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
    riot_tier_refresh_hours: int = 72  # 3일

    @field_validator("database_url", mode="before")

    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg2://", 1)
        return value

settings = Settings()


