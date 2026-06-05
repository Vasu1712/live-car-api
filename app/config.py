"""Application Configuration"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    app_name: str = "Live Car API"
    app_version: str = "0.1.0"
    debug: bool = False
    port: int = 8000
    host: str = "0.0.0.0"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
