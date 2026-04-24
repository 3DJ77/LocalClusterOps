#!/usr/bin/env python3
import argparse
import base64
import csv
import json
import logging
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
import yaml

from spine_lock import SpineLock

logger = logging.getLogger(__name__)


TAG_PATTERN = re.compile(r"```(comfyui|chart|laser|kicad|dxf|stl)\s*\n(.*?)\n```", re.DOTALL)
NOTEBOOK_ROOT = Path.home() / "Notebook"
DEFAULT_A1111_URL = "http://127.0.0.1:8189"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"


def slugify(value):
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "report"


def load_yaml_payload(raw):
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("tag payload must be a YAML mapping")
    return data


def image_markdown(path, report_dir):
    rel = path.relative_to(report_dir)
    return f"![generated artifact]({rel.as_posix()})"


class NotebookRenderer:
    def __init__(self, report_name, a1111_url, comfyui_url, skip_comfyui=False):
        self.report_name = slugify(report_name)
        self.report_dir = NOTEBOOK_ROOT / self.report_name
        self.artifacts_dir = self.report_dir / "artifacts"
        self.a1111_url = a1111_url.rstrip("/")
        self.comfyui_url = comfyui_url.rstrip("/")
        self.skip_comfyui = skip_comfyui
        self.counter = 0
        self.manifest = []
        self.source_dir = Path.cwd()

    def prepare(self):
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def next_artifact(self, suffix):
        self.counter += 1
        return self.artifacts_dir / f"{self.counter:03d}-{uuid.uuid4().hex[:8]}{suffix}"

    def render_markdown(self, source, source_dir):
        self.source_dir = source_dir

        def replace(match):
            tag = match.group(1)
            payload = load_yaml_payload(match.group(2))
            if tag == "comfyui":
                return self.render_comfyui(payload)
            if tag == "chart":
                return self.render_chart(payload)
            return self.write_pending(tag, payload)

        return TAG_PATTERN.sub(replace, source)

    def render_comfyui(self, payload):
        if self.skip_comfyui:
            artifact = self.next_artifact(".comfyui.pending.yml")
            artifact.write_text(
                yaml.safe_dump(
                    {"backend": "comfyui", "payload": payload, "reason": "deferred_comfyui"},
                    sort_keys=False,
                )
            )
            self.record("comfyui", artifact, {"route": "pending", "reason": "deferred_comfyui"})
            return f"[generated image deferred]({artifact.relative_to(self.report_dir).as_posix()})"
        logger.info("Acquiring SPINE lock for comfyui render…")
        with SpineLock("notebook-renderer"):
            logger.info("SPINE lock acquired — starting comfyui render")
            if payload.get("workflow"):
                artifact = self.render_comfyui_workflow(payload)
            else:
                artifact = self.render_comfyui_a1111(payload)
        logger.info("SPINE lock released after comfyui render")
        return image_markdown(artifact, self.report_dir)

    def render_comfyui_a1111(self, payload):
        size = payload.get("size") or [payload.get("width", 1024), payload.get("height", 1024)]
        width, height = int(size[0]), int(size[1])
        request_payload = {
            "prompt": payload.get("prompt", ""),
            "negative_prompt": payload.get("negative_prompt", payload.get("negative", "")),
            "width": width,
            "height": height,
            "steps": int(payload.get("steps", 22)),
            "cfg_scale": float(payload.get("cfg_scale", payload.get("cfg", 7))),
            "sampler_name": payload.get("sampler_name", "euler"),
            "seed": int(payload.get("seed", -1)),
        }
        response = requests.post(f"{self.a1111_url}/sdapi/v1/txt2img", json=request_payload, timeout=420)
        response.raise_for_status()
        data = response.json()
        image = data["images"][0]
        artifact = self.next_artifact(".png")
        artifact.write_bytes(base64.b64decode(image))
        self.record("comfyui", artifact, {"route": "a1111-shim", "request": request_payload, "info": data.get("info")})
        return artifact

    def render_comfyui_workflow(self, payload):
        workflow_path = Path(str(payload["workflow"])).expanduser()
        workflow = json.loads(workflow_path.read_text())
        response = requests.post(
            f"{self.comfyui_url}/prompt",
            json={"prompt": workflow, "client_id": "notebook-renderer"},
            timeout=30,
        )
        response.raise_for_status()
        prompt_id = response.json()["prompt_id"]
        history = self.wait_for_comfyui(prompt_id)
        image_meta = self.first_comfyui_image(history)
        image_response = requests.get(f"{self.comfyui_url}/view?{urlencode(image_meta)}", timeout=30)
        image_response.raise_for_status()
        artifact = self.next_artifact(".png")
        artifact.write_bytes(image_response.content)
        self.record("comfyui", artifact, {"route": "workflow", "workflow": str(workflow_path), "prompt_id": prompt_id})
        return artifact

    def wait_for_comfyui(self, prompt_id):
        deadline = time.time() + 420
        while time.time() < deadline:
            response = requests.get(f"{self.comfyui_url}/history/{prompt_id}", timeout=10)
            response.raise_for_status()
            history = response.json().get(prompt_id, {})
            if history.get("outputs"):
                return history
            time.sleep(1)
        raise TimeoutError(f"ComfyUI workflow timed out: {prompt_id}")

    def first_comfyui_image(self, history):
        for output in history.get("outputs", {}).values():
            images = output.get("images") or []
            if images:
                return images[0]
        raise RuntimeError("ComfyUI workflow completed without image output")

    def render_chart(self, payload):
        chart_type = str(payload.get("type", "line")).lower()
        if chart_type not in {"bar", "line", "scatter", "pie"}:
            raise ValueError(f"unsupported chart type: {chart_type}")

        data_path = self.resolve_input_path(payload["data"])
        rows = self.read_csv_rows(data_path)
        x_key = payload["x"]
        y_keys = self.normalize_y_keys(payload["y"])
        x_values = [row[x_key] for row in rows]
        y_series = {key: [self.to_number(row[key]) for row in rows] for key in y_keys}

        fmt = str(payload.get("format", "png")).lower().lstrip(".")
        if fmt not in {"png", "svg"}:
            raise ValueError("chart format must be png or svg")

        width = float(payload.get("width", 8))
        height = float(payload.get("height", 4.5))
        dpi = int(payload.get("dpi", 144))
        artifact = self.next_artifact(f".{fmt}")

        fig, ax = plt.subplots(figsize=(width, height))
        try:
            if chart_type == "bar":
                self.plot_bar(ax, x_values, y_series)
            elif chart_type == "line":
                for key, values in y_series.items():
                    ax.plot(x_values, values, marker=payload.get("marker", "o"), label=key)
            elif chart_type == "scatter":
                for key, values in y_series.items():
                    ax.scatter(x_values, values, label=key)
            elif chart_type == "pie":
                if len(y_keys) != 1:
                    raise ValueError("pie chart requires exactly one y column")
                values = y_series[y_keys[0]]
                ax.pie(values, labels=x_values, autopct="%1.1f%%", startangle=90)
                ax.axis("equal")

            ax.set_title(str(payload.get("title", "")))
            if chart_type != "pie":
                ax.set_xlabel(str(payload.get("xlabel", x_key)))
                ax.set_ylabel(str(payload.get("ylabel", ", ".join(y_keys))))
                if len(y_keys) > 1 or payload.get("legend", len(y_keys) > 1):
                    ax.legend()
                if payload.get("grid", True):
                    ax.grid(True, alpha=0.25)
                fig.autofmt_xdate(rotation=int(payload.get("x_rotation", 30)), ha="right")
            fig.tight_layout()
            fig.savefig(artifact, dpi=dpi if fmt == "png" else None, format=fmt)
        finally:
            plt.close(fig)

        self.record(
            "chart",
            artifact,
            {
                "route": "matplotlib",
                "type": chart_type,
                "data": str(data_path),
                "x": x_key,
                "y": y_keys,
                "format": fmt,
            },
        )
        return image_markdown(artifact, self.report_dir)

    def resolve_input_path(self, value):
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.source_dir / path
        return path

    def read_csv_rows(self, path):
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError(f"chart CSV has no data rows: {path}")
        return rows

    def normalize_y_keys(self, value):
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def to_number(self, value):
        try:
            return int(value)
        except ValueError:
            return float(value)

    def plot_bar(self, ax, x_values, y_series):
        keys = list(y_series)
        positions = list(range(len(x_values)))
        if len(keys) == 1:
            ax.bar(positions, y_series[keys[0]], label=keys[0])
        else:
            width = 0.8 / len(keys)
            offsets = [index - ((len(keys) - 1) / 2) for index in range(len(keys))]
            for offset, key in zip(offsets, keys):
                ax.bar([pos + offset * width for pos in positions], y_series[key], width=width, label=key)
        ax.set_xticks(positions)
        ax.set_xticklabels(x_values)

    def write_pending(self, tag, payload):
        artifact = self.next_artifact(f".{tag}.pending.yml")
        artifact.write_text(yaml.safe_dump({"backend": tag, "payload": payload}, sort_keys=False))
        self.record(tag, artifact, {"route": "pending", "reason": "backend scheduled for later packet"})
        return f"[{tag} artifact pending]({artifact.relative_to(self.report_dir).as_posix()})"

    def record(self, tag, artifact, metadata):
        self.manifest.append(
            {
                "tag": tag,
                "artifact": str(artifact),
                "metadata": metadata,
            }
        )

    def write_manifest(self):
        manifest_path = self.artifacts_dir / "manifest.json"
        manifest_path.write_text(json.dumps(self.manifest, indent=2))
        return manifest_path


def main():
    parser = argparse.ArgumentParser(description="Render Notebook media-tag Markdown into artifacts")
    parser.add_argument("input", help="Markdown source file containing fenced media tags")
    parser.add_argument("--report-name", help="Notebook report folder name")
    parser.add_argument("--output", help="Output markdown path; defaults to ~/Notebook/<report>/rendered.md")
    parser.add_argument("--a1111-url", default=DEFAULT_A1111_URL)
    parser.add_argument("--comfyui-url", default=DEFAULT_COMFYUI_URL)
    parser.add_argument("--skip-comfyui", action="store_true", help="Do not render comfyui tags; emit deferred placeholders instead")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if args.report_name:
        report_name = args.report_name
    else:
        parent = input_path.parent
        try:
            rel = parent.relative_to(NOTEBOOK_ROOT)
            report_name = rel.parts[0] if rel.parts else input_path.stem
        except ValueError:
            report_name = parent.name or input_path.stem
    renderer = NotebookRenderer(report_name, args.a1111_url, args.comfyui_url, skip_comfyui=args.skip_comfyui)
    renderer.prepare()

    rendered = renderer.render_markdown(input_path.read_text(), input_path.resolve().parent)
    output_path = Path(args.output) if args.output else renderer.report_dir / "rendered.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)
    manifest_path = renderer.write_manifest()

    print(json.dumps({"output": str(output_path), "manifest": str(manifest_path), "artifacts": renderer.manifest}, indent=2))


if __name__ == "__main__":
    main()
