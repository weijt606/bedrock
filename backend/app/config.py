"""Runtime configuration. Everything is env-driven; nothing is baked in."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_local_env() -> None:
    """Load developer-only values from the repository `.env` file.

    Deployed environments keep precedence, and `.env` stays ignored by git.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- Cala: the only source of facts -----------------------------------
    cala_key: str = os.environ.get("CALA_API_KEY", "")
    cala_base: str = os.environ.get("CALA_BASE", "https://api.cala.ai")

    # --- the reasoning engine (plans, parses, reads labels; never asserts) -
    # Two ways to reach a frontier model. OpenAI directly if a key is set;
    # otherwise Pioneer, whose gateway is OpenAI-compatible and serves the same
    # models on the key we already have for the specialists. That means one key
    # is enough to light up vision and the planner, instead of two.
    openai_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base: str = os.environ.get("OPENAI_BASE", "https://api.openai.com/v1")
    model_planner: str = os.environ.get("MODEL_PLANNER", "")
    model_vision: str = os.environ.get("MODEL_VISION", "")

    # --- Pioneer: the fine-tuned specialist for classification/extraction --
    pioneer_key: str = os.environ.get("PIONEER_API_KEY", "")
    # Native endpoint is /inference (the OpenAI-compatible one lives under /v1).
    pioneer_base: str = os.environ.get("PIONEER_BASE", "https://api.pioneer.ai")
    # A GLiNER2 encoder answers in ~100ms; swap in a fine-tuned job id (job_...)
    # once scripts/train_assay.py has produced one.
    model_assay: str = os.environ.get("MODEL_ASSAY", "fastino/gliner2-base-v1")
    assay_threshold: float = _f("ASSAY_THRESHOLD", 0.5)
    # The reader turns Cala prose back into a table. GLiNER2 large by default;
    # swap in a fine-tuned job id once scripts/train_assay.py train-reader is done.
    model_reader: str = os.environ.get("MODEL_READER", "fastino/gliner2-large-v1")
    reader_timeout_s: float = _f("READER_TIMEOUT_S", 15.0)
    pioneer_adaptive: bool = os.environ.get("PIONEER_ADAPTIVE", "1") == "1"

    # --- fal: speech to text, and background removal for the shelf --------
    fal_key: str = os.environ.get("FAL_KEY", "")
    fal_stt_model: str = os.environ.get("FAL_STT_MODEL", "fal-ai/whisper")

    # --- speed budget ------------------------------------------------------
    # Cala is 16-75s cold and ~0.5s warm. Everything here is tuned around that:
    # probes run concurrently, each one is capped, and a probe that blows its
    # budget becomes a Gap instead of stalling the dig.
    probe_timeout_s: float = _f("PROBE_TIMEOUT_S", 90.0)
    total_budget_s: float = _f("TOTAL_BUDGET_S", 150.0)
    max_concurrent_probes: int = int(os.environ.get("MAX_CONCURRENT_PROBES", "4"))
    assay_timeout_s: float = _f("ASSAY_TIMEOUT_S", 12.0)
    planner_timeout_s: float = _f("PLANNER_TIMEOUT_S", 10.0)

    cache_dir: str = os.environ.get("CACHE_DIR", ".cache")
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:4173,http://127.0.0.1:4173,http://localhost:5173,http://localhost:8000"
        ).split(",")
    )

    @property
    def has_cala(self) -> bool:
        return bool(self.cala_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_key)

    # ---- resolved reasoning provider -------------------------------------
    @property
    def llm_provider(self) -> str:
        """'openai' | 'pioneer' | 'none'. OpenAI wins when both are configured."""
        if self.openai_key:
            return "openai"
        if self.pioneer_key:
            return "pioneer"
        return "none"

    @property
    def has_llm(self) -> bool:
        return self.llm_provider != "none"

    @property
    def llm_base(self) -> str:
        return self.openai_base if self.llm_provider == "openai" else f"{self.pioneer_base}/v1"

    @property
    def llm_headers(self) -> dict[str, str]:
        """Pioneer authenticates with X-API-Key, OpenAI with a bearer token."""
        if self.llm_provider == "openai":
            return {"Authorization": f"Bearer {self.openai_key}"}
        return {"X-API-Key": self.pioneer_key}

    @property
    def planner_model(self) -> str:
        if self.model_planner:
            return self.model_planner
        return "gpt-4o-mini" if self.llm_provider == "openai" else "gpt-5.6-sol"

    @property
    def vision_model(self) -> str:
        if self.model_vision:
            return self.model_vision
        return "gpt-4o-mini" if self.llm_provider == "openai" else "gpt-5.6-sol"

    @property
    def has_pioneer(self) -> bool:
        return bool(self.pioneer_key)

    @property
    def has_fal(self) -> bool:
        return bool(self.fal_key)


settings = Settings()
