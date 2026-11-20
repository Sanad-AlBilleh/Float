"""Write this service's OpenAPI document to openapi.json (Assignment 2 §8a).

FastAPI builds the document from the routes, so it always matches the code. CI runs this script and fails
if the committed file differs ("git diff --exit-code"), so a route change without its document is caught.
Usage, from the service folder: python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

# Placeholder settings: building the document needs no database and no real secrets.
settings = Settings(database_url="mssql://docs:docs@localhost:1433/docs", token_secret="docs", internal_api_key="docs")
document = create_app(settings, run_migrations=False).openapi()
target = Path(__file__).resolve().parents[1] / "openapi.json"
target.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {target.name}: {len(document['paths'])} paths")
