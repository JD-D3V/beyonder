"""Negative tests for frontend/scripts/fetch-icons.sh's embedded validator.

Extracts the heredoc python and runs it against crafted API responses (stdlib
only, no network).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "fetch-icons.sh"
ICON_ID = "lucide:test-icon"
ROOT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
)


def _embedded_python() -> str:
    m = re.search(r"<<'PY'\n(.*?)\nPY\n", SCRIPT.read_text(), re.S)
    assert m, "embedded python not found"
    return m.group(1)


def _run(tmp_path, body: str):
    (tmp_path / "lucide__test-icon.json").write_text(
        json.dumps({"svg": ROOT + body + "</svg>"})
    )
    prog = tmp_path / "gen.py"
    prog.write_text(_embedded_python())
    out = tmp_path / "icons.tsx"
    p = subprocess.run(
        [sys.executable, str(prog), str(tmp_path), str(out), ICON_ID],
        capture_output=True, text=True,
    )
    return p, out


def test_valid_icon_succeeds(tmp_path):
    p, out = _run(tmp_path, '<path d="M4 4h16" />')
    assert p.returncode == 0, p.stderr
    text = out.read_text()
    assert "export function IconTestIcon" in text and 'd="M4 4h16"' in text


def test_onclick_attribute_rejected(tmp_path):
    p, out = _run(tmp_path, '<path d="M4 4h16" onClick="alert(1)" />')
    assert p.returncode != 0 and "onClick" in p.stderr
    assert not out.exists()


def test_brace_in_value_rejected(tmp_path):
    p, out = _run(tmp_path, '<path d="M4 4{evil}" />')
    assert p.returncode != 0 and "forbidden character" in p.stderr
    assert not out.exists()


def test_disallowed_tag_rejected(tmp_path):
    p, out = _run(tmp_path, "<script>alert(1)</script>")
    assert p.returncode != 0 and "unsupported element" in p.stderr
    assert not out.exists()
