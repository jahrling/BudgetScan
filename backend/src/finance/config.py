from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret: str = "change-me"
    secret_key: str = ""  # session signing; required in prod
    database_url: str = "sqlite+aiosqlite:///data/finance.db"
    ollama_url: str = "http://ollama:11434"
    ollama_base_url: str = ""  # alias accepted from .env; falls back to ollama_url
    ollama_vision_model: str = "qwen2.5vl:7b"
    ollama_text_model: str = "qwen2.5:7b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 120.0
    receipts_dir: str = "data/receipts"
    receipt_staging_dir: str = ""  # alias; falls back to receipts_dir
    max_receipt_upload_bytes: int = 10 * 1024 * 1024

    # Local vector index for the summarization/RAG layer (prose only — never
    # transaction numbers). Lives under data/ so it stays gitignored.
    vector_index_dir: str = "data/vector"

    # Dropbox archive
    dropbox_access_token: str = ""
    dropbox_root_folder: str = "/finance-receipts"
    dropbox_backup_folder: str = "/finance-backups/db"

    # Runtime mode
    app_env: str = "development"  # set to "production" to enforce required keys

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def model_post_init(self, __context: object) -> None:
        # Aliases: prefer the newer env names if set, otherwise keep originals.
        if self.ollama_base_url:
            object.__setattr__(self, "ollama_url", self.ollama_base_url)
        if self.receipt_staging_dir:
            object.__setattr__(self, "receipts_dir", self.receipt_staging_dir)


settings = Settings()


REQUIRED_PROD_KEYS = ("secret_key", "dropbox_access_token")


def require_production_secrets() -> None:
    """Raise if any required production key is missing. Called from main.lifespan."""
    if settings.app_env != "production":
        return
    missing = [k for k in REQUIRED_PROD_KEYS if not getattr(settings, k, "")]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables for production: {', '.join(missing)}"
        )
