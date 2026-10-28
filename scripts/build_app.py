"""Compile the Mac app into the package, for both Intel and Apple Silicon.

    python3 scripts/build_app.py          # macOS with swiftc (Xcode or its command line tools)

Writes src/cc_profiles/app/cc-profiles-app from src/cc_profiles/app/main.swift, the program
that `cc-profiles install-app` puts in ~/Applications/cc-profiles.app. The release workflow
runs it on a macOS runner before building the package; a checkout without it compiles the
app for its own Mac when `cc-profiles install-app` runs.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cc_profiles import macapp  # noqa: E402


def main():
    if sys.platform != "darwin":
        sys.exit("The Mac app can only be built on macOS")
    out = macapp.build_binary(macapp.APP_BINARY, archs=["arm64", "x86_64"])
    print(subprocess.run(["lipo", "-info", out], capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
