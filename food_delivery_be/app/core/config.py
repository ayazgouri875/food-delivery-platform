from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Food Delivery Platform"
    DATABASE_URL: str = "postgresql+psycopg2://postgres@localhost:5432/food_delivery"
    SECRET_KEY: str = "supersecretjwtkey_for_development_change_in_production_12345678"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
