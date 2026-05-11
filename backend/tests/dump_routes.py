"""Dump all registered API routes."""
import sys
sys.path.insert(0, ".")
from bootstrap.app import create_app

app = create_app()
for r in app.routes:
    if hasattr(r, "methods"):
        methods = ",".join(sorted(r.methods - {"HEAD", "OPTIONS"}))
        if methods:
            print(f"{methods:6s} {r.path}")
