from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret: str = "change-me"
    database_url: str = "sqlite+aiosqlite:///data/finance.db"
    ollama_url: str = "http://ollama:11434"
    ollama_vision_model: str = "qwen2.5vl:7b"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
