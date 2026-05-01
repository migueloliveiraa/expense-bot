from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_TOKEN: str
    ANTHROPIC_API_KEY: str
    SPREADSHEET_ID: str
    LOG_LEVEL: str = "INFO"

    GOOGLE_CREDENTIALS_JSON: str

    class Config:
        env_file = ".env"

settings = Settings()
