import sys
import io
from pathlib import Path

# Fix Windows console charmap encoding for emojis
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path so 'backend' is importable when script is run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3
import json
from collections import defaultdict
import httpx
from backend.config import settings

def extract_folder_topology(db_path = None) -> dict:
    """Extracts a weighted directory tree from the existing SQLite WAL ledger."""
    db_path = Path(db_path) if db_path else Path(settings.DB_PATH)
    print(f"📂 Extracting topology from {db_path}...")
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Fetch all relative paths and filenames
    cur.execute("""
        SELECT fl.relative_path, dl.canonical_filename 
        FROM file_locations fl
        JOIN document_ledger dl ON fl.sha256_hash = dl.sha256_hash
    """)
    
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("⚠️ No data found. Ensure the crawler has run at least once.")
        return {}

    # Build a 2-level deep folder weight map
    topology = defaultdict(int)
    for rel_path, filename in rows:
        path_parts = Path(rel_path).parts
        if len(path_parts) > 1:
            # Capture the top two folder levels (e.g., "Finance/Taxes")
            macro_folder = "/".join(path_parts[:2])
            topology[macro_folder] += 1
            
    # Sort by highest document count to prioritize actual data gravity
    sorted_topology = dict(sorted(topology.items(), key=lambda item: item[1], reverse=True))
    print(f"✅ Extracted {len(sorted_topology)} distinct folder structures.")
    
    return sorted_topology

def generate_macro_themes(topology: dict):
    """Feeds the folder topology to the local LLM to deduce enriched Macro Domains."""
    print(f"🧠 Synthesizing Macro Domains via {settings.OLLAMA_MODEL_SP1}...")

    topology_str = "\n".join([f"- {folder} ({count} documents)" for folder, count in list(topology.items())[:100]])

    prompt = f"""You are a Chief Information Architect. 
Analyze the following physical folder topology and document counts from a digital repository.
Deduce exactly 10 to 15 "Macro Life Domains" (Themes) that logically group these folders.

Requirements:
1. Assign a short machine-readable slug starting with 'theme_' (e.g., "theme_real_estate").
2. Generate a multilingual array of 5-8 ACTUAL relevant search keywords for each theme. DO NOT use placeholders.
3. Aggregate the document counts of the constituent folders into a total "weight" integer.
4. Write a REAL, specific 1-sentence description for each domain. DO NOT copy the template text.
5. Output STRICTLY in JSON format.

Folder Topology:
{topology_str}

Output JSON format:
{{
  "macro_themes": [
    {{
      "slug": "theme_name",
      "name_en": "English Name",
      "name_fr": "French Name",
      "name_de": "German Name",
      "description": "<Write the real generated description here>",
      "keywords": ["<real_keyword_1>", "<real_keyword_2>", "<real_keyword_3>"],
      "weight": 150
    }}
  ]
}}
"""

    try:
        response = httpx.post(
            f"{settings.OLLAMA_CHAT_BASE_URL}/api/chat",
            json={
                "model": settings.OLLAMA_MODEL_PC1,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.3}
            },
            timeout=240.0
        )
        response.raise_for_status()
        
        result_json = response.json()["message"]["content"]
        themes = json.loads(result_json.strip().removeprefix("```json").removesuffix("```").strip())
        
        output_file = Path(settings.DB_PATH).parent / "foundational_themes.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(themes, f, indent=2, ensure_ascii=False)
            
        print(f"🎉 Successfully generated {len(themes.get('macro_themes', []))} Enriched Macro Themes!")
        print(f"💾 Saved to {output_file}. Please review and adjust the file before ingesting.")
        
    except Exception as e:
        print(f"❌ Failed to generate themes: {e}")

if __name__ == "__main__":
    db_topology = extract_folder_topology(settings.DB_PATH)
    if db_topology:
        generate_macro_themes(db_topology)