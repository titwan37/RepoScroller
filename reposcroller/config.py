"""Configuration management for RepoScroller using Pydantic Settings."""

from pathlib import Path
from typing import List, Union, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core App
    APP_NAME: str = "RepoScroller"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "127.0.0.1"
    PORT: int = 8090

    # Database
    DB_PATH: Path = Field(default=Path("reposcroller_ledger.db"))
    SQLITE_TIMEOUT: float = 30.0

    # Storage Mounts
    STORAGE_ROOTS: List[str] = Field(
        default_factory=lambda: [
            r"\\SyNAS\xcloud\docs",
            r"\\SyNAS\xcloud\LawSuiteRAG",
            r"\\SyNAS\CloudSpace\LexSpace",
            r"H:\My Drive",
            r"L:\My Drive",
            r"G:\My Drive",
        ]
    )

    # File extensions to ingest
    SUPPORTED_EXTENSIONS: List[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".txt", ".md", ".eml"]
    )

    # Directories to ignore during traversal
    IGNORE_DIRS: List[str] = Field(
        default_factory=lambda: [
            ".git", ".venv", "venv", "node_modules",
            "__pycache__", ".pytest_cache", ".vscode",
            ".continue", ".system_generated", "$RECYCLE.BIN",
            "System Volume Information"
        ]
    )

    # Crawler settings
    POLL_INTERVAL_SECONDS: int = 10
    FAST_SCAN_ENABLED: bool = True
    SCAN_ORDER: str = "antichronological"  # 'antichronological' (newest first), 'chronological', 'alphabetical', or 'default'
    SCAN_PARALLEL_WORKERS: int = 6  # Number of concurrent threads in the worker pool (1 per storage root)
    MAX_FILE_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MB limit per file

    # SimHash & Deduplication thresholds
    # 64-bit SimHash hamming distance:
    # 0: Bitwise identical text
    # 1-3: Near-exact duplicate (e.g. whitespace or minute edit)
    # 4-12: Evolved version / draft / partial revision (>= 81.25% similarity)
    # >12: Distinct content
    SIMHASH_EXACT_THRESHOLD: int = 3
    SIMHASH_HAMMING_THRESHOLD: int = 12
    SIMILARITY_SCORE_THRESHOLD: float = 0.80

    # Heuristic Maturity Weights (sum to 1.0)
    MATURITY_WEIGHT_COMPLETENESS: float = 0.35
    MATURITY_WEIGHT_SIGNATURES: float = 0.25
    MATURITY_WEIGHT_DATE: float = 0.20
    MATURITY_WEIGHT_NAMING: float = 0.20

    # LLM Categorization & Analysis settings
    LLM_PROVIDER: str = "auto"  # 'auto', 'openrouter', 'ollama', or 'heuristic'
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "google/gemini-2.0-flash-001"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    @field_validator("STORAGE_ROOTS", "SUPPORTED_EXTENSIONS", "IGNORE_DIRS", mode="before")
    @classmethod
    def parse_list(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


settings = Settings()
