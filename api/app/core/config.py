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

    # AWS Infrastructure
    AWS_REGION: str = "ap-southeast-2"

    # Amazon Bedrock & Claude LLM Foundation (Phase 10 Step 1)
    BEDROCK_REGION: str | None = None
    BEDROCK_MODEL_ID: str = "anthropic.claude-sonnet-4-6"
    BEDROCK_ALLOWED_MODELS: Union[list[str], str] = [
        "anthropic.claude-sonnet-4-6",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-5-haiku-20241022-v1:0",
    ]
    BEDROCK_MAX_TOKENS: int = 4096
    BEDROCK_TIMEOUT_SECONDS: float = 30.0
    BEDROCK_MAX_RETRIES: int = 3
    BEDROCK_BACKOFF_BASE_SECONDS: float = 0.5
    BEDROCK_BACKOFF_MAX_SECONDS: float = 4.0
    LLM_PROVIDER: str = "bedrock"  # "bedrock" or "mock"

    @property
    def effective_bedrock_region(self) -> str:
        """Resolve Bedrock region: fallback to AWS_REGION if BEDROCK_REGION not explicitly set."""
        return (self.BEDROCK_REGION or self.AWS_REGION or "ap-southeast-2").strip()

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
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[list[str], str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("BEDROCK_ALLOWED_MODELS", mode="before")
    @classmethod
    def parse_allowed_models(cls, v: Union[list[str], str]) -> list[str]:
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v

    @model_validator(mode="after")
    def validate_bedrock_configuration(self) -> "Settings":
        """Validate Bedrock LLM configuration at startup without making external AWS network calls."""
        if not self.BEDROCK_MODEL_ID or not self.BEDROCK_MODEL_ID.strip():
            raise ValueError("BEDROCK_MODEL_ID cannot be empty.")

        allowed = self.BEDROCK_ALLOWED_MODELS if isinstance(self.BEDROCK_ALLOWED_MODELS, list) else []
        if self.BEDROCK_MODEL_ID not in allowed:
            raise ValueError(
                f"Configured BEDROCK_MODEL_ID '{self.BEDROCK_MODEL_ID}' is not permitted by BEDROCK_ALLOWED_MODELS allowlist: {allowed}"
            )

        if self.BEDROCK_MAX_TOKENS <= 0 or self.BEDROCK_MAX_TOKENS > 16384:
            raise ValueError(f"BEDROCK_MAX_TOKENS must be between 1 and 16384, got {self.BEDROCK_MAX_TOKENS}.")

        if self.BEDROCK_TIMEOUT_SECONDS <= 0:
            raise ValueError(f"BEDROCK_TIMEOUT_SECONDS must be positive, got {self.BEDROCK_TIMEOUT_SECONDS}.")

        if self.BEDROCK_MAX_RETRIES < 0 or self.BEDROCK_MAX_RETRIES > 10:
            raise ValueError(f"BEDROCK_MAX_RETRIES must be between 0 and 10, got {self.BEDROCK_MAX_RETRIES}.")

        return self

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
