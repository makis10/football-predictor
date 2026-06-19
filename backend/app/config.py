from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://user:password@db:5432/football_db"
    model_version: str = "1.0.0"
    api_football_key: str = ""
    admin_api_key: str = ""   # set in .env — required for /admin/* endpoints
    # Connection pool — raise in high-traffic deployments
    db_pool_size: int = 10
    db_max_overflow: int = 20

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
        "protected_namespaces": ("settings_",),
    }


settings = Settings()
