# Put on PYTHONPATH by tests/conftest.py, only when the suite runs under coverage:
# Python imports this module at startup, so the servers and command-line runs the
# tests start are measured too (COVERAGE_PROCESS_START names the config).
import os

import coverage

# Every process writes its data next to the config (the repository), not in its own
# working folder: the servers and CLI runs work inside fake homes, which tests compare
# before and after, and whose files coverage combine would never find.
if os.environ.get("COVERAGE_PROCESS_START"):
    os.environ.setdefault("COVERAGE_FILE", os.path.join(os.path.dirname(os.path.abspath(os.environ["COVERAGE_PROCESS_START"])), ".coverage"))

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
