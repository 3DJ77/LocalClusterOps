#!/usr/bin/env python3
"""Notebook assembler — stitch rendered.md + artifacts/ into HTML + PDF.

Reads a report directory produced by notebook-render:
    ~/Notebook/<report-name>/
        rendered.md
        artifacts/
            001-hash.png
            002-hash.svg
            manifest.json

Produces:
    <report-name>.html   (pandoc -t html5 --standalone --embed-resources)
    <report-name>.pdf    (pandoc --pdf-engine=weasyprint)

Both outputs land in the same report directory.

Usage:
    notebook-assemble ~/Notebook/my-report
    notebook-assemble ~/Notebook/my-report --html-only
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

NOTEBOOK_ROOT = Path.home() / "Notebook"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Locate weasyprint — prefer project venv, fallback to PATH
VENV_WEASYPRINT = PROJECT_ROOT / ".venv" / "bin" / "weasyprint"
SYSTEM_WEASYPRINT = shutil.which("weasyprint")
WEASYPRINT = str(VENV_WEASYPRINT) if VENV_WEASYPRINT.exists() else SYSTEM_WEASYPRINT

# wkhtmltopdf as final fallback
WKHTMLTOPDF = shutil.which("wkhtmltopdf")


def find_pandoc() -> str:
    """Return path to pandoc or exit with a clear message."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        print(
            "ERROR: pandoc not found on PATH.\n"
            "Install via:  sudo apt install pandoc\n"
            "         or:  https://pandoc.org/installing.html",
            file=sys.stderr,
        )
        sys.exit(1)
    return pandoc


def find_pdf_engine() -> tuple[str, str] | None:
    """Return (engine_path, engine_name) or None if nothing available."""
    if WEASYPRINT:
        return (WEASYPRINT, "weasyprint")
    if WKHTMLTOPDF:
        return (WKHTMLTOPDF, "wkhtmltopdf")
    return None


def pandoc_metadata_args(report_name: str) -> list[str]:
    """Metadata flags shared by HTML and PDF invocations."""
    title = report_name.replace("-", " ").replace("_", " ").title()
    return [
        "--metadata", f"title={title}",
        "--metadata", "lang=en",
    ]


def build_html(pandoc: str, report_dir: Path, report_name: str) -> Path:
    """Build a self-contained HTML file with embedded resources."""
    rendered = report_dir / "rendered.md"
    output = report_dir / f"{report_name}.html"

    cmd = [
        pandoc,
        str(rendered),
        "-t", "html5",
        "--standalone",
        "--embed-resources",
        f"--resource-path={report_dir}",
        "-o", str(output),
    ] + pandoc_metadata_args(report_name)

    print(f"  HTML: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(report_dir))
    if result.returncode != 0:
        print(f"ERROR: pandoc HTML failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    if result.stderr.strip():
        # Print warnings but don't fail
        for line in result.stderr.strip().splitlines():
            print(f"  [pandoc] {line}")

    print(f"  ✓ {output}  ({output.stat().st_size:,} bytes)")
    return output


def build_pdf(pandoc: str, report_dir: Path, report_name: str) -> Path | None:
    """Build a PDF via pandoc + weasyprint (or wkhtmltopdf fallback)."""
    engine = find_pdf_engine()
    if engine is None:
        print(
            "WARNING: No PDF engine found. Install one:\n"
            f"  Option 1 (recommended):  {PROJECT_ROOT / '.venv' / 'bin' / 'pip'} install weasyprint\n"
            "  Option 2:                sudo apt install wkhtmltopdf\n"
            "Continuing with HTML output only.",
            file=sys.stderr,
        )
        return None

    engine_path, engine_name = engine
    rendered = report_dir / "rendered.md"
    output = report_dir / f"{report_name}.pdf"

    cmd = [
        pandoc,
        str(rendered),
        "-t", "html5",
        "--standalone",
        "--embed-resources",
        f"--resource-path={report_dir}",
        f"--pdf-engine={engine_path}",
        "-o", str(output),
    ] + pandoc_metadata_args(report_name)

    print(f"  PDF ({engine_name}): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(report_dir))
    if result.returncode != 0:
        print(f"WARNING: pandoc PDF failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        print("Continuing without PDF output.", file=sys.stderr)
        return None
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            # Suppress noisy weasyprint CSS warnings — they're benign
            if "unknown property" in line or "invalid value" in line or "was ignored" in line:
                continue
            print(f"  [pandoc] {line}")

    print(f"  ✓ {output}  ({output.stat().st_size:,} bytes)")
    return output


def main():
    parser = argparse.ArgumentParser(
        description="Assemble Notebook rendered.md + artifacts into HTML and PDF"
    )
    parser.add_argument(
        "report_dir",
        help="Path to a Notebook report directory (contains rendered.md + artifacts/)",
    )
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="Generate only the HTML output (skip PDF)",
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Generate only the PDF output (skip HTML)",
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    rendered = report_dir / "rendered.md"

    if not report_dir.is_dir():
        print(f"ERROR: Not a directory: {report_dir}", file=sys.stderr)
        sys.exit(1)
    if not rendered.is_file():
        print(f"ERROR: Missing rendered.md in {report_dir}", file=sys.stderr)
        sys.exit(1)

    report_name = report_dir.name
    pandoc = find_pandoc()

    print(f"Assembling: {report_dir}")
    print(f"  Source:  {rendered}")
    print(f"  Report:  {report_name}")

    outputs = []

    if not args.pdf_only:
        html_path = build_html(pandoc, report_dir, report_name)
        outputs.append(("HTML", str(html_path)))

    if not args.html_only:
        pdf_path = build_pdf(pandoc, report_dir, report_name)
        if pdf_path is not None:
            outputs.append(("PDF", str(pdf_path)))
        elif args.pdf_only:
            print("ERROR: PDF output was requested but could not be generated.", file=sys.stderr)
            sys.exit(1)

    print()
    print("Assembly complete:")
    for fmt, path in outputs:
        print(f"  {fmt}: {path}")


if __name__ == "__main__":
    main()
