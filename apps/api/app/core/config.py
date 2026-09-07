from urllib.parse import quote_plus
from typing import Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "RiskWise API"
    VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    API_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # CORS configuration
    CORS_ORIGINS: Union[list[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Database configuration (resolved from environment variables)
    DATABASE_URL: str | None = None
    DB_HOST: str | None = None
    DB_PORT: int | str = 5432
    DB_NAME: str | None = None
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None

    # AWS
    AWS_REGION: str = "ap-southeast-2"

    # Google OAuth 2.0 (Server-side credentials & callback)
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None

    @property
    def is_google_oauth_configured(self) -> bool:
        """Check whether Google OAuth client credentials and redirect URI are populated."""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.GOOGLE_REDIRECT_URI)

    # Application Session & Storage
    SESSION_COOKIE_NAME: str = "riskwise_session"
    SESSION_MAX_AGE_SECONDS: int = 604800  # 7 days
    SESSION_SAME_SITE: str = "lax"
    SESSION_SECURE: bool | None = None
    REDIS_URL: str | None = None
    FRONTEND_URL: str = "http://localhost:3000"

    @property
    def session_cookie_secure(self) -> bool:
        """Return True if session cookies should have the Secure flag set (HTTPS)."""
        if self.SESSION_SECURE is not None:
            return self.SESSION_SECURE
        return self.APP_ENV.lower() == "production"

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[list[str], str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def assemble_db_url(self) -> "Settings":
        """Assemble or format DATABASE_URL using psycopg driver without exposing secrets."""
        if not self.DATABASE_URL and self.DB_HOST and self.DB_USER and self.DB_NAME:
            user = quote_plus(str(self.DB_USER))
            password = quote_plus(str(self.DB_PASSWORD)) if self.DB_PASSWORD else ""
            auth = f"{user}:{password}@" if password else f"{user}@"
            self.DATABASE_URL = f"postgresql+psycopg://{auth}{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        elif self.DATABASE_URL and self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        return self


settings = Settings()
