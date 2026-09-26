from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "shopping_agent"
DEFAULT_CONFIG = AGENT_ROOT / "configs/v1.json"
DEFAULT_ENV = AGENT_ROOT / ".env"


def load_dotenv(path: Path = DEFAULT_ENV) -> None:
    """Load simple KEY=VALUE entries without overriding the process environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve_project_path(value: str, default: Path) -> Path:
    raw = Path(value) if value else default
    return raw if raw.is_absolute() else PROJECT_ROOT / raw


def _origins(value: str) -> tuple[str, ...]:
    """Comma-separated origins, without trailing slashes; a browser sends "https://host" exactly."""
    return tuple(dict.fromkeys(item.strip().rstrip("/") for item in value.split(",") if item.strip()))


@dataclass(frozen=True)
class AgentSettings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    database_path: Path
    session_days: int
    llm_provider: str
    openai_api_key: str
    openai_model: str
    openai_fallback_model: str
    gemini_api_key: str
    gemini_model: str
    langsmith_tracing: bool
    langsmith_project: str
    catalog_mode: str
    config: dict[str, Any]

    @classmethod
    def load(cls, *, env_path: Path = DEFAULT_ENV, config_path: Path = DEFAULT_CONFIG) -> "AgentSettings":
        load_dotenv(env_path)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        provider = os.getenv("SHOPPING_AGENT_LLM_PROVIDER", "auto").strip().casefold()
        if provider not in {"auto", "openai", "gemini", "deterministic"}:
            raise ValueError("SHOPPING_AGENT_LLM_PROVIDER must be auto, openai, gemini, or deterministic")
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if provider == "auto":
            provider = "openai" if openai_key else "gemini" if gemini_key else "deterministic"
        if provider == "openai" and not openai_key:
            raise ValueError("OPENAI_API_KEY is required when the OpenAI provider is selected")
        if provider == "gemini" and not gemini_key:
            raise ValueError("GEMINI_API_KEY is required when the Gemini provider is selected")
        catalog_mode = os.getenv("SHOPPING_AGENT_CATALOG", "curated").strip().casefold()
        if catalog_mode not in {"curated", "full"}:
            raise ValueError("SHOPPING_AGENT_CATALOG must be curated or full")
        default_db = AGENT_ROOT / "data/agent_v1.sqlite3"
        database_path = _resolve_project_path(
            os.getenv("SHOPPING_AGENT_DB", "shopping_agent/data/agent_v1.sqlite3"),
            default_db,
        )
        return cls(
            host=os.getenv("SHOPPING_AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("SHOPPING_AGENT_PORT", "8878")),
            cors_origins=_origins(
                os.getenv("SHOPPING_AGENT_CORS_ORIGINS") or os.getenv("SHOPPING_AGENT_CORS_ORIGIN", "http://127.0.0.1:8878")
            ),
            database_path=database_path,
            session_days=int(os.getenv("SHOPPING_AGENT_SESSION_DAYS", str(config["auth"]["session_days"]))),
            llm_provider=provider,
            openai_api_key=openai_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip(),
            # Empty disables the fallback; the default comes from configs/v1.json tool_agent.fallback_model.
            openai_fallback_model=os.getenv(
                "OPENAI_FALLBACK_MODEL", str(config.get("tool_agent", {}).get("fallback_model", ""))
            ).strip(),
            gemini_api_key=gemini_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip(),
            langsmith_tracing=os.getenv("LANGSMITH_TRACING", "false").casefold() in {"1", "true", "yes"},
            langsmith_project=os.getenv("LANGSMITH_PROJECT", "material-shopping-agent-v1"),
            catalog_mode=catalog_mode,
            config=config,
        )

