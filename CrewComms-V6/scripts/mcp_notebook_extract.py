#!/usr/bin/env python3
"""MCP server exposing notebook-extract for local orchestration agents.

Tool: notebook_extract(folder, compress=False, vision=False, deep=False, out_slug=None)
Returns JSON with briefing_path, csv_list, vision_stats, wall_clock, exit_code.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HOME_DIR = Path.home()
EXTRACT_BIN = os.environ.get("NOTEBOOK_EXTRACT_BIN", str(HOME_DIR / "bin" / "notebook-extract"))
NOTEBOOK_ROOT = Path(os.environ.get("NOTEBOOK_ROOT", str(HOME_DIR / "Notebook"))).expanduser()

mcp = FastMCP("notebook")


@mcp.tool()
def notebook_extract(
    folder: str,
    compress: bool = False,
    vision: bool = False,
    deep: bool = False,
    out_slug: str | None = None,
) -> str:
    """Run notebook-extract on a folder; return briefing + CSV paths.

    Args:
        folder: Absolute path to the source project folder.
        compress: Run Ollama compression pass over Misc Source Text.
        vision: Run Moondream bulk vision pass on discovered images.
        deep: Use Granite Vision deep tier (requires vision=True).
        out_slug: Override the report output slug under NOTEBOOK_ROOT.

    Returns:
        JSON string with briefing_path, csv_list, vision_stats, wall_clock, exit_code.
    """
    src = Path(folder).expanduser().resolve()
    if not src.is_dir():
        return json.dumps({"error": f"folder not found or not a directory: {src}"})

    cmd = [EXTRACT_BIN, "--folder", str(src)]
    if out_slug:
        cmd += ["--out", out_slug]
    if compress:
        cmd.append("--compress")
    if vision:
        cmd.append("--vision")
    if deep:
        cmd.append("--deep")

    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    wall = round(time.monotonic() - t0, 2)

    stdout = proc.stdout
    stderr = proc.stderr

    out_dir = _find_output_dir(stdout, src, out_slug)
    briefing = out_dir / "briefing.md" if out_dir else None
    csvs = sorted(str(p) for p in (out_dir / "data").glob("*.csv")) if out_dir else []

    vision_stats = _parse_vision_stats(stdout)

    result = {
        "exit_code": proc.returncode,
        "wall_clock_seconds": wall,
        "output_dir": str(out_dir) if out_dir else None,
        "briefing_path": str(briefing) if briefing and briefing.exists() else None,
        "csv_list": csvs,
        "vision_stats": vision_stats,
        "stdout_tail": stdout.splitlines()[-20:] if stdout else [],
        "stderr_tail": stderr.splitlines()[-20:] if stderr else [],
    }
    return json.dumps(result, indent=2)


def _find_output_dir(stdout: str, src: Path, slug: str | None) -> Path | None:
    if slug:
        cand = NOTEBOOK_ROOT / slug
        return cand if cand.is_dir() else None
    m = re.search(rf"({re.escape(str(NOTEBOOK_ROOT))}/[^\s]+)", stdout)
    if m:
        p = Path(m.group(1))
        if p.is_dir():
            return p
    cand = NOTEBOOK_ROOT / src.name.lower()
    return cand if cand.is_dir() else None


def _parse_vision_stats(stdout: str) -> dict | None:
    m = re.search(r"(attempted_images=\d+.*)", stdout)
    if not m:
        return None
    stats = {}
    for pair in m.group(1).split():
        if "=" in pair:
            k, v = pair.split("=", 1)
            try:
                stats[k] = int(v)
            except ValueError:
                stats[k] = v
    return stats


if __name__ == "__main__":
    mcp.run()
