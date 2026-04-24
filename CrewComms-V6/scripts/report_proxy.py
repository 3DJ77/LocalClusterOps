#!/usr/bin/env python3
"""Local report proxy.

OpenAI-compatible endpoint on 127.0.0.1:11437 that forwards to Ollama
(127.0.0.1:11434). On the first user turn of a conversation, scans the
user message for a local filesystem path; if found, runs notebook-extract
and prepends the briefing + CSV heads as a system message.

The authoring model sees a pre-loaded context and authors from it — no tool calls,
no MCP, no agent loops.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest

OLLAMA = "http://127.0.0.1:11434"
HOME_DIR = Path.home()
EXTRACT_BIN = os.environ.get("NOTEBOOK_EXTRACT_BIN", str(HOME_DIR / "bin" / "notebook-extract"))
NOTEBOOK_ROOT = Path(os.environ.get("NOTEBOOK_ROOT", str(HOME_DIR / "Notebook"))).expanduser()
GRAVEYARD_ROOT = Path(os.environ.get("REPORT_ARCHIVE_ROOT", str(HOME_DIR / "Generated-Archives"))).expanduser()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "notebook-agent-system.md"
PATH_RE = re.compile(r"((?:~|/)[^\s'\"`)\]]+)")
BRIEFING_MARKER = "PRE-LOADED BRIEFING (notebook-extract \u2192"
FORMAT_REMINDER_MARKER = "NOTEBOOK FORMAT REMINDER"
FENCE_RE = re.compile(r"```(comfyui|chart|laser|kicad|dxf|stl)\s*\n", re.IGNORECASE)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".svg"}
PERSISTENT_REPORT_CACHE_NAMES = {".compress-cache", ".vision-cache"}
SUPPORTED_CHART_TYPES = {"bar", "line", "scatter", "pie"}
MIN_COMFYUI_BLOCKS = 4
MIN_CHART_BLOCKS = 2
PLANNER_FALLBACK_MODELS = ["gemma4:e4b", "mistral-nemo:latest"]
PLANNER_HTTP_RETRIES = 3
HEARTBEAT_INTERVAL_SECONDS = 8
TERMINATION_REMINDER_INTERVAL_SECONDS = 300


def default_report_slug(source_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_name.strip().lower()).strip("-")
    return f"{cleaned or 'report'}-deepdive"


def resolve_extract_output_dir(folder: str) -> Path | None:
    src = Path(folder)
    if not src.is_dir():
        return None
    proc = subprocess.run(
        [EXTRACT_BIN, "--folder", str(src), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = re.search(r"^output:\s*(.+)$", proc.stdout, flags=re.MULTILINE)
    if match:
        return Path(match.group(1).strip())
    return NOTEBOOK_ROOT / default_report_slug(src.name)


def archive_previous_report_state(report_dir: Path) -> Path | None:
    if not report_dir.exists() or not report_dir.is_dir():
        return None
    items = [path for path in sorted(report_dir.iterdir()) if path.name not in PERSISTENT_REPORT_CACHE_NAMES]
    if not items:
        return None

    GRAVEYARD_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    archive_dir = GRAVEYARD_ROOT / report_dir.name / timestamp
    suffix = 1
    while archive_dir.exists():
        suffix += 1
        archive_dir = GRAVEYARD_ROOT / report_dir.name / f"{timestamp}-{suffix:02d}"
    archive_dir.mkdir(parents=True, exist_ok=False)

    for item in items:
        shutil.move(str(item), str(archive_dir / item.name))
    return archive_dir


def run_extract(folder: str) -> dict:
    src = Path(folder)
    if not src.is_dir():
        return {"error": f"not a directory: {folder}"}
    proc = subprocess.run(
        [EXTRACT_BIN, "--folder", str(src)],
        capture_output=True, text=True, timeout=1800,
    )
    m = re.search(rf"({re.escape(str(NOTEBOOK_ROOT))}/[^\s]+)", proc.stdout)
    out = Path(m.group(1)) if m else NOTEBOOK_ROOT / default_report_slug(src.name)
    briefing = out / "briefing.md"
    if not briefing.exists():
        return {
            "error": f"extract produced no briefing (exit={proc.returncode})",
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-10:]),
        }
    csvs = sorted((out / "data").glob("*.csv")) if (out / "data").is_dir() else []
    csv_section = ""
    for c in csvs:
        lines = c.read_text(errors="replace").splitlines()[:20]
        csv_section += f"\n\n### {c.name}\n```\n" + "\n".join(lines) + "\n```"
    return {
        "briefing": briefing.read_text(errors="replace"),
        "csvs": csv_section,
        "dir": str(out),
    }


def build_inject(ext: dict) -> str:
    if "error" in ext:
        return (
            f"[NOTEBOOK-EXTRACT FAILED: {ext['error']}]\n"
            f"Report the failure to the user and stop. Do not fabricate.\n"
            f"{ext.get('stderr_tail','')}"
        )
    return (
        f"## {BRIEFING_MARKER} (notebook-extract → {ext['dir']})\n\n"
        f"Author the report using ONLY the facts below. Use the current user's "
        f"real home directory when you need one. Do not invent usernames or "
        f"placeholder home paths. Do not claim to call "
        f"any file tools; everything you need is already in this system "
        f"message.\n\n"
        f"### briefing.md\n\n{ext['briefing']}\n\n"
        f"## CSV HEADS{ext['csvs']}"
    )


def build_format_reminder() -> str:
    return (
        f"## {FORMAT_REMINDER_MARKER}\n\n"
        "Write the final answer as a complete Markdown report.\n"
        "When the report needs generated media, emit fenced YAML blocks using "
        "only supported tags such as ```comfyui or ```chart.\n"
        "Do not emit Python code blocks, shell snippets, placeholder image URLs, "
        "or narration about tools you did not call.\n"
        "Charts must use ```chart with real CSV-backed columns. Images must use "
        "```comfyui with YAML keys like prompt, size, steps, and cfg.\n"
        "Return the report itself, not commentary about the pipeline.\n"
    )


def discover_real_images(source_folder: str) -> list[str]:
    folder = Path(source_folder)
    images: list[str] = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(str(path))
    return images[:24]


def parse_csv_heads(ext: dict) -> list[dict]:
    csvs: list[dict] = []
    for block in re.finditer(r"### ([^\n]+)\n```\n(.*?)\n```", ext.get("csvs", ""), re.DOTALL):
        filename = block.group(1).strip()
        preview = block.group(2).strip().splitlines()
        headers = preview[0].split(",") if preview else []
        csvs.append(
            {
                "file": f"data/{filename}",
                "headers": [header.strip() for header in headers if header.strip()],
                "preview_rows": preview[:4],
            }
        )
    return csvs


def build_plan_prompt(ext: dict, folder: str, user_request: str) -> tuple[str, str]:
    csvs = parse_csv_heads(ext)
    images = discover_real_images(folder)
    image_lines = "\n".join(f"- {path}" for path in images) if images else "- none found"
    csv_lines = "\n".join(
        f"- {entry['file']} | headers: {', '.join(entry['headers']) or 'none'}"
        for entry in csvs
    ) or "- none found"
    system = (
        "You are a report planner for the local Notebook pipeline.\n"
        "Return JSON only. Do not write Markdown. Do not wrap the JSON in code fences.\n"
        "Plan a rich report using only these block types: paragraph, bullet_list, real_image, generated_image, chart, warning.\n"
        "Use real_image when a discovered image directly documents the subject.\n"
        "Use chart only when the requested chart can be backed by the listed CSV files and exact headers.\n"
        "Use generated_image only for supportive illustration, never for factual charts.\n"
        "Never invent files, CSV headers, numbers, dimensions, or image paths.\n"
        "Return an object with keys: title, executive_summary, sections.\n"
        "Each section must have: heading, blocks.\n"
        "Each block must include a type field and the fields required by that type.\n"
    )
    user = (
        f"User request:\n{user_request}\n\n"
        f"Source folder:\n{folder}\n\n"
        f"Briefing:\n{ext.get('briefing', '')}\n\n"
        f"CSV inventory:\n{csv_lines}\n\n"
        f"Candidate real images:\n{image_lines}\n\n"
        "Requirements:\n"
        "- Prefer a concise but useful executive summary.\n"
        "- Include at least one real_image block if a candidate image is clearly relevant.\n"
        "- Include a chart block only if a listed CSV and exact headers support it.\n"
        "- Include generated_image blocks only when they add explanatory value.\n"
        "- If data is missing for a requested chart, use a warning block instead of inventing one.\n"
    )
    return system, user


def build_batch_instruction(ext: dict, folder: str, user_request: str) -> str:
    csvs = parse_csv_heads(ext)
    csv_lines = "\n".join(f"- {entry['file']} | headers: {', '.join(entry['headers'])}" for entry in csvs) or "- none found"
    images = discover_real_images(folder)
    image_lines = "\n".join(f"- {path}" for path in images[:8]) if images else "- none found"
    return (
        "Write a complete rich report from the extracted briefing packet.\n\n"
        "Output contract:\n"
        "- Markdown only. No preamble. No postscript.\n"
        "- Write the final report directly, not a plan.\n"
        "- Use fenced `comfyui` blocks for generated illustrations when helpful.\n"
        "- Use fenced `chart` blocks only when supported by the real CSV inventory below.\n"
        f"- Include at least {MIN_COMFYUI_BLOCKS} separate `comfyui` blocks.\n"
        f"- Include at least {MIN_CHART_BLOCKS} separate `chart` blocks when the listed CSV inventory supports them.\n"
        f"- Supported chart types are: {', '.join(sorted(SUPPORTED_CHART_TYPES))}.\n"
        "- Never fabricate chart data, labels, dimensions, or source facts.\n"
        "- If a useful chart is not supported by the CSV inventory, say so in prose instead of inventing one.\n"
        "- When candidate real images are clearly relevant, include standard markdown image references using their absolute paths.\n"
        "- Copy candidate real image paths exactly as listed. Do not change punctuation, directories, filenames, or characters.\n"
        "- Do not emit a real image markdown reference unless the exact file path appears in the candidate image list below.\n"
        "- Prefer 3 to 6 major sections for a deep report.\n\n"
        f"User request:\n{user_request}\n\n"
        f"Source folder:\n{folder}\n\n"
        f"Available CSV inventory:\n{csv_lines}\n\n"
        f"Candidate real images:\n{image_lines}\n"
    )


def extract_json_object(raw: str) -> dict:
    text = raw.strip()
    if not text:
        raise ValueError("planner output was empty")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text)
    if not isinstance(obj, dict):
        raise ValueError("planner output was not a JSON object")
    return obj


def detect_report_request(payload: dict) -> tuple[Path | None, str | None]:
    msgs = payload.get("messages", [])
    if not msgs or not first_user_turn(msgs):
        return None, None
    last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
    if not last_user:
        return None, None
    content = last_user.get("content") or ""
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    m = PATH_RE.search(content)
    if not m:
        return None, None
    folder = Path(m.group(1).rstrip("/.,;:)"))
    return folder, content


def first_user_turn(messages: list) -> bool:
    return sum(1 for m in messages if m.get("role") == "user") == 1


def validate_generated_markdown(markdown: str) -> list[str]:
    issues = []
    if "```python" in markdown:
        issues.append("contains ```python blocks instead of notebook media tags")
    if "via.placeholder.com" in markdown or "placeholder.com" in markdown:
        issues.append("contains placeholder image URLs")
    if "```chart" in markdown and "data:" not in markdown:
        issues.append("contains a chart fence without a data path")
    comfyui_count = len(re.findall(r"^```comfyui\s*$", markdown, flags=re.MULTILINE))
    chart_count = len(re.findall(r"^```chart\s*$", markdown, flags=re.MULTILINE))
    if comfyui_count < MIN_COMFYUI_BLOCKS:
        issues.append(f"contains only {comfyui_count} comfyui blocks; need at least {MIN_COMFYUI_BLOCKS}")
    if chart_count < MIN_CHART_BLOCKS:
        issues.append(f"contains only {chart_count} chart blocks; need at least {MIN_CHART_BLOCKS}")
    for match in re.finditer(r"```chart\s*\n(.*?)\n```", markdown, flags=re.DOTALL):
        body = match.group(1)
        type_match = re.search(r"^\s*type:\s*([A-Za-z0-9_-]+)\s*$", body, flags=re.MULTILINE)
        if not type_match:
            issues.append("contains a chart block without a type field")
            continue
        chart_type = type_match.group(1).strip().lower()
        if chart_type not in SUPPORTED_CHART_TYPES:
            issues.append(f"contains unsupported chart type: {chart_type}")
    for match in re.finditer(r"!\[[^\]]*\]\(((?:~|/)[^)\s]+)\)", markdown):
        image_path = Path(match.group(1)).expanduser()
        if not image_path.exists():
            issues.append(f"contains missing real image path: {image_path}")
    return issues


def build_repair_instruction(
    ext: dict,
    folder: str,
    user_request: str,
    draft: str,
    issues: list[str],
) -> str:
    base = build_batch_instruction(ext, folder, user_request)
    issue_lines = "\n".join(f"- {issue}" for issue in issues)
    return (
        base
        + "\nValidation failed for the previous draft. Rewrite the full report and fix every issue below.\n\n"
        + "Validation issues:\n"
        + issue_lines
        + "\n\nPrevious draft to repair:\n\n"
        + draft
    )


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + fmt % args + "\n")

    def _forward(self, method: str):
        body = b""
        if self.headers.get("Content-Length"):
            body = self.rfile.read(int(self.headers["Content-Length"]))

        folder_path = None
        request_text = None
        is_stream = False
        if method == "POST" and self.path.endswith("/chat/completions") and body:
            try:
                payload = json.loads(body)
                is_stream = payload.get("stream", False)
                folder_path, request_text = detect_report_request(payload)
                if folder_path and is_stream:
                    self._run_report_job(payload, folder_path, request_text or "")
                    return
                body = json.dumps(payload).encode()
            except Exception as e:
                sys.stderr.write(f"[proxy] inject error: {e}\n")

        url = OLLAMA + self.path
        req = urlrequest.Request(url, data=body or None, method=method)
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length"):
                continue
            req.add_header(k, v)
        if body:
            req.add_header("Content-Length", str(len(body)))

        try:
            resp = urlrequest.urlopen(req, timeout=3600)
        except Exception as e:
            self.send_error(502, f"upstream error: {e}")
            return

        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(k, v)
        self.end_headers()
        
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break

    def _planner_request_once(self, model: str, system_prompt: str, user_prompt: str, report_dir: Path) -> tuple[dict, str]:
        last_error: Exception | None = None
        for attempt in range(1, PLANNER_HTTP_RETRIES + 1):
            req = urlrequest.Request(
                f"{OLLAMA}/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlrequest.urlopen(req, timeout=3600) as resp:
                    raw_body = resp.read().decode("utf-8", errors="replace")
                (report_dir / f"planner-http-{model.replace('/', '_').replace(':', '_')}-attempt{attempt}.txt").write_text(
                    raw_body,
                    encoding="utf-8",
                )
                if not raw_body.strip():
                    raise ValueError("planner upstream returned empty HTTP body")
                data = json.loads(raw_body)
                content = data["choices"][0]["message"]["content"]
                return extract_json_object(content), content
            except Exception as e:
                last_error = e
                if attempt < PLANNER_HTTP_RETRIES:
                    time.sleep(2 * attempt)
                    continue
        assert last_error is not None
        raise last_error

    def _planner_request(self, model: str, system_prompt: str, user_prompt: str, report_dir: Path) -> tuple[dict, str]:
        attempts = [model] + [fallback for fallback in PLANNER_FALLBACK_MODELS if fallback != model]
        errors: list[str] = []
        for index, attempt_model in enumerate(attempts, start=1):
            try:
                plan, raw = self._planner_request_once(attempt_model, system_prompt, user_prompt, report_dir)
                (report_dir / f"planner-response-{index:02d}-{attempt_model.replace('/', '_').replace(':', '_')}.txt").write_text(
                    raw,
                    encoding="utf-8",
                )
                return plan, attempt_model
            except Exception as e:
                raw_text = ""
                if hasattr(e, "args") and e.args:
                    raw_text = str(e)
                (report_dir / f"planner-error-{index:02d}-{attempt_model.replace('/', '_').replace(':', '_')}.txt").write_text(
                    raw_text or repr(e),
                    encoding="utf-8",
                )
                errors.append(f"{attempt_model}: {e}")
        raise ValueError("planner failed across models: " + " | ".join(errors))

    def _batch_generate_markdown(self, model: str, ext: dict, folder: Path, request_text: str, report_dir: Path) -> str:
        system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8", errors="replace")
        instruction = build_batch_instruction(ext, str(folder), request_text)
        return self._generate_markdown_with_instruction(model, system, ext["briefing"], instruction, report_dir)

    def _repair_generated_markdown(
        self,
        model: str,
        ext: dict,
        folder: Path,
        request_text: str,
        report_dir: Path,
        draft: str,
        issues: list[str],
        attempt: int,
    ) -> str:
        system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8", errors="replace")
        instruction = build_repair_instruction(ext, str(folder), request_text, draft, issues)
        return self._generate_markdown_with_instruction(
            model,
            system,
            ext["briefing"],
            instruction,
            report_dir,
            suffix=f"-repair-{attempt:02d}",
        )

    def _generate_markdown_with_instruction(
        self,
        model: str,
        system: str,
        briefing: str,
        instruction: str,
        report_dir: Path,
        suffix: str = "",
    ) -> str:
        payload = {
            "model": model,
            "system": system,
            "prompt": briefing + "\n\n" + instruction,
            "stream": False,
            "keep_alive": 0,
            "options": {
                "num_ctx": 32768,
                "num_predict": 8192,
                "temperature": 0.45,
                "top_p": 0.9,
            },
        }
        req = urlrequest.Request(
            f"{OLLAMA}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=7200) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        json_name = f"source.md{suffix}.json" if suffix else "source.md.json"
        (report_dir / json_name).write_text(raw, encoding="utf-8")
        data = json.loads(raw)
        response = data.get("response", "").strip()
        if response.startswith("```markdown") and response.endswith("```"):
            response = response[len("```markdown"):].strip()
            response = response[:-3].strip()
        elif response.startswith("```") and response.endswith("```"):
            response = response[3:-3].strip()
        if not response:
            raise ValueError("batch generation returned an empty response")
        return response + "\n"

    def _append_status(self, status_path: Path, text: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with status_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {text}\n")

    def _status_path(self, folder_path: Path) -> Path:
        return folder_path / "report-status.log"

    def _heartbeat_worker(self, stop_event: threading.Event, status_path: Path):
        started_at = time.monotonic()
        last_termination_reminder = started_at
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            message = f"Still working. Status log: `{status_path}`"
            now = time.monotonic()
            if now - last_termination_reminder >= TERMINATION_REMINDER_INTERVAL_SECONDS:
                message += " If the user wants to terminate this run, ask once now; otherwise keep it going."
                last_termination_reminder = now
            self._append_status(status_path, "heartbeat: planner/render still running")
            try:
                self._send_sse_chunk(message + "\n")
            except Exception:
                break

    def _run_report_job(self, payload: dict, folder_path: Path, request_text: str):
        stop_event = threading.Event()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            model = payload.get("model", "gemma4:26b")
            self._send_sse_chunk("Starting report job...\n")
            planned_report_dir = resolve_extract_output_dir(str(folder_path))
            if planned_report_dir is not None:
                archived_dir = archive_previous_report_state(planned_report_dir)
                if archived_dir is not None:
                    self._send_sse_chunk(
                        f"Archived previous report state to `{archived_dir}` before starting this run.\n"
                    )
            sys.stderr.write(f"[proxy] extracting {folder_path}\n")
            ext = run_extract(str(folder_path))
            if "error" in ext:
                self._send_sse_chunk(f"❌ Extraction failed: {ext['error']}\n{ext.get('stderr_tail', '')}\n")
                self._send_final_sse_chunk("stop")
                self._finish_sse()
                return

            report_dir = Path(ext["dir"])
            status_path = self._status_path(report_dir)
            self._append_status(status_path, f"job started for {folder_path}")
            self._send_sse_chunk(f"Extracted source to `{report_dir}`.\n")
            self._send_sse_chunk(f"Status log: `{status_path}`\n")
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker,
                args=(stop_event, status_path),
                daemon=True,
            )
            heartbeat_thread.start()
            self._append_status(status_path, f"starting batch markdown generation with model {model}")
            self._send_sse_chunk(f"Generating source markdown with `{model}`...\n")
            markdown = self._batch_generate_markdown(model, ext, folder_path, request_text, report_dir)
            validation_issues = validate_generated_markdown(markdown)
            for attempt in range(1, 3):
                if not validation_issues:
                    break
                self._append_status(
                    status_path,
                    f"validation failed on draft {attempt}: {'; '.join(validation_issues)}",
                )
                self._send_sse_chunk(
                    f"Validation failed on draft {attempt}; retrying with stricter repair guidance...\n"
                )
                markdown = self._repair_generated_markdown(
                    model,
                    ext,
                    folder_path,
                    request_text,
                    report_dir,
                    markdown,
                    validation_issues,
                    attempt,
                )
                validation_issues = validate_generated_markdown(markdown)

            source_md = report_dir / "source.md"
            source_md.write_text(markdown, encoding="utf-8")
            self._append_status(status_path, f"source markdown compiled: {source_md}")
            if validation_issues:
                raise ValueError("; ".join(validation_issues))

            report_name = report_dir.name
            html_path = report_dir / f"{report_name}.html"
            pdf_path = report_dir / f"{report_name}.pdf"
            publish_log = report_dir / "publish.log"
            comfyui_count = len(re.findall(r"^```comfyui\s*$", markdown, flags=re.MULTILINE))
            self._send_sse_chunk(
                "Publishing final report after all rendering completes...\n"
                f"- Source: `{source_md}`\n"
                f"- Status log: `{status_path}`\n"
                f"- Publish log: `{publish_log}`\n"
                f"- HTML: `{html_path}`\n"
                f"- PDF: `{pdf_path}`\n"
            )
            if comfyui_count:
                self._append_status(
                    status_path,
                    f"starting final publish with {comfyui_count} comfyui block(s); waiting for image generation to finish",
                )
                self._send_sse_chunk(
                    f"Waiting for {comfyui_count} generated image block(s) to finish before completing the report. "
                    "This can take minutes to hours when many images are requested.\n"
                )
            else:
                self._append_status(status_path, "starting final publish")
            publish_returncode = self._run_publish(source_md, report_dir, skip_comfyui=False, log_name="publish.log")
            if publish_returncode != 0:
                raise RuntimeError(f"publish failed with exit {publish_returncode}; see {publish_log}")
            self._append_status(status_path, "final publish completed")
            stop_event.set()
            completion_lines = [
                "✅ Report publish complete.",
                f"- Status log: `{status_path}`",
                f"- Publish log: `{publish_log}`",
            ]
            if html_path.exists():
                completion_lines.append(f"- HTML: `{html_path}`")
            if pdf_path.exists():
                completion_lines.append(f"- PDF: `{pdf_path}`")
            else:
                completion_lines.append("- PDF: not generated in this pass")
            self._send_sse_chunk("\n".join(completion_lines) + "\n")
            self._send_final_sse_chunk("stop")
            self._finish_sse()
        except Exception as e:
            sys.stderr.write(f"[proxy] report job error: {e}\n")
            try:
                status_path = self._status_path(Path(ext["dir"])) if "ext" in locals() and "dir" in ext else None
                if status_path:
                    self._append_status(status_path, f"error: {e}")
            except Exception:
                pass
            stop_event.set()
            try:
                self._send_sse_chunk(f"❌ Report job failed: {e}\n")
                self._send_final_sse_chunk("stop")
                self._finish_sse()
            except Exception:
                pass
        finally:
            stop_event.set()

    def _send_sse_chunk(self, text: str):
        chunk = {
            "id": "chatcmpl-proxy",
            "object": "chat.completion.chunk",
            "model": "orchestrator",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]
        }
        data = f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
        self.wfile.write(data)
        self.wfile.flush()

    def _send_final_sse_chunk(self, finish_reason: str = "stop"):
        chunk = {
            "id": "chatcmpl-proxy",
            "object": "chat.completion.chunk",
            "model": "orchestrator",
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
        }
        data = f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
        self.wfile.write(data)
        self.wfile.flush()

    def _finish_sse(self):
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _run_publish(self, source_md: Path, folder_path: Path, *, skip_comfyui: bool = False, log_name: str = "publish.log"):
        """Run notebook-publish and return its exit code."""
        publish_bin = os.environ.get("NOTEBOOK_PUBLISH_BIN", str(HOME_DIR / "bin" / "notebook-publish"))
        log_path = folder_path / log_name
        cmd = [publish_bin, str(source_md), "--no-open"]
        if skip_comfyui:
            cmd.append("--skip-comfyui")
        phase = "fast" if skip_comfyui else "full"
        status_path = self._status_path(folder_path)
        sys.stderr.write(f"[proxy] publish starting ({phase}): {source_md}\n")
        try:
            self._append_status(status_path, f"publish phase started: {phase}")
            with open(log_path, "w") as lf:
                proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
            if proc.returncode == 0:
                sys.stderr.write(f"[proxy] publish done ({phase}): {folder_path.name}\n")
                self._append_status(status_path, f"publish phase completed: {phase}")
            else:
                sys.stderr.write(f"[proxy] publish exit={proc.returncode} ({phase}): {folder_path.name}\n")
                self._append_status(
                    status_path,
                    f"publish phase failed ({phase}) with exit {proc.returncode}; see {log_path}",
                )
            return proc.returncode
        except Exception as e:
            sys.stderr.write(f"[proxy] publish error ({phase}): {e}\n")
            self._append_status(status_path, f"publish phase error ({phase}): {e}")
            raise

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 11437), Proxy)
    sys.stderr.write("[proxy] listening on 127.0.0.1:11437 -> upstream 11434\n")
    srv.serve_forever()
