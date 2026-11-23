from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PORTS = {3000, 3001}
FRONTEND_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in FRONTEND_PORTS}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model: str = "gpt-4.1"
    webmorph_data_dir: Path = ROOT / ".data"
    webmorph_max_runs: int = Field(4, ge=1, le=16)
    webmorph_idle_minutes: int = Field(45, ge=2, le=1440)
    webmorph_max_steps: int = Field(12, ge=1, le=50)

    @property
    def data_dir(self) -> Path:
        return (ROOT / self.webmorph_data_dir).resolve()


settings = Settings()
