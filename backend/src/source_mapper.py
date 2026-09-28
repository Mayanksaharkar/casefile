import os
import json
from pathlib import Path

def generate_test_vectors(frontend_path: str):
    vectors = []
    app_dir = Path(frontend_path) / "app"
    if not app_dir.exists():
        return vectors
        
    for page_file in app_dir.rglob("page.js"):
        rel_path = page_file.parent.relative_to(app_dir)
        route = "/" if str(rel_path) == "." else f"/{rel_path}"
        vectors.append({
            "route": route,
            "actions": [
                {"type": "navigate", "url": route},
                {"type": "screenshot", "name": f"baseline_{route.replace('/', '_')}"}
            ]
        })
        
    out_path = Path("data/test-vectors.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(vectors, f, indent=2)
    return vectors
