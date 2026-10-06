"""Type-check the UI's JavaScript with TypeScript, without a build step.

    python3 scripts/check_js.py        # needs Node.js; npx fetches TypeScript once

The inline <script> blocks of src/cc_profiles/static/index.html are written to a
temporary file and checked with `tsc --checkJs` against scripts/check_js.d.ts. It
finds misspelled names, wrong arguments and calls of things that do not exist.
Exit status: tsc's (0 when clean).
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the inline scripts of our own page (any case, closing tag with optional spaces)
SCRIPT = re.compile(r"<script>([\s\S]*?)</script\s*>", re.IGNORECASE)
TSC = ["npx", "--yes", "-p", "typescript@5", "tsc"]


def main():
    if not shutil.which("npx"):
        sys.exit("npx not found: install Node.js to run the JavaScript check")
    html = (ROOT / "src" / "cc_profiles" / "static" / "index.html").read_text()
    scripts = SCRIPT.findall(html)
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "index.js"
        # one file, padded so that tsc's line numbers are index.html's
        text = ""
        line = 0
        for m in SCRIPT.finditer(html):
            start = html.count("\n", 0, m.start(1))
            text += "\n" * (start - line) + m.group(1)
            line = start + m.group(1).count("\n")
        js.write_text(text)
        shutil.copy(ROOT / "scripts" / "check_js.d.ts", Path(tmp) / "dom.d.ts")
        r = subprocess.run(TSC + ["--noEmit", "--allowJs", "--checkJs", "--target", "es2022",
                                  "--lib", "es2022,dom,dom.iterable", "index.js", "dom.d.ts"],
                           capture_output=True, text=True, cwd=tmp)
    report = r.stdout.replace("index.js(", "src/cc_profiles/static/index.html(")
    print(report.strip() or f"No problems in {len(scripts)} scripts of index.html.")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
