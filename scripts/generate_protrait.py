import sys
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

out_path = Path(r"C:\Dev\RepoScroller\portraits\Antoine_Falempin_Portrait.md")
out_path.parent.mkdir(parents=True, exist_ok=True)

try:
    resp = httpx.post(
        "http://127.0.0.1:8090/api/v1/dossier/generate",
        json={"node_id": "Antoine Falempin", "stream": False},
        timeout=90.0
    )
    data = resp.json()
except Exception:
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/dossier/generate",
        json={"node_id": "Antoine Falempin", "stream": False}
    )
    data = resp.json()

with open(out_path, "w", encoding="utf-8") as f:
    f.write(data["markdown"])

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
print(data["markdown"])