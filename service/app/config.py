from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_REPO = Path(__file__).resolve().parents[2] / "hugoDocs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVAL_", env_file=".env")

    default_repo: Path | None = DEFAULT_REPO
    greptile_binary: str = "greptile"
    greptile_timeout_seconds: float = 600.0
