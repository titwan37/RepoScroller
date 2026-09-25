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

-- Knowledge Base Processing Queue (Asynchronous CDC Sidecar)
CREATE TABLE IF NOT EXISTS kb_processing_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT NOT NULL REFERENCES document_ledger(sha256_hash) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending',          -- pending, processing, completed, failed
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    enqueued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    UNIQUE(sha256_hash)
);

-- Document Vector Chunks (Dense semantic passages)
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,               -- e.g. "{sha256}_{chunk_index}"
    sha256_hash TEXT NOT NULL REFERENCES document_ledger(sha256_hash) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    embedding_json TEXT,                     -- JSON array of floats (e.g. from snowflake-arctic-embed)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_queue_status ON kb_processing_queue(status);
CREATE INDEX IF NOT EXISTS idx_chunks_sha256 ON document_chunks(sha256_hash);

-- Knowledge Graph Entity Nodes (e.g. Person, Organization, Location, Statute, ContractType)
CREATE TABLE IF NOT EXISTS knowledge_nodes (
    node_id TEXT PRIMARY KEY,               -- canonical slug e.g. "org_ubs_ag", "person_alice_smith"
    node_type TEXT NOT NULL,                -- person, organization, location, statute, contract_type, date_event
    name TEXT NOT NULL,                     -- canonical display name
    properties_json TEXT,                   -- JSON object with aliases, descriptions, metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge Graph Directed Edges / Relationships (e.g. SIGNS, PARTY_TO, GOVERNED_BY, SUPERSEDES)
CREATE TABLE IF NOT EXISTS knowledge_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,            -- SIGNS, PARTY_TO, GOVERNED_BY, SUPERSEDES, AMENDS, REFERENCES
    weight REAL DEFAULT 1.0,
    properties_json TEXT,                   -- JSON metadata (e.g. signed_date, context_snippet)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, target_id, relation_type)
);

-- Document to Knowledge Graph Entity Association Links
CREATE TABLE IF NOT EXISTS document_entity_links (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT NOT NULL REFERENCES document_ledger(sha256_hash) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE CASCADE,
    role TEXT NOT NULL,                     -- signatory, counterparty, subject_matter, governing_law, mention
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sha256_hash, node_id, role)
);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON knowledge_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON knowledge_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON knowledge_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_doc_entity_sha ON document_entity_links(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_doc_entity_node ON document_entity_links(node_id);
"""


