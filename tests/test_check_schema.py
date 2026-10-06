"""Tests for scripts/check_settings_schema.py, on a small fake Claude Code "binary"
written from SETTING_FIELDS with the same shapes as the real one."""
import importlib.util
import subprocess
import sys

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "check_settings_schema.py"
spec = importlib.util.spec_from_file_location("check_settings_schema", SCRIPT)
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)

sys.path.insert(0, str(ROOT / "src"))
from cc_profiles.settings import SETTING_FIELDS  # noqa: E402


def values(fd):
    return [o[0] if isinstance(o, (list, tuple)) else o for o in fd.get("options") or []]


def js_list(vals):
    return "[" + ",".join(f'"{v}"' for v in vals) + "]"


def schema_snippet(fd, override=None):
    """The zod schema of a field, as the minified binary writes it."""
    if override is not None:
        return override
    if fd["type"] == "bool" and "off_value" not in fd:
        return "H()"
    if fd["type"] == "number":
        return "C().int().positive()"
    if fd["type"] == "select" and not isinstance(fd.get("options"), str):
        return f"j({js_list(values(fd))})"
    return "o()"


def fake_binary(path, schema=None, drop=(), panel_extra=(), panel_drop=(), panel_options=None):
    """schema: {key: zod expression} overrides; drop: keys left out of the schema;
    panel_*: items added to or removed from /config, or their options replaced."""
    schema, panel_options = schema or {}, panel_options or {}
    parts = [b"\x7fELF\x00\x01junk\x00", b'var Q={VERSION:"9.9.9",BUILD_TIME:"x"};\x00',
             b',effortLevel:()=>j(["low","medium","high"]).optional().catch(void 0).describe("Effort"),',
             b',cleanupPeriodDays:()=>C().int().positive().optional().describe("Days"),',
             # a lazy chunk with the same name as a key comes first: not the schema
             b',theme:()=>import("/$bunfs/root/chunk-x.js"),tui:()=>import("/$bunfs/root/chunk-y.js"),',
             # an unrelated list with the same minified name as the theme list below
             b'let seo=["allowUnixSockets","httpProxyPort"];\x00']
    keys = {fd["key"] for fd in SETTING_FIELDS}
    for fd in SETTING_FIELDS:
        key = fd["key"]
        if key in drop or (fd.get("file") == "global" and key not in schema):
            continue
        expr = schema_snippet(fd, schema.get(key))
        if key == "timeFormat" and key not in schema:  # a named list in a union with any string
            parts.append(f'var x6e={js_list(values(fd))};'.encode())
            expr = "Fe([j(x6e),o()])"
        if "." in key:
            parent, leaf = key.split(".")
            parts.append(f',{parent}:()=>u({{other:o().optional(),{leaf}:{expr}.optional().describe("d")}})'
                         f'.optional(),'.encode())
        else:
            parts.append(f',{key}:()=>{expr}.optional().describe("d"),'.encode())
    if "language" not in keys:  # reference keys the script learns the function names from
        parts.append(b',language:()=>o().optional().describe("Language"),')
    if "prefersReducedMotion" not in keys:
        parts.append(b',prefersReducedMotion:()=>H().optional().describe("Motion"),')
    # the /config panel; theme spreads a named list, defined near the panel
    by_key = {fd["key"]: fd for fd in SETTING_FIELDS}
    theme_vals = values(by_key["theme"])
    parts.append(f'let seo={js_list(theme_vals[1:])},ktt=["{theme_vals[0]}",...seo];'.encode())
    items = []
    for iid, key in list(chk.CONFIG_IDS.items()) + [(i, None) for i in panel_extra]:
        if iid in panel_drop:
            continue
        fd = by_key.get(key) if key else None
        label = "Auto-compact" if iid == "autoCompact" else (fd["label"] if fd else iid.title())
        if iid == "theme":
            body = 'type:"managedEnum",options:ktt'
        elif fd and fd["type"] == "select" and not isinstance(fd.get("options"), str):
            body = f'options:{panel_options.get(iid, js_list(values(fd)))},type:"enum"'
        else:
            body = 'type:"boolean"'
        item = f'{{id:"{iid}",label:"{label}",value:s.x,{body},onChange(e){{W("x",e),w((o)=>({{...o,x:e}}))}}}}'
        items.append(f'...k("flag")?[{item}]:[]' if iid == "verbose" else item)
    parts.append(("let Oe=1,Pe=[" + ",".join(items) + "];return Pe}").encode())
    parts.append(b"\x00trailing junk [ ( {")
    path.write_bytes(b"".join(parts))
    return path


def run(path):
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)


def test_matching_binary_reports_no_differences(tmp_path):
    r = run(fake_binary(tmp_path / "claude"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Claude Code **9.9.9**" in r.stdout
    assert "No differences" in r.stdout


def test_reports_enum_changes_through_named_and_spread_lists(tmp_path):
    fd = next(f for f in SETTING_FIELDS if f["key"] == "timeFormat")
    vals = values(fd)
    path = fake_binary(tmp_path / "claude", schema={
        fd["key"]: "Fe([j(ab$),o()])",
        "autoUpdatesChannel": 'j(["latest","beta"])',
    })
    # ab$ spreads another list: the second definition of base shares values with ours
    data = path.read_bytes() + f';var base=["unrelated"];var base={js_list(vals[1:])},ab$=["{vals[0]}",...base,"brand-new"];'.encode()
    path.write_bytes(data)
    r = run(path)
    assert r.returncode == 1
    assert f"`{fd['key']}`" in r.stdout and "new values `brand-new`" in r.stdout
    assert "`autoUpdatesChannel`" in r.stdout and "new values `beta`" in r.stdout
    assert "values no longer listed `stable`" in r.stdout


def test_reports_type_changes_and_missing_keys(tmp_path):
    r = run(fake_binary(tmp_path / "claude", schema={"spinnerTipsEnabled": "o()", "worktree.baseRef": "H()"},
                        drop=("awaySummaryEnabled",)))
    assert r.returncode == 1
    assert "`spinnerTipsEnabled` (Show tips): type changed: the schema says string, the field expects bool" in r.stdout
    assert "`worktree.baseRef`" in r.stdout and "the schema says bool, the field expects enum" in r.stdout
    assert "`awaySummaryEnabled` (Session recap): missing from the schema" in r.stdout


def test_values_computed_at_runtime_are_flagged(tmp_path):
    fd = next(f for f in SETTING_FIELDS if f["key"] == "permissions.defaultMode")
    vals = values(fd)
    path = fake_binary(tmp_path / "claude", schema={fd["key"]: "Ki(Rg,j([...b$,...Vo(e)]))"})
    path.write_bytes(path.read_bytes() + f';b$={js_list(vals[:2] + ["bypassPermissions"])};'.encode())
    r = run(path)
    assert r.returncode == 1
    assert "bypassPermissions" not in r.stdout  # left out on purpose (LEFT_OUT)
    assert "computed at runtime" in r.stdout


def test_global_fields_are_checked_against_the_config_panel(tmp_path):
    r = run(fake_binary(tmp_path / "claude", panel_extra=("shinyNewToggle",), panel_drop=("diffTool", "fast"),
                        panel_options={"editor": '["normal","vim","emacs"]', "notifChannel": '[..."auto"]'}))
    assert r.returncode == 1
    out = r.stdout
    assert "New item `shinyNewToggle`" in out
    assert "Item `diffTool` is gone (it edits `diffTool`)" in out
    assert "Item `fast` is gone" in out
    assert "`diffTool` (Diff tool): /config item `diffTool` not found" in out
    assert "`editorMode` (Editor mode): new values `emacs`" in out
    assert "`preferredNotifChannel`" in out


def test_unreadable_layout_and_missing_binary_exit_2(tmp_path):
    junk = tmp_path / "claude"
    junk.write_bytes(b"\x00not claude at all\x00")
    r = run(junk)
    assert r.returncode == 2 and "Reference key" in r.stderr
    r = run(tmp_path / "missing")
    assert r.returncode == 2 and "not found" in r.stderr


def test_output_file(tmp_path):
    out = tmp_path / "report.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(fake_binary(tmp_path / "claude", drop=("verbose",))),
                        "--output", str(out)], capture_output=True, text=True)
    assert r.returncode == 0  # verbose is a global field: the schema is not where it lives
    assert out.read_text().startswith("# Claude Code settings schema check")
