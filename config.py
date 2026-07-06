import os
from dataclasses import dataclass

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    WEBAPP_URL: str = os.getenv("WEBAPP_URL", "https://your-domain.com")
    DB_PATH: str = os.getenv("DB_PATH", "magnit_scanner.db")
    DEFAULT_RADIUS: int = 3000
    MAGNIT_API_BASE: str = "https://magnit.ru/api"

config = Config()