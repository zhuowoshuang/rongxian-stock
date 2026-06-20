from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "融衔"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./stock_agent.db"

    # JWT 配置（未设置时自动生成随机密钥，每次重启会变；生产环境请在 .env 中固定）
    JWT_SECRET_KEY: str = ""

    # Redis 配置（可选）
    REDIS_URL: Optional[str] = None

    # 数据源 API Key
    TUSHARE_TOKEN: Optional[str] = None
    FUTU_ACCESS_TOKEN: Optional[str] = None

    # LLM API 配置
    LLM_API_URL: str = "https://tokendance.space/gateway/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v4-pro"

    # CORS 配置
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# 如果 .env 中未设置 JWT_SECRET_KEY，自动生成随机密钥（开发用）
if not settings.JWT_SECRET_KEY:
    settings.JWT_SECRET_KEY = secrets.token_hex(32)
