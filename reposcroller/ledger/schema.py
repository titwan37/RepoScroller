"""Database schema definitions for ALCOA+ document ledger, locations, and version chains."""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- Core Document Ledger (content-addressable unique cryptographic record)
CREATE TABLE IF NOT EXISTS document_ledger (
    sha256_hash TEXT PRIMARY KEY,
    simhash TEXT,
    canonical_filename TEXT,
    doc_type TEXT,
    lifecycle_status TEXT,          -- draft, review, final, truncated, superseded
    completeness_score REAL DEFAULT 0.0,
    maturity_score REAL DEFAULT 0.0,
    page_count INTEGER DEFAULT 0,
    text_snippet TEXT,
    doc_date TEXT,                  -- Substantive date of document (YYYY-MM-DD)
    doc_date_source TEXT,           -- filename, content, mtime
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Physical and Virtual Storage Locations (Multiple copies mapped to 1 SHA-256)
CREATE TABLE IF NOT EXISTS file_locations (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT NOT NULL REFERENCES document_ledger(sha256_hash) ON DELETE CASCADE,
    storage_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    is_primary_source BOOLEAN DEFAULT 0,
    status TEXT DEFAULT 'active',    -- active, missing, offline
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Version Lineage and Evolutionary Relationships
CREATE TABLE IF NOT EXISTS version_chains (
    chain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_sha256 TEXT NOT NULL REFERENCES document_ledger(sha256_hash),
    child_sha256 TEXT NOT NULL REFERENCES document_ledger(sha256_hash),
    relationship TEXT NOT NULL,      -- supersedes, derived_from, near_duplicate, merged_into
    similarity_score REAL DEFAULT 0.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_sha256, child_sha256, relationship)
);

-- ALCOA+ Audit Trail (Attributable, Contemporaneous, Enduring, Tamper-evident)
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT,
    action TEXT NOT NULL,            -- ingest, duplicate_found, supersedes, status_change, scan_verify
    details TEXT,
    actor TEXT DEFAULT 'RepoScroller-Engine',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Global Multilingual Taxonomy (English, French, German) for Dynamic Topic Evolution
CREATE TABLE IF NOT EXISTS global_taxonomy (
    category_id TEXT PRIMARY KEY,        -- canonical slug e.g. "employment_contract"
    parent_id TEXT REFERENCES global_taxonomy(category_id),
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    name_de TEXT NOT NULL,
    description TEXT,
    keywords TEXT,                       -- multilingual keywords JSON/CSV
    document_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices for rapid duplicate lookup & lineage navigation
CREATE INDEX IF NOT EXISTS idx_taxonomy_parent ON global_taxonomy(parent_id);
CREATE INDEX IF NOT EXISTS idx_ledger_simhash ON document_ledger(simhash);
CREATE INDEX IF NOT EXISTS idx_locations_sha256 ON file_locations(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_locations_abs_path ON file_locations(absolute_path);
CREATE INDEX IF NOT EXISTS idx_locations_root ON file_locations(storage_root);
CREATE INDEX IF NOT EXISTS idx_version_parent ON version_chains(parent_sha256);
CREATE INDEX IF NOT EXISTS idx_version_child ON version_chains(child_sha256);
CREATE INDEX IF NOT EXISTS idx_audit_sha256 ON audit_log(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_ledger_doc_date ON document_ledger(doc_date);

-- Lexical Keyword Search Table (SQLite FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
    sha256_hash UNINDEXED,
    canonical_filename,
    text_content
);
"""
