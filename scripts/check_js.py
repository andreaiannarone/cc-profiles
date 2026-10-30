"""Type-check the UI's JavaScript with TypeScript, without a build step.

    python3 scripts/check_js.py        # needs Node.js; npx fetches TypeScript once

The scripts of src/cc_profiles/static/ (the files index.html loads, plus its inline
<script> blocks) are copied to a temporary folder and checked together, as the one
global scope the page gives them, with `tsc --checkJs` against scripts/check_js.d.ts.
It finds misspelled names, wrong arguments and calls of things that do not exist.
Exit status: tsc's (0 when clean).
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "cc_profiles" / "static"
# the inline scripts of our own page (any case, a nonce, closing tag with optional spaces)
SCRIPT = re.compile(r"<script(?: nonce=\"[^\"]*\")?>([\s\S]*?)</script\s*>", re.IGNORECASE)
# the page's own script files, in the order it loads them
SCRIPT_FILE = re.compile(r'<script src="/static/([a-z]+\.js)"></script>')
TSC = ["npx", "--yes", "-p", "typescript@5", "tsc"]


def main():
    if not shutil.which("npx"):
        sys.exit("npx not found: install Node.js to run the JavaScript check")
    html = (STATIC / "index.html").read_text()
    files = SCRIPT_FILE.findall(html)
    with tempfile.TemporaryDirectory() as tmp:
        # the inline scripts in one file, padded so that tsc's line numbers are index.html's
        text = ""
        line = 0
        for m in SCRIPT.finditer(html):
            start = html.count("\n", 0, m.start(1))
            text += "\n" * (start - line) + m.group(1)
            line = start + m.group(1).count("\n")
        (Path(tmp) / "index.js").write_text(text)
        for name in files:
            shutil.copy(STATIC / name, Path(tmp) / name)
        shutil.copy(ROOT / "scripts" / "check_js.d.ts", Path(tmp) / "dom.d.ts")
        r = subprocess.run(TSC + ["--noEmit", "--allowJs", "--checkJs", "--target", "es2022",
                                  "--lib", "es2022,dom,dom.iterable", "index.js", *files, "dom.d.ts"],
                           capture_output=True, text=True, cwd=tmp)
    report = re.sub(r"^([a-z]+)\.js\(", lambda m: f"src/cc_profiles/static/{'index.html' if m.group(1) == 'index' else m.group(1) + '.js'}(",
                    r.stdout, flags=re.M)
    print(report.strip() or f"No problems in index.html and {len(files)} scripts.")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
