"""Test that service-level imports work correctly."""
import sys
sys.path.insert(0, ".")


def test_services_import():
    from infra.llm.gateway import llm_gateway
    print("  llm_gateway OK")

    from services.inception_svc import inception_svc
    print("  inception_svc OK")

    from services.workflow_svc import workflow_svc
    print("  workflow_svc OK")

    from services.llm_svc import llm_svc
    print("  llm_svc OK")

    from api.routes_lifecycle import router
    print("  routes_lifecycle OK")

    from api.routes_inception import router as incep_router
    print("  routes_inception OK")

    print("\nAll service imports passed!")


if __name__ == "__main__":
    test_services_import()
