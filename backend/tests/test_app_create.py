"""Test that the FastAPI app can be created with all routes registered."""
import sys
sys.path.insert(0, ".")

from bootstrap.app import create_app

app = create_app()
route_paths = [r.path for r in app.routes if hasattr(r, "path")]

print(f"FastAPI app created OK")
print(f"Total routes: {len(app.routes)}")
print(f"API routes: {len([p for p in route_paths if p.startswith('/api')])}")

# Verify key routes exist
expected = [
    "/api/v1/health",
    "/api/v1/llm/providers",
    "/api/v1/inceptions/sessions",
    "/api/v1/workflow/active",
    "/api/v1/lifecycle/state",
]
for ep in expected:
    found = any(ep in p for p in route_paths)
    status = "✓" if found else "✗"
    print(f"  {status} {ep}")

if all(any(ep in p for p in route_paths) for ep in expected):
    print("\nAll critical routes registered!")
else:
    missing = [ep for ep in expected if not any(ep in p for p in route_paths)]
    print(f"\nMISSING routes: {missing}")
    sys.exit(1)
