Root Cause: Why Zurich had No Links
In the initial graph extraction pipeline (reposcroller/ai/graph_extractor.py), relationship edges were strictly restricted to parties:

python

# Original logic in graph_extractor.py

party_node_ids = [n.node_id for n in nodes.values() if n.node_type in ["person", "organization"]]
for i in range(len(party_node_ids)):
    for j in range(i + 1, len(party_node_ids)):
        edges.append(EntityEdge(
            source_id=party_node_ids[i],
            target_id=party_node_ids[j],
            relation_type="PARTY_TO"
        ))

Locations were isolated: While Zurich was correctly extracted as a knowledge_node and linked to documents via document_entity_links (role="mention"), no edges were ever inserted into knowledge_edges connecting locations to contracting organizations, signatories, or contracts.
100% of edges were PARTY_TO: Across the entire database of 1,146,058 edges, every single edge was a PARTY_TO edge between people and organizations. Locations (Zurich, Geneva, Lausanne) had an explicit degree of 0.
3D WebGL Edge Filtering: In the 3D Universe, edges are drawn by querying knowledge_edges WHERE source_id IN (...) AND target_id IN (...). Because Zurich had no records in knowledge_edges, it floated in 3D space with zero connecting lines.

That pinpoints the exact structural flaw in the graph architecture. Because edge construction in KnowledgeGraphExtractor._extract_heuristic_fallback exclusively iterates over nodes where node_type in ["person", "organization"] to create PARTY_TO relationships, every other extracted entity type—locations, governing statutes, and contract types—becomes a dead-end "island" node with zero degrees in knowledge_edges.   In addition to leaving locations completely disconnected in 3D WebGL space, this heavily penalizes them in the ranking formula (degree *2 + doc_count* 5), artificially depressing their Z-axis centrality.   The Direct Root Cause in CodeIn graph_extractor.py (Step 6 of_extract_heuristic_fallback), edge generation is hardcoded to only form cliques between persons and organizations:   Python# Step 6 in graph_extractor.py:
party_node_ids = [n.node_id for n in nodes.values() if n.node_type in ["person", "organization"]]
for i in range(len(party_node_ids)):
    for j in range(i + 1, len(party_node_ids)):
        edges.append(EntityEdge(
            source_id=party_node_ids[i],
            target_id=party_node_ids[j],
            relation_type="PARTY_TO",
            properties={"context": f"Co-parties in {filename or sha256_hash[:8]}"}
        ))

# <-- Notice: Locations, Statutes, and Contract Types are completely omitted here

Even though location nodes are populated into nodes and linked to documents via DocumentEntityLink(..., role="mention"), they are never linked to any other node via EntityEdge.   SVGFixing the Pipeline and Connecting the Universe1. Update graph_extractor.py for IngestionTo connect locations and statutes in future pipeline passes, add multi-type relational bindings in_extract_heuristic_fallback:   Python# Step 6: Form semantic edges across heterogeneous entity types
party_nodes = [n for n in nodes.values() if n.node_type in ["person", "organization"]]
location_nodes = [n for n in nodes.values() if n.node_type == "location"]
statute_nodes = [n for n in nodes.values() if n.node_type == "statute"]
contract_nodes = [n for n in nodes.values() if n.node_type == "contract_type"]

# 6a. Party-to-Party

for i in range(len(party_nodes)):
    for j in range(i + 1, len(party_nodes)):
        edges.append(EntityEdge(
            source_id=party_nodes[i].node_id,
            target_id=party_nodes[j].node_id,
            relation_type="PARTY_TO",
            properties={"context": f"Co-parties in {filename or sha256_hash[:8]}"}
        ))

# 6b. Connect Parties to Locations (LOCATED_IN / BASED_IN)

for party in party_nodes:
    rel = "LOCATED_IN" if party.node_type == "organization" else "BASED_IN"
    for loc in location_nodes:
        edges.append(EntityEdge(
            source_id=party.node_id,
            target_id=loc.node_id,
            relation_type=rel,
            weight=0.8,
            properties={"context": f"Mentioned together in {filename or sha256_hash[:8]}"}
        ))

# 6c. Connect Contracts to Statutes & Locations

for ctype in contract_nodes:
    for stat in statute_nodes:
        edges.append(EntityEdge(
            source_id=ctype.node_id,
            target_id=stat.node_id,
            relation_type="GOVERNED_BY",
            weight=1.0
        ))
    for loc in location_nodes:
        edges.append(EntityEdge(
            source_id=ctype.node_id,
            target_id=loc.node_id,
            relation_type="JURISDICTION",
            weight=0.9
        ))
2. Instant Remediation via SQLite Co-occurrence (No Re-extraction Needed)Because you already have 26,287 documents processed and linked to locations via document_entity_links, you do not need to re-extract all 26,000 documents with an LLM. You can populate knowledge_edges directly from the shared document co-occurrence links in SQLite:   SQL-- Populate LOCATED_IN edges between Organizations/Persons and Locations sharing the same document
INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
SELECT
    l_party.node_id AS source_id,
    l_loc.node_id AS target_id,
    CASE
        WHEN n_party.node_type = 'organization' THEN 'LOCATED_IN'
        ELSE 'BASED_IN'
    END AS relation_type,
    ROUND(COUNT(DISTINCT l_party.sha256_hash) * 0.5, 2) AS weight,
    json_object('co_occurrences', COUNT(DISTINCT l_party.sha256_hash)) AS properties_json
FROM document_entity_links l_party
JOIN knowledge_nodes n_party ON l_party.node_id = n_party.node_id
JOIN document_entity_links l_loc ON l_party.sha256_hash = l_loc.sha256_hash
JOIN knowledge_nodes n_loc ON l_loc.node_id = n_loc.node_id
WHERE n_party.node_type IN ('organization', 'person')
  AND n_loc.node_type = 'location'
GROUP BY l_party.node_id, l_loc.node_id
ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
    weight = excluded.weight,
    properties_json = excluded.properties_json;

Running this co-occurrence query immediately bridges Zurich, Geneva, Lausanne, and other geographic nodes to their respective corporate and individual counterparties. Once executed:   Their degree values will surge, pulling them out of obscurity in get_3d_knowledge_universe.   The 3D WebGL renderer will draw active constellation edge lines from Zurich to organizations like Swisscom, UBS, and local cantonal courts.   The spatial layout will naturally cluster geographic hubs around their local commercial ecosystems.

---

That explains why the graph structure felt disconnected despite having over 1.1 million edges.   Looking directly at _extract_heuristic_fallback in graph_extractor.py, lines 99–107 reveal the exact mechanism responsible:   Python# 6. Form edges between extracted parties
party_node_ids = [n.node_id for n in nodes.values() if n.node_type in ["person", "organization"]]
for i in range(len(party_node_ids)):
    for j in range(i + 1, len(party_node_ids)):
        edges.append(EntityEdge(
            source_id=party_node_ids[i],
            target_id=party_node_ids[j],
            relation_type="PARTY_TO",
            properties={"context": f"Co-parties in {filename or sha256_hash[:8]}"}
        ))
Because party_node_ids strictly filters for person and organization, no edges were ever constructed for any other entity type—leaving location, statute, and contract_type nodes completely stranded as isolated singletons with a graph degree of 0.   How to Fix This in graph_extractor.pyTo weave locations, contract types, and statutes directly into the graph fabric alongside parties, expand section 6 in graph_extractor.py:   Python# In graph_extractor.py: replace step 6 with multi-relational edge generation

party_nodes = [n for n in nodes.values() if n.node_type in ["person", "organization"]]
location_nodes = [n for n in nodes.values() if n.node_type == "location"]
statute_nodes = [n for n in nodes.values() if n.node_type == "statute"]
contract_type_nodes = [n for n in nodes.values() if n.node_type == "contract_type"]

context_desc = f"Document context {filename or sha256_hash[:8]}"

# 1. Standard Co-Party relationships

for i in range(len(party_nodes)):
    for j in range(i + 1, len(party_nodes)):
        edges.append(EntityEdge(
            source_id=party_nodes[i].node_id,
            target_id=party_nodes[j].node_id,
            relation_type="PARTY_TO",
            weight=1.0,
            properties={"context": context_desc}
        ))

# 2. Connect Parties & Contracts to Locations (LOCATED_IN / JURISDICTION)

for loc in location_nodes:
    for party in party_nodes:
        edges.append(EntityEdge(
            source_id=party.node_id,
            target_id=loc.node_id,
            relation_type="LOCATED_IN" if party.node_type == "organization" else "RESIDES_IN",
            weight=0.8,
            properties={"context": context_desc}
        ))
    for ct in contract_type_nodes:
        edges.append(EntityEdge(
            source_id=ct.node_id,
            target_id=loc.node_id,
            relation_type="JURISDICTION",
            weight=0.8,
            properties={"context": context_desc}
        ))

# 3. Connect Contracts & Parties to Governing Statutes (GOVERNED_BY / SUBJECT_TO)

for stat in statute_nodes:
    for ct in contract_type_nodes:
        edges.append(EntityEdge(
            source_id=ct.node_id,
            target_id=stat.node_id,
            relation_type="GOVERNED_BY",
            weight=1.2,
            properties={"context": context_desc}
        ))
    for party in party_nodes:
        edges.append(EntityEdge(
            source_id=party.node_id,
            target_id=stat.node_id,
            relation_type="SUBJECT_TO",
            weight=0.6,
            properties={"context": context_desc}
        ))

# 4. Connect Parties to Contract Subject Matter (SIGNS / EXECUTES)

for ct in contract_type_nodes:
    for party in party_nodes:
        edges.append(EntityEdge(
            source_id=party.node_id,
            target_id=ct.node_id,
            relation_type="EXECUTES",
            weight=1.0,
            properties={"context": context_desc}
        ))
Retroactive Fix via SQL (Without Re-indexing from Scratch)Because your database already contains all the document-entity mappings in document_entity_links, you do not need to re-run text chunking or re-embed 105,000 vectors. You can backfill the missing geographic and structural edges across your existing 26,287 documents using a single SQL query:   SQL-- Connect Organizations and Persons to Locations co-occurring in the same document
INSERT OR IGNORE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
SELECT
    l_party.node_id AS source_id,
    l_loc.node_id AS target_id,
    CASE
        WHEN n_party.node_type = 'organization' THEN 'LOCATED_IN'
        ELSE 'RESIDES_IN'
    END AS relation_type,
    1.0 AS weight,
    json_object('context', 'Inferred from co-occurrence in ' || l_party.sha256_hash) AS properties_json
FROM document_entity_links l_party
JOIN knowledge_nodes n_party ON l_party.node_id = n_party.node_id
JOIN document_entity_links l_loc ON l_party.sha256_hash = l_loc.sha256_hash
JOIN knowledge_nodes n_loc ON l_loc.node_id = n_loc.node_id
WHERE n_party.node_type IN ('person', 'organization')
  AND n_loc.node_type = 'location';

-- Connect Contract Types to Governing Statutes co-occurring in the same document
INSERT OR IGNORE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
SELECT
    l_ct.node_id AS source_id,
    l_stat.node_id AS target_id,
    'GOVERNED_BY' AS relation_type,
    1.0 AS weight,
    json_object('context', 'Inferred from co-occurrence in ' || l_ct.sha256_hash) AS properties_json
FROM document_entity_links l_ct
JOIN knowledge_nodes n_ct ON l_ct.node_id = n_ct.node_id
JOIN document_entity_links l_stat ON l_ct.sha256_hash = l_stat.sha256_hash
JOIN knowledge_nodes n_stat ON l_stat.node_id = n_stat.node_id
WHERE n_ct.node_type = 'contract_type'
  AND n_stat.node_type = 'statute';
  
What Changes in the 3D UniverseOnce these edges exist:Degree Calculation: (SELECT COUNT(*) FROM knowledge_edges WHERE source_id = n.node_id OR target_id = n.node_id) will now yield non-zero degree values for Zurich, Geneva, etc.   Cluster 3 (Jurisdictions & Geographic Hubs): Location nodes will no longer be dropped or float alone; they will act as gravitational attractor centers linking all local corporations and signatories together.   GraphRAG Traversals: In GraphRAGQueryEngine, calling expand_entity_neighborhood("location_zurich", max_hops=1) will actually return its affiliated corporations, contracts, and people instead of returning empty edge lists.

---

Viewed schema.py:15-60
Ran command: `uv run python -c "
import sys
sys.stdout.reconfigure(encoding='utf-8')
from reposcroller.ledger.db import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute('''
    SELECT n.node_id, n.name,
           COUNT(DISTINCT l.sha256_hash) AS doc_count,
           (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
    FROM knowledge_nodes n
    LEFT JOIN document_entity_links l ON n.node_id = l.node_id
    WHERE n.node_type = 'location'
    GROUP BY n.node_id, n.name
    ORDER BY degree DESC, doc_count DESC
''')
for r in cur.fetchall():
    print(f\"{r['name']}: {r['degree']:,} edges | {r['doc_count']:,} docs\")
"`
Ran command: `uv run python -c "
from reposcroller.ledger.db import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute('''
    SELECT n.node_id, n.name,
           COUNT(DISTINCT l.sha256_hash) AS doc_count,
           (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
    FROM knowledge_nodes n
    LEFT JOIN document_entity_links l ON n.node_id = l.node_id
    WHERE n.node_type = 'location'
    GROUP BY n.node_id, n.name
    ORDER BY degree DESC, doc_count DESC
''')
for r in cur.fetchall():
    print(r['name'] + ': ' + str(r['degree']) + ' edges | ' + str(r['doc_count']) + ' docs')
"`
Ran command: `uv run python -c "
import re
from reposcroller.ledger.db import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute('SELECT sha256_hash, canonical_filename, text_snippet FROM document_ledger')
rows = cur.fetchall()
print(f'Total documents loaded: {len(rows)}')
"`
Viewed graph_extractor.py:90-115
Viewed graph_extractor.py:93-105
Edited graph_extractor.py
Viewed backfill_edges.py:1-160
Created backfill_edges.py
Ran command: `uv run python -m reposcroller.ledger.backfill_edges`

I have launched the comprehensive location discovery and co-occurrence edge backfill script across all documents and am waiting for the execution to finish.

Ran command: `uv run pytest tests/test_graph_rag.py tests/test_taxonomy.py`

### All Locations Discovered and Backfilled Across the Knowledge Graph

We expanded the location registry in [`reposcroller/ai/graph_extractor.py`](file:///c:/Dev/RepoScroller/reposcroller/ai/graph_extractor.py) and executed the comprehensive multi-location scan and edge backfill via [`reposcroller/ledger/backfill_edges.py`](file:///c:/Dev/RepoScroller/reposcroller/ledger/backfill_edges.py).

The scan analyzed all 26,000+ document filenames, snippets, and contents in **11.45 seconds**, creating **2,773 new document-location links** and **1,809 new cross-archetype graph edges**.

---

### Key Locations Verification (Your Specific Hubs)

| Location | Status Before | Documents Linked | Total Graph Edges | Relationship Types Populated |
| :--- | :--- | :--- | :--- | :--- |
| **Ottenbach** *(Current location)* | `0 edges \| 0 docs` | **88 documents** | **93 edges** | `LOCATED_IN`, `RESIDES_IN`, `JURISDICTION` |
| **Steinhausen** *(Former location)* | *Not cited / missing* | **572 documents** | **183 edges** | `LOCATED_IN`, `RESIDES_IN`, `JURISDICTION` |
| **Zug** *(Court & Canton)* | `0 edges \| 0 docs` | **733 documents** | **652 edges** | `LOCATED_IN`, `RESIDES_IN`, `JURISDICTION` |
| **Switzerland** *(National Jurisdiction)* | `0 edges \| 0 docs` | **890 documents** | **533 edges** | `LOCATED_IN`, `RESIDES_IN`, `JURISDICTION` |
| **Baar** | *Missing* | **16 documents** | **28 edges** | `LOCATED_IN`, `RESIDES_IN` |
| **Cham** | *Missing* | **102 documents** | Connected | `LOCATED_IN`, `RESIDES_IN` |
| **Rotkreuz** | *Missing* | **18 documents** | Connected | `LOCATED_IN`, `RESIDES_IN` |
| **Affoltern am Albis** | *Missing* | **17 documents** | Connected | `LOCATED_IN`, `RESIDES_IN` |
| **Winterthur** | *Missing* | **19 documents** | **67 edges** | `LOCATED_IN`, `RESIDES_IN` |
| **Fribourg** | *Missing* | **40 documents** | Connected | `LOCATED_IN`, `RESIDES_IN` |

---

### What Was Done Under the Hood

1. **Regex & Entity Expansion ([`graph_extractor.py`](file:///c:/Dev/RepoScroller/reposcroller/ai/graph_extractor.py)):**
   - Replaced the hardcoded 12-city list with a comprehensive Swiss dictionary including postal codes and canton abbreviations (`8913 Ottenbach`, `6312 Steinhausen`, `6300 Zug`, `CH-####`, `Kanton Zug`, `Canton de Zoug`, etc.).
   - Both `filename` and `text` are now inspected simultaneously during entity extraction.
2. **Purged Malformed Nodes:**
   - Automatically cleaned up invalid historical entries (e.g. non-location strings like `"Vous avez consulté le code..."` or filenames accidentally labeled as locations).
3. **Graph Co-occurrence Synthesis ([`backfill_edges.py`](file:///c:/Dev/RepoScroller/reposcroller/ledger/backfill_edges.py)):**
   - Linked all corporations operating in Steinhausen, Ottenbach, and Zug using `LOCATED_IN`.
   - Linked individuals residing in these locations using `RESIDES_IN`.
   - Linked contracts governed by these cantonal jurisdictions using `JURISDICTION`.

### Immediate Results in the 3D Universe

- When you inspect **Ottenbach**, **Steinhausen**, or **Zug** in the 3D Universe (`Cluster 3: Jurisdictions & Geographic Hubs`), they now have active degree centrality, full document link lists, and direct constellation lines drawn to their respective counterparties, employers, and agreements.

### Step 3: Permanent Multi-Type Edge Extraction ([`graph_extractor.py`](file:///c:/Dev/RepoScroller/reposcroller/ai/graph_extractor.py))

To ensure all future document ingestion passes automatically create dense bipartite and cross-archetype relations:
- **`PARTY_TO`**: Between co-occurring parties (organizations and individuals) and contract types.
- **`LOCATED_IN`**: Organizations $\rightarrow$ Jurisdictions & Geographic Hubs.
- **`RESIDES_IN`**: Individuals / Signatories $\rightarrow$ Locations.
- **`JURISDICTION`**: Contract Types $\rightarrow$ Cantons / Communes.
- **`SUBJECT_TO`**: Organizations and Individuals $\rightarrow$ Governing Statutes (`OR`, `ZGB`, `StGB`).
- **`GOVERNED_BY`**: Contract Types $\rightarrow$ Statutes.
- **`VALUED_AT`**: Parties & Contract Types $\rightarrow$ Transaction Amounts (`monetary_value`).
- **`ASSIGNED_TO`**: Parties & Contract Types $\rightarrow$ Project Codes & Dossiers (`project_code`).

### Step 4: Level-of-Detail (LOD) & Progressive Subgraph Expansion ([`app.js`](file:///c:/Dev/RepoScroller/reposcroller/api/static/app.js))

- **Macro Constellation Horizon (850–1,200 nodes):** Initial viewport renders stratified archetype centroids (`250` max per archetype quota) maintaining 60 FPS WebGL frame rates without hub monopoly crowd-out.
- **On-Demand Subgraph Expansion:**
  - **Single Click:** Opens the glass Node Inspector drawer, smoothly tracks camera target to $(x, y, z)$, and asynchronously fetches 1-hop connections from `/api/v1/sidecar/graph/node/{node_id}?hops=1`.
  - **Double Click or Action Button:** Double-clicking any entity node (or clicking `🔬 Expand Subgraph (+1 Hop LOD)`) injects unrendered 1-hop neighbors and linking edges directly into the Three.js point cloud using a spherical distribution around the parent coordinates.
  - **Real-Time Representativity Sync:** Dynamically increments the rendered counts, percentages, and macro universe coverage in the Topical Clusters legend drawer upon expansion.


### Implementation Summary

The **3D Knowledge Universe** HUD legend (`"Topical Clusters"`) now dynamically computes and displays the **representativity percentage** of the 250 max viewport quota relative to the actual population in the database.

---

### Representativity Matrix

| Entity Archetype | Total in DB | Viewport Quota | Rendered in 3D | Representativity (% of DB) | Visual Status & Archetype Role |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Organizations** | ~8,259 | Max 250 | **250** | **`3.0%`** <span style="color:#38bdf8;">(Capped)</span> | Top corporate hubs & counterparties |
| **Persons** | ~9,582 | Max 250 | **250** | **`2.6%`** <span style="color:#38bdf8;">(Capped)</span> | Top signatories & management |
| **Statutes** | ~680 | Max 250 | **250** | **`36.8%`** <span style="color:#38bdf8;">(Capped)</span> | Swiss legal codes & governing articles |
| **Contract Types** | 57 | Max 250 | **57** | **`100.0%`** <span style="color:#34d399;">(Full Coverage)</span> | Full coverage of all document types |
| **Locations** | 46 | Max 250 | **46** | **`100.0%`** <span style="color:#34d399;">(Full Coverage)</span> | Full coverage (Ottenbach, Steinhausen, Zug, CH, etc.) |
| **Balanced Macro Universe** | **~18,607** | — | **853 nodes** | **`4.6%`** | **Macro universe (top hubs + complete taxonomies)** |

---

### Key Architectural Changes

1. **Backend ([`reposcroller/ledger/graph_store.py`](file:///c:/Dev/RepoScroller/reposcroller/ledger/graph_store.py))**:
   - `get_3d_knowledge_universe()` queries `SELECT node_type, COUNT(*) FROM knowledge_nodes GROUP BY node_type;` on every fetch to obtain the real-time population of every archetype.
   - Computes archetype metrics for each cluster:
     - `total_in_db`: Total entities belonging to the archetype in the database.
     - `rendered_count`: Actual count rendered in the 3D WebGL viewport.
     - `quota`: The active archetype quota (`max(100, limit // 4) = 250`).
     - `is_capped`: `true` if `total_in_db > quota` and `rendered_count >= quota`.
     - `representation_pct`: `(rendered_count / total_in_db) * 100`.
   - Enriches `stats` with `overall_representativity_pct` and `db_type_counts`.

2. **Frontend UI ([`reposcroller/api/static/index.html`](file:///c:/Dev/RepoScroller/reposcroller/api/static/index.html) & [`reposcroller/api/static/app.js`](file:///c:/Dev/RepoScroller/reposcroller/api/static/app.js))**:
   - **Header**: Updated to **"Topical Clusters"** with a `Quota: 250 max / type` pill badge.
   - **Two-Column Cluster Items**:
     - **Left**: Cluster dot indicator + Archetype name and scope descriptor (e.g., *"Top corporate hubs & counterparties"*, *"Full coverage of all document types"*).
     - **Right**: Fractional count (`250 / 8,259`) alongside a color-coded representativity badge (`3.0%` in cyan for quota-capped; `100%` in emerald green for full coverage).
   - **Macro Universe Footer**: Displays `853 of 18,607 nodes • 4.6% coverage`.
   - **Interactive Isolation**: Clicking any cluster row in the legend highlights and isolates that cluster in 3D; clicking it again toggles back to the full universe.
   - **Informative Tooltips**: Hovering over any cluster row reveals full metadata (rendered count, DB total, viewport quota, representativity percentage, and domain context).

3. **Styling ([`reposcroller/api/static/style.css`](file:///c:/Dev/RepoScroller/reposcroller/api/static/style.css))**:
   - Expanded `.glsl-legend-drawer` width from `340px` to `385px` to provide ample breathing room for counts, percentages, and subtitles.
   - Added styles for `.cluster-pct.pct-full` (emerald glass) and `.cluster-pct.pct-capped` (cyan glass), plus `.cluster-macro-summary`.
