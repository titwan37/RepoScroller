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
    DB_PATH: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "data" / "reposcroller_ledger.db")
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
        default_factory=lambda: [".pdf", ".docx", ".txt", ".md", ".eml", ".xml"]
    )

    # Swiss Law & Fedlex Storage Roots
    SWISS_LAW_ROOTS: List[str] = Field(
        default_factory=lambda: [
            r"\\SyNAS\CloudSpace\LexSpace",
            r"\\SyNAS\xcloud\LawSuiteRAG",
        ]
    )

    # Swiss Federal Law SR/RS Code Mapping (FR / DE / EN / IT)
    SWISS_LAW_MAP: dict[str, str] = Field(
        default_factory=lambda: {
            # SR 101: Federal Constitution
            "CST": "101", "BV": "101",
            # SR 142.20: Foreign Nationals and Integration Act
            "LEI": "142.20", "AIG": "142.20", "FNIA": "142.20",
            # SR 173.110: Federal Supreme Court Act
            "LTF": "173.110", "BGG": "173.110", "LCA": "173.110", "FSCA": "173.110",
            # SR 210: Civil Code
            "CC": "210", "ZGB": "210",
            # SR 220: Code of Obligations
            "CO": "220", "OR": "220",
            # SR 272: Civil Procedure Code
            "CPC": "272", "ZPO": "272",
            # SR 273: Federal Civil Procedure Act
            "PCF": "273", "BZP": "273",
            # SR 281.1: Debt Collection and Bankruptcy Act
            "LP": "281.1", "SCHKG": "281.1", "DEBA": "281.1",
            # SR 311.0: Criminal Code
            "CP": "311.0", "STGB": "311.0", "SCC": "311.0",
            # SR 312.0: Criminal Procedure Code
            "CPP": "312.0", "STPO": "312.0", "CRIMPC": "312.0",
            # SR 702: Second Homes Act
            "LRS": "702", "ZWG": "702",
            # SR 741.01: Road Traffic Act
            "LCR": "741.01", "SVG": "741.01", "RTA": "741.01",
            # SR 830.1: Social Insurance General Part Act
            "LPGA": "830.1", "ATSG": "830.1",
            # SR 831.10: Old-Age and Survivors' Insurance Act
            "LAVS": "831.10", "AHVG": "831.10",
        }
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

    # Files & patterns to ignore during crawling/watching
    IGNORE_FILE_PATTERNS: List[str] = Field(
        default_factory=lambda: [
            "~$*", "*.tmp", "*.crdownload", "*.part", "job_history.txt", "thumbs.db", "desktop.ini"
        ]
    )

    # Raw Scanner Ingestion Postponement (awaits manual or automated renaming)
    POSTPONE_RAW_SCANS: bool = True  # Avoid ingesting raw scanner documents until renamed
    RAW_SCAN_PREFIXES: List[str] = Field(
        default_factory=lambda: ["Xerox Scan_", "Xerox_Scan_", "Scan_"]
    )
    RAW_SCAN_POSTPONE_HOURS: float = 96.0  # Hours to wait for rename before fallback ingestion (0 = postpone indefinitely)

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

    # Split Workload LLM & Embedding Routing
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CHAT_BASE_URL: Optional[str] = "http://localhost:11434"  # PC1 Localhost (CPU / Reasoning)
    OLLAMA_EMBED_BASE_URL: Optional[str] = "http://NITRO-AN51755:11434"  # PC2 Remote Node (CUDA GPU RTX 3060)
    OLLAMA_LOCAL_EMBED_BASE_URL: Optional[str] = "http://localhost:11434"  # Tier 2 Local CPU Fallback
    OLLAMA_LOCAL_EMBEDDING_MODEL: str = "snowflake-arctic-embed:latest"
    OLLAMA_LOCAL_EMBED_NUM_CTX: Optional[int] = 512  # Context window for local 512-token models (snowflake-arctic-embed v1)

    # LLM Categorization & Analysis settings
    LLM_PROVIDER: str = "auto"  # 'auto', 'openrouter', 'ollama', or 'heuristic'
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "google/gemini-2.0-flash-001"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_MODEL_PC1: str = "llama3.2:1b"
    OLLAMA_MODEL_SP1: str = "qwen2.5:7b"
    OLLAMA_MODEL_PC2: str = "llama3.2:3b"
    
    # Dense Vector Embeddings & Knowledge Base Sidecar Settings
    EMBEDDING_PROVIDER: str = "auto"  # 'auto', 'ollama', 'openrouter', or 'mock'
    OLLAMA_EMBEDDING_MODEL: str = "snowflake-arctic-embed2:latest"
    OLLAMA_TIMEOUT: float = 300.0  # Timeout in seconds for Ollama model load & embedding (patient for CPU/GPU)
    OLLAMA_KEEP_ALIVE: str = "24h"  # Keep model resident in VRAM/RAM
    OLLAMA_NUM_CTX: int = 2048  # Context length (2048 tokens allows dual 3B chat + embed models in 6GB VRAM)
    OLLAMA_SUB_BATCH_SIZE: int = 16  # Max chunks sent per HTTP batch slice to ensure fast, reliable responses
    CHUNK_SIZE_TOKENS: int = 600
    CHUNK_OVERLAP_TOKENS: int = 80
    VECTOR_STORE_PATH: Path = Field(default=Path("reposcroller_vectors"))
    KB_SIDECAR_BATCH_SIZE: int = 10
    KB_SIDECAR_HTTP_WORKERS: int = 4  # Concurrency matching PC2 Ollama OLLAMA_NUM_PARALLEL (prevents queue overflow)
    ALLOW_PSEUDO_FALLBACK: bool = False  # Strict dense embeddings; prevents degrading to Tier 3 hash pseudo-embeddings

    @property
    def chat_url(self) -> str:
        """Endpoint for conversational reasoning, taxonomy discovery, and chat generation."""
        try:
            from backend.ai.telemetry import workload_telemetry
            return workload_telemetry.get_active_chat_url()
        except Exception:
            return (self.OLLAMA_CHAT_BASE_URL or self.OLLAMA_BASE_URL).rstrip("/")

    @property
    def chat_model(self) -> str:
        """Active model selected dynamically for conversational reasoning and classification."""
        try:
            from backend.ai.telemetry import workload_telemetry
            return workload_telemetry.get_active_chat_model()
        except Exception:
            return self.OLLAMA_MODEL_PC2 or self.OLLAMA_MODEL

    @property
    def embed_url(self) -> str:
        """Endpoint for dense vector embeddings on remote CUDA GPU (Tier 1)."""
        return (self.OLLAMA_EMBED_BASE_URL or self.OLLAMA_BASE_URL).rstrip("/")

    @property
    def local_embed_url(self) -> str:
        """Endpoint for secondary local embedding fallback on PC1 CPU (Tier 2)."""
        return (self.OLLAMA_LOCAL_EMBED_BASE_URL or self.chat_url).rstrip("/")

    # Vector Store Backend Type ('sqlite' or 'qdrant')
    VECTOR_STORE_TYPE: str = "sqlite"  # 'sqlite' or 'qdrant'
    QDRANT_URL: Optional[str] = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION: str = "reposcroller_chunks"
    QDRANT_PREFER_GRPC: bool = False

    # Knowledge Graph & Neo4j Settings (Optional Sidecar Integration)
    GRAPH_STORE_TYPE: str = "sqlite"  # 'sqlite' or 'neo4j'
    GRAPH_EXTRACTOR_MODE: str = "heuristic"  # 'heuristic' (instant regex/taxonomy, 1ms) or 'llm'
    NEO4J_URI: Optional[str] = "bolt://localhost:7687"
    NEO4J_USER: Optional[str] = "neo4j"
    NEO4J_PASSWORD: Optional[str] = "password"


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

    def is_swiss_law_root(self, path: Union[str, Path]) -> bool:
        """Check if a file or storage root resides in known Swiss legal directories."""
        path_str = str(path).lower()
        return any(root.lower() in path_str for root in self.SWISS_LAW_ROOTS)

    def get_sr_code_for_abbrev(self, abbrev: str) -> Optional[str]:
        """Resolve Swiss law abbreviation (e.g. 'CO', 'OR', 'CC', 'ZGB') to SR code."""
        if not abbrev:
            return None
        return self.SWISS_LAW_MAP.get(abbrev.strip().upper())


settings = Settings()
