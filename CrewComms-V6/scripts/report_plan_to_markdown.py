#!/usr/bin/env python3
"""Compile a structured report plan into Notebook markdown."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ALLOWED_BLOCK_TYPES = {
    "paragraph",
    "bullet_list",
    "real_image",
    "generated_image",
    "chart",
    "warning",
}

ALLOWED_CHART_TYPES = {"bar", "line", "scatter", "pie"}


def load_plan(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plan must be a JSON object")
    return data


def require_string(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def require_list(value, field: str) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    return value


def copy_real_image(src: Path, report_dir: Path) -> Path:
    dest_dir = report_dir / "real-images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    counter = 1
    while dest.exists() and dest.read_bytes() != src.read_bytes():
        dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest.relative_to(report_dir)


def compile_block(block: dict, report_dir: Path) -> list[str]:
    block_type = require_string(block.get("type"), "block.type")
    if block_type not in ALLOWED_BLOCK_TYPES:
        raise ValueError(f"unsupported block type: {block_type}")

    if block_type == "paragraph":
        return [require_string(block.get("text"), "paragraph.text")]

    if block_type == "bullet_list":
        items = require_list(block.get("items"), "bullet_list.items")
        return [f"- {require_string(item, 'bullet_list.items[]')}" for item in items]

    if block_type == "warning":
        title = block.get("title")
        text = require_string(block.get("text"), "warning.text")
        if title:
            return [f"**Warning: {require_string(title, 'warning.title')}**", text]
        return ["**Warning**", text]

    if block_type == "real_image":
        src = Path(require_string(block.get("path"), "real_image.path")).expanduser()
        if not src.is_file():
            raise ValueError(f"real_image.path not found: {src}")
        copied = copy_real_image(src, report_dir)
        alt = require_string(block.get("alt") or src.stem.replace("-", " "), "real_image.alt")
        caption = block.get("caption")
        lines = [f"![{alt}]({copied.as_posix()})"]
        if caption:
            lines.append(f"*{require_string(caption, 'real_image.caption')}*")
        return lines

    if block_type == "generated_image":
        prompt = require_string(block.get("prompt"), "generated_image.prompt")
        size = block.get("size") or [1024, 1024]
        steps = int(block.get("steps", 22))
        cfg = float(block.get("cfg", 7))
        negative = block.get("negative")
        caption = block.get("caption")
        lines = ["```comfyui", f"prompt: {prompt}"]
        if negative:
            lines.append(f"negative: {require_string(negative, 'generated_image.negative')}")
        lines.append(f"size: [{int(size[0])}, {int(size[1])}]")
        lines.append(f"steps: {steps}")
        lines.append(f"cfg: {cfg:g}")
        workflow = block.get("workflow")
        if workflow:
            lines.append(f"workflow: {require_string(workflow, 'generated_image.workflow')}")
        lines.append("```")
        if caption:
            lines.append(f"*{require_string(caption, 'generated_image.caption')}*")
        return lines

    if block_type == "chart":
        chart_type = require_string(block.get("chart_type") or block.get("type_name") or block.get("kind") or block.get("chart"), "chart.chart_type").lower()
        if chart_type not in ALLOWED_CHART_TYPES:
            raise ValueError(f"unsupported chart type: {chart_type}")
        data = require_string(block.get("data"), "chart.data")
        x_value = require_string(block.get("x"), "chart.x")
        y_value = block.get("y")
        if isinstance(y_value, str):
            y_lines = [f"y: {y_value}"]
        elif isinstance(y_value, list) and y_value:
            y_lines = [f"y: [{', '.join(require_string(item, 'chart.y[]') for item in y_value)}]"]
        else:
            raise ValueError("chart.y must be a non-empty string or list")

        lines = ["```chart", f"type: {chart_type}", f"data: {data}", f"x: {x_value}"]
        lines.extend(y_lines)
        for field in ("title", "xlabel", "ylabel", "format", "marker"):
            if block.get(field):
                lines.append(f"{field}: {require_string(block.get(field), f'chart.{field}')}")
        for field in ("width", "height", "dpi", "x_rotation"):
            if block.get(field) is not None:
                lines.append(f"{field}: {block.get(field)}")
        for field in ("legend", "grid"):
            if block.get(field) is not None:
                lines.append(f"{field}: {'true' if block.get(field) else 'false'}")
        lines.append("```")
        caption = block.get("caption")
        if caption:
            lines.append(f"*{require_string(caption, 'chart.caption')}*")
        return lines

    raise ValueError(f"unhandled block type: {block_type}")


def compile_plan(plan: dict, report_dir: Path) -> str:
    title = require_string(plan.get("title"), "plan.title")
    lines = [f"# {title}", ""]
    if plan.get("subtitle"):
        lines.extend([require_string(plan.get("subtitle"), "plan.subtitle"), ""])
    if plan.get("executive_summary"):
        lines.extend(["## Executive Summary", "", require_string(plan.get("executive_summary"), "plan.executive_summary"), ""])

    sections = require_list(plan.get("sections"), "plan.sections")
    for section in sections:
        heading = require_string(section.get("heading"), "section.heading")
        lines.extend([f"## {heading}", ""])
        for block in require_list(section.get("blocks"), f"section.blocks ({heading})"):
            lines.extend(compile_block(block, report_dir))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a report plan JSON file into Notebook markdown")
    parser.add_argument("plan", help="Path to report plan JSON")
    parser.add_argument("output", help="Path to output source.md")
    args = parser.parse_args()

    plan_path = Path(args.plan).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_dir = output_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    plan = load_plan(plan_path)
    markdown = compile_plan(plan, report_dir)
    output_path.write_text(markdown, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
