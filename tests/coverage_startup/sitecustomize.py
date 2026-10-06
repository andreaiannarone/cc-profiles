# Put on PYTHONPATH by tests/conftest.py, only when the suite runs under coverage:
# Python imports this module at startup, so the servers and command-line runs the
# tests start are measured too (COVERAGE_PROCESS_START names the config).
import os

import coverage

_cov = coverage.process_startup()

if _cov is not None:
    # The server replaces coverage's SIGTERM handler with its own, which ends with
    # os._exit() (cli.stop_gracefully): that skips atexit, so save the data first.
    _exit = os._exit

    def _exit_saving_coverage(code):
        try:
            _cov.stop()
            _cov.save()
        except Exception:
            pass
        _exit(code)

    os._exit = _exit_saving_coverage
