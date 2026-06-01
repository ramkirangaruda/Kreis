from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    secret_key: str

    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    app_name: str = "KREIS IMS"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False
    )


settings = Settings()