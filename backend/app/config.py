"""Application settings, read from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Пульс города"
    city_name: str = "Павлодар"
    database_url: str = "postgresql+psycopg://pulse:pulse@localhost:5432/pulse"

    # Security
    secret_key: str = "change-me-in-env"
    author_hash_salt: str = "change-me-too"
    access_token_minutes: int = 12 * 60
    cors_origins: str = "http://localhost:5173"

    # AI
    anthropic_api_key: str = ""
    llm_model_enrich: str = "claude-haiku-5-5"
    llm_model_summary: str = "claude-sonnet-5-5"
    llm_parallelism: int = 8
    llm_timeout_s: float = 30.0
    review_confidence_threshold: float = 0.6
    prompt_version: str = "enrich-v1"

    # Embeddings: "auto" tries sentence-transformers, falls back to TF-IDF
    embedding_backend: str = "auto"
    embedding_model: str = "intfloat/multilingual-e5-small"
    cluster_threshold: float = 0.55

    # Telegram
    telegram_bot_token: str = ""
    telegram_alert_chat_id: str = ""
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "data/telethon.session"

    # Public URL of this deployment (OAuth redirects for Instagram/Threads)
    public_base_url: str = "http://localhost:8000"

    # Instagram (Meta). Instagram API with Instagram Login by default (graph.instagram.com);
    # set INSTAGRAM_API_HOST=graph.facebook.com when using a Facebook Login token (business discovery, hashtags).
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_access_token: str = ""      # optional manual long-lived token instead of the Connect button
    instagram_user_id: str = ""
    instagram_api_host: str = "graph.instagram.com"
    meta_graph_version: str = "v26.0"
    instagram_scopes: str = "instagram_business_basic,instagram_business_manage_comments,instagram_business_manage_messages"

    # Threads (Meta)
    threads_app_id: str = ""
    threads_app_secret: str = ""
    threads_access_token: str = ""        # optional manual long-lived token
    threads_api_host: str = "graph.threads.com"
    threads_scopes: str = "threads_basic,threads_read_replies,threads_keyword_search"

    # Scheduler
    scheduler_enabled: bool = True
    collect_interval_minutes: int = 60
    bot_poll_seconds: int = 20

    # Direct messages retention (3.7.4: shorter retention)
    direct_retention_days: int = 90

    # Seed
    seed_admin_password: str = "admin123"
    seed_operator_password: str = "operator123"
    seed_viewer_password: str = "viewer123"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
