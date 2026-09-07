"""Run all APEX Partnership test suites.

Usage:
    python tests/run_tests.py           # Run unit tests only
    python tests/run_tests.py --all     # Run unit + integration tests
"""
import subprocess
import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_suite(label: str, script: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, script],
        cwd=BACKEND_DIR,
        capture_output=False,
    )
    return result.returncode == 0


def main():
    run_integration = "--all" in sys.argv

    unit_ok = run_suite("Unit Tests", os.path.join(BACKEND_DIR, "tests", "test_unit.py"))

    integration_ok = True
    if run_integration:
        integration_ok = run_suite("Integration Tests (requires Docker stack)", os.path.join(BACKEND_DIR, "tests", "test_integration.py"))
    else:
        print("\n  [SKIP] Integration tests (use --all to include)")

    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    print(f"  Unit tests:       {'PASS' if unit_ok else 'FAIL'}")
    if run_integration:
        print(f"  Integration tests: {'PASS' if integration_ok else 'FAIL'}")

    all_pass = unit_ok and integration_ok
    print(f"\n  Overall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print(f"{'='*60}\n")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
