Searched for "candidates"
Viewed authors.py:260-350
Viewed authors.py:590-680
Ran command: `python -c "
with open('frontend/app.js', 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if 'Prevalidate' in line or 'prevalidate' in line.lower() or 'review threshold' in line.lower():
            print(f'{i}: {line.strip()[:120]}')
"`
Viewed app.js:1950-2050
Ran command: `python -c "
import sqlite3
from backend.config import settings

conn = sqlite3.connect(settings.DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check total entity links with person
cur.execute('''
    SELECT COUNT(*) FROM document_entity_links l
    JOIN knowledge_nodes n ON n.node_id = l.node_id
    WHERE n.node_type = 'person'
''')
print('Total person entity links:', cur.fetchone()[0])

# Check distinct person nodes
cur.execute('''
    SELECT COUNT(DISTINCT l.node_id) FROM document_entity_links l
    JOIN knowledge_nodes n ON n.node_id = l.node_id
    WHERE n.node_type = 'person'
''')
print('Distinct person nodes in links:', cur.fetchone()[0])

# Check author_candidate_evaluations count & statuses
try:
    cur.execute('SELECT status, COUNT(*), AVG(confidence) FROM author_candidate_evaluations GROUP BY status')
    rows = cur.fetchall()
    print('author_candidate_evaluations:', [dict(r) for r in rows])
except Exception as e:
    print('Error reading author_candidate_evaluations:', e)

# Check author_candidate_reviews count
try:
    cur.execute('SELECT status, COUNT(*) FROM author_candidate_reviews GROUP BY status')
    rows = cur.fetchall()
    print('author_candidate_reviews:', [dict(r) for r in rows])
except Exception as e:
    print('Error reading author_candidate_reviews:', e)

conn.close()
"`
Viewed authors.py:220-270
Ran command: `dir /s /b *.db`
Ran command: `Get-ChildItem -Recurse -Filter "*.db" | Select-Object FullName`
Viewed config.py:1-60
Ran command: `python -c "
import sqlite3

for p in [r'C:\Dev\RepoScroller\reposcroller_ledger.db', r'C:\Dev\RepoScroller\backend\data\reposcroller_ledger.db']:
    try:
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
        tables = [t[0] for t in cur.fetchall()]
        print(p, 'tables:', tables)
        if 'document_entity_links' in tables:
            cur.execute('SELECT COUNT(*) FROM document_entity_links')
            print('  links count:', cur.fetchone()[0])
        conn.close()
    except Exception as e:
        print(p, 'error:', e)
"`
Ran command: `python -c "
import sqlite3

for p in [r'C:\Dev\RepoScroller\reposcroller_ledger.db', r'C:\Dev\RepoScroller\backend\data\reposcroller_ledger.db']:
    try:
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\'')
        tables = [t[0] for t in cur.fetchall()]
        print(p, 'tables count:', len(tables))
        if 'document_entity_links' in tables:
            cur.execute('SELECT COUNT(*) FROM document_entity_links')
            print('  document_entity_links count:', cur.fetchone()[0])
        conn.close()
    except Exception as e:
        print(p, 'error:', e)
"`
Viewed .env:1-50
Viewed start_backend.bat:1-24
Ran command: `python -c "
import sqlite3

p = r'C:\Dev\RepoScroller\scripts\reposcroller_ledger.db'
conn = sqlite3.connect(p)
cur = conn.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\'')
tables = [t[0] for t in cur.fetchall()]
print(p, 'tables:', len(tables))
if 'document_entity_links' in tables:
    cur.execute('SELECT COUNT(*) FROM document_entity_links')
    print('document_entity_links count:', cur.fetchone()[0])
if 'author_candidate_evaluations' in tables:
    cur.execute('SELECT COUNT(*) FROM author_candidate_evaluations')
    print('evaluations count:', cur.fetchone()[0])
conn.close()
"`
Ran command: `python -c "
import sqlite3

p = r'C:\Dev\RepoScroller\backend\data\reposcroller_ledger.db'
conn = sqlite3.connect(p)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('SELECT COUNT(*) FROM document_entity_links l JOIN knowledge_nodes n ON n.node_id = l.node_id WHERE n.node_type = \'person\'')
print('Person links:', cur.fetchone()[0])

cur.execute('SELECT COUNT(DISTINCT l.node_id) FROM document_entity_links l JOIN knowledge_nodes n ON n.node_id = l.node_id WHERE n.node_type = \'person\'')
print('Distinct persons:', cur.fetchone()[0])

cur.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'author%'\")
print('Author tables:', [r[0] for r in cur.fetchall()])

try:
    cur.execute('SELECT status, COUNT(*) FROM author_candidate_evaluations GROUP BY status')
    print('author_candidate_evaluations:', [dict(r) for r in cur.fetchall()])
except Exception as e:
    print('author_candidate_evaluations error:', e)

try:
    cur.execute('SELECT status, COUNT(*) FROM author_candidate_reviews GROUP BY status')
    print('author_candidate_reviews:', [dict(r) for r in cur.fetchall()])
except Exception as e:
    print('author_candidate_reviews error:', e)

conn.close()
"`
Viewed config.py:20-35
Viewed config.py:60-120
Viewed authors.py:340-450
Viewed authors.py:50-95
Viewed authors.py:20-50
Edited config.py
Edited .env
Viewed app.js:1980-2045
Edited app.js
Ran command: `node --check frontend/app.js`

Voici l'explication technique exacte de la différence entre les **17 candidats du graphe** et les **0 candidats de la file d'attente (Review Queue)** :

---

### 1. Pourquoi le graphe affiche 17 candidats alors que la file en affiche 0 ?

Le graphe et la file d'attente représentent **deux étapes distinctes de l'entonnoir (funnel)** :

| Vue | Source de données | Condition d'affichage | Ce que vous voyez |
| :--- | :--- | :--- | :--- |
| **Graphe 3D / Réseau** (`/api/v1/authors/graph`) | `document_entity_links` + `knowledge_nodes` | Tout nœud `person` lié à un document où `role != 'author'` sans décision humaine préalable. | **17 candidats bruts** (17 personnes physiques détectées dans les documents indexés). |
| **Queue de décision** (`/api/v1/authors/candidates`) | `author_candidate_evaluations` | **Uniquement** les candidats ayant passé la prévalidation avec :<br>• `status = 'qualified'`<br>• `confidence >= 0.90` (≥90%)<br>• `evidence_verified = 1` (citation textuelle exacte) | **0 candidat qualifié** |

Dans le code de [backend/api/routes/authors.py](file:///c:/Dev/RepoScroller/backend/api/routes/authors.py#L282-L310) :
```sql
SELECT ...
FROM document_entity_links l
JOIN knowledge_nodes n ON n.node_id = l.node_id
JOIN author_candidate_evaluations e 
    ON e.sha256_hash = l.sha256_hash AND e.node_id = l.node_id
WHERE n.node_type = 'person'
  AND l.role != 'author'
  AND e.status = 'qualified'       -- <--- Requis
  AND e.confidence >= 0.90         -- <--- Requis (90%)
  AND e.evidence_verified = 1      -- <--- Citation exacte vérifiée
```

---

### 2. Pourquoi le bouton « Prevalidate » donne 0 qualifié ?

Lorsque vous cliquez sur **🧠 Prevalidate next 10**, le backend exécute un filtre déterministe en amont du LLM pour éviter d'invoquer le modèle pour des personnes qui ne sont manifestement pas des auteurs :

```python
AUTHOR_CUE_RE = re.compile(
    r"\b(?:author(?:s)?|authored\s+by|written\s+by|prepared\s+by|"
    r"auteur(?:e|rice)?s?|rédigé(?:e|s)?\s+par|écrit\s+par|"
    r"verfasser(?:in|innen)?|geschrieben\s+von|erstellt\s+von)\b",
    re.IGNORECASE,
)
```

1. Dans les documents administratifs / juridiques, la plupart des noms extraits sont des parties, des juges, des avocats ou des greffiers.
2. Pour être envoyé au LLM puis qualifié pour validation humaine, le texte entourant le nom doit comporter **un indicateur d'auteur explicite** (ex: *« rédigé par Me Dupont »*, *« auteur: ... »*, *« écrit par ... »*).
3. Comme les 17 entités n'ont pas cette mention d'auteur explicite dans l'extrait textuel, le pré-filtre les rejette avec la mention :
   `"No explicit authorship cue occurs near the candidate in saved text."`
4. Ces candidats sont enregistrés dans `author_candidate_evaluations` avec le statut `rejected` (non qualifié), et **aucun n'atteint le statut `qualified` à ≥ 90%**.
5. La file affiche donc en toute conformité ALCOA+ :
   > *"No high-confidence author candidates are ready for this queue. Run the next prevalidation batch above. Candidates require an exact, source-verifiable authorship quote and confidence ≥90%; human approval is still required."*

---

### 3. Correctifs appliqués

1. **Emplacement de la base de données fixé sur `RepoScroller\backend\data\reposcroller_ledger.db`** :
   - Dans [backend/config.py](file:///c:/Dev/RepoScroller/backend/config.py), le chemin par défaut pointe désormais explicitement et de manière absolue vers `Path(__file__).resolve().parent / "data" / "reposcroller_ledger.db"`.
   - Dans [.env](file:///c:/Dev/RepoScroller/.env), `DB_PATH=backend/data/reposcroller_ledger.db` est configuré pour garantir qu'aucun fichier temporaire n'est créé dans `scripts/`.
2. **Correction du texte de statut de prévalidation dans le frontend** :
   - Dans [frontend/app.js](file:///c:/Dev/RepoScroller/frontend/app.js#L2035), les interpolations de chaînes de templates corrompues avec `\({...}\)` ont été corrigées. Le bandeau affiche maintenant proprement les valeurs chiffrées réelles (ex: *« Evaluated 10: 10 filtered before LLM, 0 LLM-evaluated, 0 qualified at ≥ 90% »*).