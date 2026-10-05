# Put on PYTHONPATH by tests/conftest.py, only when the suite runs under coverage:
# Python imports this module at startup, so the servers and command-line runs the
# tests start are measured too (COVERAGE_PROCESS_START names the config).
import coverage

coverage.process_startup()
