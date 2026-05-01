from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_TOKEN: str
    ANTHROPIC_API_KEY: str
    SPREADSHEET_ID: str
    LOG_LEVEL: str = "INFO"

    # Credenciais Google: ficheiro local (dev) ou JSON em string (produção)
    GOOGLE_CREDENTIALS_PATH: str = "credentials.json"
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None  # conteúdo do JSON como string

    class Config:
        env_file = ".env"

settings = Settings()
