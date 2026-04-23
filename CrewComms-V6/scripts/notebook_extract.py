#!/usr/bin/env python3
"""Deterministic Notebook source extractor.

Reads configs/extract/<name>.yml and writes:
    /home/jay/Notebook/<report_slug>/briefing.md
    /home/jay/Notebook/<report_slug>/data/*.csv
    /home/jay/Notebook/<report_slug>/extract.log
"""

import argparse
import base64
import binascii
import csv
import hashlib
import json
import logging
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import yaml
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "configs" / "extract"
NOTEBOOK_ROOT = Path("/home/jay/Notebook")
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
GENERIC_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".pdf", ".odt", ".docx", ".rtf"}
GENERIC_DENYLIST_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
GENERIC_TEXT_CAP = 500 * 1024
GENERIC_MISC_FILE_CAP = 8000
DEFAULT_COMPRESS_SYSTEM_PROMPT = """You are a technical compression agent. Produce a concise summary of the
input document that preserves: named projects, stated decisions, TODO
items, technical constraints, quoted figures, and open questions. Drop:
pleasantries, speculation, marketing prose, repetition across sections.
Output plain prose. Never invent facts that are not in the source."""
DEFAULT_COMPRESS_MODEL = "gemma4:26b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_COMPRESS_TARGET_TOKENS = 6000
DEFAULT_COMPRESS_TIMEOUT_SECONDS = 600
DEFAULT_BULK_VISION_MODEL = "moondream:1.8b"
DEFAULT_DEEP_VISION_MODEL = "granite3.2-vision:2b"
DEFAULT_BULK_VISION_PROMPT = """Describe the image in 1-3 sentences. Identify what it depicts
functionally (photo, diagram, schematic, screenshot, chart) and
note any visible labels, text, or named components. Do not
speculate beyond what is visible. Never invent facts."""
DEFAULT_DEEP_VISION_PROMPT = """Describe this technical drawing in detail. Identify: drawing type
(schematic, mechanical print, PCB, blueprint), visible components
and their labels, dimensions and callouts if present, net labels
and connections if schematic, scale and orientation. Do not guess
at components whose labels you cannot read - say "unreadable label
at <location>" instead. Never invent."""
DEFAULT_VISION_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_VISION_MAX_PER_SOURCE = 50
DEFAULT_VISION_MAX_BYTES = 8_000_000
DEFAULT_VISION_TIMEOUT_SECONDS = 120


class ImageDescriber(Protocol):
    def describe(self, image_path: Path) -> str: ...


@dataclass(frozen=True)
class CompressConfig:
    model: str = DEFAULT_COMPRESS_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    target_tokens: int = DEFAULT_COMPRESS_TARGET_TOKENS
    system_prompt: str = DEFAULT_COMPRESS_SYSTEM_PROMPT
    timeout_seconds: int = DEFAULT_COMPRESS_TIMEOUT_SECONDS


@dataclass
class CompressionStats:
    attempted_files: int = 0
    cache_hits: int = 0
    fallbacks: int = 0


@dataclass(frozen=True)
class VisionTierConfig:
    tier: str
    model: str
    system_prompt: str


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool = False
    mode: str = "bulk"
    ollama_url: str = DEFAULT_OLLAMA_URL
    bulk: VisionTierConfig = VisionTierConfig("bulk", DEFAULT_BULK_VISION_MODEL, DEFAULT_BULK_VISION_PROMPT)
    deep: VisionTierConfig = VisionTierConfig("deep", DEFAULT_DEEP_VISION_MODEL, DEFAULT_DEEP_VISION_PROMPT)
    extensions: frozenset[str] = frozenset(DEFAULT_VISION_EXTENSIONS)
    max_per_source: int = DEFAULT_VISION_MAX_PER_SOURCE
    max_bytes_per_image: int = DEFAULT_VISION_MAX_BYTES
    timeout_seconds: int = DEFAULT_VISION_TIMEOUT_SECONDS


@dataclass
class VisionStats:
    attempted_images: int = 0
    cache_hits: int = 0
    described_images: int = 0
    skipped_images: int = 0
    failed_images: int = 0
    fallback_count: int = 0
    bulk_images: int = 0
    deep_images: int = 0


@dataclass
class ImageRecord:
    path: Path
    rel_path: Path
    group: str
    tier: str
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0
    description: str = ""


@dataclass
class Source:
    name: str
    path: Path
    glob: str | None = None
    convert: str | None = None
    compress: CompressConfig | None = None
    vision: str | None = None


@dataclass
class GenericFile:
    path: Path
    rel_path: Path
    extension: str
    subdir: str
    mtime_month: str
    bucket: str


def setup_logging(report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "extract.log"
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[file_handler, stream_handler],
        force=True,
    )


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("extract config must be a YAML mapping")
    return data


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value).strip().lower()).strip("-")
    return cleaned or "report"


def resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def brace_patterns(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", pattern)
    if not match:
        return [pattern]
    choices = [choice.strip() for choice in match.group(1).split(",") if choice.strip()]
    return [
        pattern[: match.start()] + choice + pattern[match.end() :]
        for choice in choices
    ]


def source_files(source: Source) -> list[Path]:
    if source.path.is_file():
        return [source.path]
    if not source.path.is_dir():
        logging.warning("source path missing: %s", source.path)
        return []
    patterns = brace_patterns(source.glob or "*")
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(source.path.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def command_text(cmd: list[str]) -> str:
    logging.info("convert command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logging.warning("conversion failed (%s): %s", result.returncode, result.stderr.strip())
        return ""
    return result.stdout


def convert_to_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".html", ".htm"}:
        return read_text(path)
    if suffix == ".pdf":
        if not shutil.which("pdftotext"):
            logging.warning("pdftotext unavailable for %s", path)
            return ""
        return command_text(["pdftotext", "-layout", str(path), "-"])
    if suffix in {".odt", ".docx", ".rtf"}:
        if not shutil.which("pandoc"):
            logging.warning("pandoc unavailable for %s", path)
            return ""
        return command_text(["pandoc", str(path), "-t", "plain"])
    logging.warning("no text conversion rule for %s", path)
    return ""


def normalize_compress_config(value: object, defaults: CompressConfig | None = None) -> CompressConfig | None:
    if value in (None, False):
        return None
    base = defaults or CompressConfig()
    if value is True:
        config = base
    elif isinstance(value, dict):
        config = replace(
            base,
            model=str(value.get("model", base.model)),
            ollama_url=str(value.get("ollama_url", base.ollama_url)),
            target_tokens=int(value.get("target_tokens", base.target_tokens)),
            system_prompt=str(value.get("system_prompt", base.system_prompt)),
            timeout_seconds=int(value.get("timeout_seconds", base.timeout_seconds)),
        )
    else:
        raise ValueError("compress must be true, false, or a mapping")
    env_ollama_url = os_environ("OLLAMA_URL")
    if env_ollama_url:
        config = replace(config, ollama_url=env_ollama_url)
    return config


def os_environ(name: str) -> str | None:
    import os

    return os.environ.get(name)


def top_level_compress_defaults(config: dict) -> CompressConfig | None:
    value = config.get("compress")
    if isinstance(value, dict):
        return normalize_compress_config(value, CompressConfig())
    return None


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, source_path: Path, text: str, chunk_index: int, config: CompressConfig) -> Path:
    payload = {
        "path": str(source_path),
        "content_hash": content_hash(text),
        "chunk_index": chunk_index,
        "model": config.model,
        "target_tokens": config.target_tokens,
        "system_prompt_hash": prompt_hash(config.system_prompt),
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.txt"


def chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + max_chars])
        start += max_chars
    return chunks


def ollama_generate(prompt: str, config: CompressConfig) -> str:
    url = config.ollama_url.rstrip("/") + "/api/generate"
    prompt_token_estimate = max(1, len(prompt) // 4)
    num_ctx = max(2048, min(32768, prompt_token_estimate + config.target_tokens + 1024))
    payload = {
        "model": config.model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"ollama returned HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))
    output = data.get("response")
    if not isinstance(output, str):
        raise RuntimeError("ollama response missing text response")
    return output.strip()


def compress_text(
    path: Path,
    text: str,
    config: CompressConfig | None,
    cache_dir: Path,
    stats: CompressionStats,
) -> str:
    if config is None or not text.strip():
        return text
    stats.attempted_files += 1
    started = time.monotonic()
    max_input_chars = max(1, config.target_tokens * 4)
    outputs: list[str] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, chunk in enumerate(chunk_text(text, max_input_chars)):
            item_cache_path = cache_path(cache_dir, path, chunk, index, config)
            if item_cache_path.is_file():
                outputs.append(item_cache_path.read_text(encoding="utf-8"))
                stats.cache_hits += 1
                logging.info("compress cache hit: %s chunk=%s chars=%s", path, index, len(chunk))
                continue
            prompt = f"{config.system_prompt.strip()}\n\nInput document:\n{chunk.strip()}"
            compressed = ollama_generate(prompt, config)
            item_cache_path.write_text(compressed.rstrip() + "\n", encoding="utf-8")
            outputs.append(compressed)
            logging.info(
                "compress call: %s chunk=%s input_chars=%s output_chars=%s",
                path,
                index,
                len(chunk),
                len(compressed),
            )
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
        stats.fallbacks += 1
        logging.warning("compression failed for %s: %s; falling back to raw text", path, exc)
        return text
    elapsed = time.monotonic() - started
    output = "\n\n".join(item.strip() for item in outputs if item.strip())
    logging.info(
        "compressed file: %s wall_seconds=%.2f input_chars=%s output_chars=%s chunks=%s",
        path,
        elapsed,
        len(text),
        len(output),
        len(outputs),
    )
    return output or text


def normalize_tier(value: object, default: str = "bulk") -> str:
    tier = str(value or default).strip().lower()
    if tier not in {"bulk", "deep"}:
        raise ValueError(f"unsupported vision tier: {tier}")
    return tier


def normalize_extensions(values: object) -> frozenset[str]:
    if values is None:
        return frozenset(DEFAULT_VISION_EXTENSIONS)
    if not isinstance(values, list):
        raise ValueError("vision extensions must be a list")
    return frozenset(str(item).lower() if str(item).startswith(".") else f".{str(item).lower()}" for item in values)


def normalize_vision_config(value: object, *, enabled_override: bool | None = None, deep: bool = False, model: str | None = None) -> VisionConfig:
    if value in (None, False):
        enabled = bool(enabled_override)
        mode = "deep" if deep else "bulk"
        bulk = VisionTierConfig("bulk", model or DEFAULT_BULK_VISION_MODEL, DEFAULT_BULK_VISION_PROMPT)
        deep_tier = VisionTierConfig("deep", model or DEFAULT_DEEP_VISION_MODEL, DEFAULT_DEEP_VISION_PROMPT)
        config = VisionConfig(enabled=enabled, mode=mode, bulk=bulk, deep=deep_tier)
    elif isinstance(value, dict):
        enabled = bool(value.get("enabled", False))
        if enabled_override is not None:
            enabled = enabled_override
        mode = normalize_tier(value.get("mode"), "deep" if deep else "bulk")
        if deep:
            mode = "deep"
        bulk_value = value.get("bulk") or {}
        deep_value = value.get("deep") or {}
        if not isinstance(bulk_value, dict) or not isinstance(deep_value, dict):
            raise ValueError("vision bulk/deep blocks must be mappings")
        bulk = VisionTierConfig(
            "bulk",
            model or str(bulk_value.get("model", DEFAULT_BULK_VISION_MODEL)),
            str(bulk_value.get("system_prompt", DEFAULT_BULK_VISION_PROMPT)),
        )
        deep_tier = VisionTierConfig(
            "deep",
            model or str(deep_value.get("model", DEFAULT_DEEP_VISION_MODEL)),
            str(deep_value.get("system_prompt", DEFAULT_DEEP_VISION_PROMPT)),
        )
        config = VisionConfig(
            enabled=enabled,
            mode=mode,
            ollama_url=str(value.get("ollama_url", DEFAULT_OLLAMA_URL)),
            bulk=bulk,
            deep=deep_tier,
            extensions=normalize_extensions(value.get("extensions")),
            max_per_source=int(value.get("max_per_source", DEFAULT_VISION_MAX_PER_SOURCE)),
            max_bytes_per_image=int(value.get("max_bytes_per_image", DEFAULT_VISION_MAX_BYTES)),
            timeout_seconds=int(value.get("timeout_seconds", DEFAULT_VISION_TIMEOUT_SECONDS)),
        )
    else:
        raise ValueError("vision must be false or a mapping")
    env_ollama_url = os_environ("OLLAMA_URL")
    if env_ollama_url:
        config = replace(config, ollama_url=env_ollama_url)
    return config


def vision_tier(config: VisionConfig, tier: str) -> VisionTierConfig:
    return config.deep if tier == "deep" else config.bulk


def ollama_available_models(ollama_url: str, timeout_seconds: int = 5) -> set[str]:
    url = ollama_url.rstrip("/") + "/api/tags"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"ollama returned HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))
    models = data.get("models")
    if not isinstance(models, list):
        raise RuntimeError("ollama tags response missing models list")
    names = set()
    for item in models:
        if isinstance(item, dict):
            if isinstance(item.get("name"), str):
                names.add(item["name"])
            if isinstance(item.get("model"), str):
                names.add(item["model"])
    return names


def image_cache_path(cache_dir: Path, image_bytes: bytes, tier: VisionTierConfig) -> Path:
    payload = {
        "image_hash": hashlib.sha256(image_bytes).hexdigest(),
        "model": tier.model,
        "system_prompt_hash": prompt_hash(tier.system_prompt),
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.txt"


class OllamaImageDescriber:
    def __init__(self, config: VisionConfig, tier: VisionTierConfig):
        self.config = config
        self.tier = tier

    def describe(self, image_path: Path) -> str:
        image_bytes = image_path.read_bytes()
        payload = {
            "model": self.tier.model,
            "prompt": "Describe this image.",
            "system": self.tier.system_prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
            "options": {"num_ctx": 4096 if self.tier.tier == "bulk" else 8192},
        }
        request = urllib.request.Request(
            self.config.ollama_url.rstrip("/") + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"ollama returned HTTP {response.status}")
            data = json.loads(response.read().decode("utf-8"))
        output = data.get("response")
        if not isinstance(output, str):
            raise RuntimeError("ollama response missing text response")
        return output.strip()


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        segment_length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 > len(data):
                return None
            height = struct.unpack(">H", data[index + 3 : index + 5])[0]
            width = struct.unpack(">H", data[index + 5 : index + 7])[0]
            return width, height
        index += segment_length
    return None


def webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        data = path.read_bytes()[:512 * 1024]
    except OSError:
        return None, None
    dimensions = png_dimensions(data) or jpeg_dimensions(data) or webp_dimensions(data)
    if dimensions is None:
        return None, None
    return dimensions


def plain_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def first_h1_section(source: Source) -> str:
    files = source_files(source)
    if not files:
        return "(no data)"
    path = files[0]
    raw = read_text(path)
    if path.suffix.lower() in {".html", ".htm"}:
        soup = BeautifulSoup(raw, "html.parser")
        h1 = soup.find("h1")
        text = plain_html_text(raw)
        if h1:
            h1_text = h1.get_text(" ", strip=True)
            start = text.find(h1_text)
            if start >= 0:
                text = text[start:]
        return text[:8000].strip() or "(no data)"
    text = convert_to_text(path)
    match = re.search(r"^#\s+(.+?)(?=^#\s+|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return (match.group(0).strip() if match else text[:8000].strip()) or "(no data)"


def included_docs(source: Source, includes: list[str], cache_dir: Path, stats: CompressionStats) -> str:
    chunks: list[str] = []
    for item in includes:
        path = source.path / item if source.path.is_dir() else source.path
        if not path.is_file():
            logging.warning("include missing: %s", path)
            continue
        text = convert_to_text(path).strip()
        text = compress_text(path, text, source.compress, cache_dir, stats).strip()
        if text:
            chunks.append(f"### {path.name}\n\n{text}")
    return "\n\n".join(chunks) if chunks else "(no data)"


def source_excerpt(source: Source, cache_dir: Path, stats: CompressionStats, limit_chars: int | None = None) -> str:
    chunks: list[str] = []
    remaining = limit_chars
    for path in source_files(source):
        text = convert_to_text(path).strip()
        text = compress_text(path, text, source.compress, cache_dir, stats).strip()
        if not text:
            continue
        header = f"### {path.name}\n\n"
        body = text
        if remaining is not None:
            budget = max(0, remaining - len(header))
            if budget <= 0:
                break
            body = body[:budget].rstrip()
            remaining -= len(header) + len(body)
        chunks.append(header + body)
        if remaining is not None and remaining <= 0:
            break
    return "\n\n".join(chunks) if chunks else "(no data)"


def parse_html_todos(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        logging.warning("todo source missing: %s", path)
        return []
    soup = BeautifulSoup(read_text(path), "html.parser")
    rows: list[dict[str, str]] = []
    for group in soup.select(".todo-group"):
        title_el = group.select_one(".todo-group-title span")
        progress_el = group.select_one(".todo-progress")
        category = title_el.get_text(" ", strip=True) if title_el else ""
        progress = progress_el.get_text(" ", strip=True) if progress_el else ""
        for item in group.select(".todo-item"):
            label = item.select_one("label")
            checkbox = item.select_one('input[type="checkbox"]')
            priority = item.select_one(".todo-priority")
            done = "done" in item.get("class", []) or bool(checkbox and checkbox.has_attr("checked"))
            status = "done" if done else "pending"
            rows.append(
                {
                    "source": str(path),
                    "category": category,
                    "group_progress": progress,
                    "status": status,
                    "priority": priority.get_text(" ", strip=True) if priority else "",
                    "item": label.get_text(" ", strip=True) if label else "",
                }
            )
    return rows


def todo_group_markdown(source: Source) -> str:
    files = source_files(source)
    if not files:
        return "(no data)"
    rows = parse_html_todos(files[0])
    if not rows:
        return "(no data)"
    by_category: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)
    lines = [f"Total TODO rows extracted: {len(rows)}"]
    for category, category_rows in by_category.items():
        lines.append(f"\n### {category}")
        for row in category_rows:
            lines.append(f"- [{row['status']}] {row['item']} ({row['priority']})")
    return "\n".join(lines)


def apply_columns(rows: list[dict[str, object]], columns: list[str]) -> list[dict[str, object]]:
    return [{column: row.get(column, "") for column in columns} for row in rows]


def csv_directory_counts(spec: dict) -> list[dict[str, object]]:
    rows = []
    roots = spec.get("roots") or {}
    if not isinstance(roots, dict):
        raise ValueError("directory_counts roots must be a mapping")
    for category, raw_path in roots.items():
        path = Path(str(raw_path)).expanduser()
        count = sum(1 for child in path.iterdir() if child.is_file()) if path.is_dir() else 0
        if path.is_dir():
            rows.append({"category": category, "file_count": count})
        else:
            logging.warning("directory_counts root missing: %s", path)
    return rows


def csv_html_todo_parse(spec: dict, sources: dict[str, Source]) -> list[dict[str, object]]:
    source_name = spec.get("source")
    if source_name not in sources:
        raise ValueError(f"unknown todo source: {source_name}")
    files = source_files(sources[source_name])
    rows = parse_html_todos(files[0]) if files else []
    group_by = spec.get("group_by")
    if group_by == "status":
        counts = Counter(row["status"] for row in rows)
        return [{"status": status, "count": counts.get(status, 0)} for status in ["done", "in-progress", "pending"]]
    if group_by == "category":
        counts = Counter(row["category"] for row in rows)
        ordered = []
        seen = set()
        for row in rows:
            category = row["category"]
            if category not in seen:
                seen.add(category)
                ordered.append({"category": category, "count": counts[category]})
        return ordered
    if group_by in {None, "raw"}:
        return rows
    raise ValueError(f"unsupported html_todo_parse group_by: {group_by}")


def csv_markdown_section_counts(spec: dict, sources: dict[str, Source]) -> list[dict[str, object]]:
    source_name = spec.get("source")
    if source_name not in sources:
        raise ValueError(f"unknown markdown source: {source_name}")
    heading_re = re.compile(str(spec.get("heading_pattern", r"^#+\s+")), re.MULTILINE)
    rows = []
    for path in source_files(sources[source_name]):
        text = convert_to_text(path)
        rows.append({"file": path.name, "section_count": len(heading_re.findall(text))})
    return rows


def deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if key in {"sources", "csvs"} and isinstance(value, list):
            merged[key] = list(merged.get(key, [])) + value
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def first_subdir(rel_path: Path) -> str:
    parts = rel_path.parts
    return parts[0] if len(parts) > 1 else "(root)"


def generic_bucket(rel_path: Path, extension: str) -> str:
    if len(rel_path.parts) == 1 and extension in {".md", ".txt"}:
        return "overview"
    if extension in {".md", ".txt", ".html", ".htm"} and len(rel_path.parts) > 1:
        return "subproject"
    return "misc"


def walk_generic_folder(folder: Path) -> tuple[list[GenericFile], list[dict[str, str]]]:
    files: list[GenericFile] = []
    skipped: list[dict[str, str]] = []
    for current, dirnames, filenames in os_walk_sorted(folder):
        kept_dirs = []
        for dirname in dirnames:
            path = current / dirname
            if dirname.startswith(".") or dirname in GENERIC_DENYLIST_DIRS:
                for skipped_file in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
                    skipped.append({"path": str(skipped_file), "reason": "denylist directory"})
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            path = current / filename
            rel_path = path.relative_to(folder)
            extension = path.suffix.lower() or "(none)"
            if path.name.startswith("."):
                skipped.append({"path": str(path), "reason": "hidden file"})
                continue
            if extension not in GENERIC_EXTENSIONS:
                skipped.append({"path": str(path), "reason": f"unsupported extension {extension}"})
                continue
            stat = path.stat()
            month = time_month(stat.st_mtime)
            files.append(
                GenericFile(
                    path=path,
                    rel_path=rel_path,
                    extension=extension,
                    subdir=first_subdir(rel_path),
                    mtime_month=month,
                    bucket=generic_bucket(rel_path, extension),
                )
            )
    files.sort(key=lambda item: item.rel_path.as_posix())
    return files, skipped


def os_walk_sorted(folder: Path):
    import os

    for current, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        filenames.sort()
        yield Path(current), dirnames, filenames


def prune_walk_dirs(current: Path, dirnames: list[str], skipped: list[dict[str, str]]) -> None:
    kept_dirs = []
    for dirname in dirnames:
        path = current / dirname
        if dirname.startswith(".") or dirname in GENERIC_DENYLIST_DIRS:
            for skipped_file in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
                skipped.append({"path": str(skipped_file), "reason": "denylist directory"})
            continue
        kept_dirs.append(dirname)
    dirnames[:] = kept_dirs


def collect_images_from_root(
    root: Path,
    base: Path,
    config: VisionConfig,
    tier: str,
    skipped: list[dict[str, str]],
    group_name: str | None = None,
) -> list[ImageRecord]:
    candidates: list[Path] = []
    if root.is_file():
        candidates = [root] if root.suffix.lower() in config.extensions else []
    elif root.is_dir():
        for current, dirnames, filenames in os_walk_sorted(root):
            prune_walk_dirs(current, dirnames, skipped)
            for filename in filenames:
                path = current / filename
                if path.name.startswith("."):
                    skipped.append({"path": str(path), "reason": "hidden file"})
                    continue
                if path.suffix.lower() in config.extensions:
                    candidates.append(path)
    else:
        logging.warning("vision source missing: %s", root)
        return []

    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    if len(candidates) > config.max_per_source:
        for path in candidates[config.max_per_source :]:
            skipped.append({"path": str(path), "reason": f"vision max_per_source cap {config.max_per_source}"})
        candidates = candidates[: config.max_per_source]

    records: list[ImageRecord] = []
    for path in candidates:
        try:
            stat = path.stat()
        except OSError as exc:
            skipped.append({"path": str(path), "reason": f"vision stat failed: {exc}"})
            continue
        if stat.st_size > config.max_bytes_per_image:
            skipped.append({"path": str(path), "reason": f"vision image over {config.max_bytes_per_image} bytes"})
            continue
        try:
            rel_path = path.relative_to(base)
        except ValueError:
            rel_path = Path(path.name)
        group = group_name or ("Overview" if len(rel_path.parts) == 1 else rel_path.parts[0])
        width, height = image_dimensions(path)
        records.append(
            ImageRecord(
                path=path,
                rel_path=rel_path,
                group=group,
                tier=tier,
                width=width,
                height=height,
                size_bytes=stat.st_size,
            )
        )
    return records


def collect_generic_images(folder: Path, config: VisionConfig, skipped: list[dict[str, str]]) -> list[ImageRecord]:
    return collect_images_from_root(folder, folder, config, config.mode, skipped)


def collect_named_images(sources: dict[str, Source], config: VisionConfig, skipped: list[dict[str, str]]) -> list[ImageRecord]:
    records: list[ImageRecord] = []
    for source in sources.values():
        if source.vision in ("false", "False", "off", "none"):
            continue
        tier = normalize_tier(source.vision, config.mode)
        records.extend(collect_images_from_root(source.path, source.path if source.path.is_dir() else source.path.parent, config, tier, skipped, source.name))
    return records


def time_month(timestamp: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m")


def cap_text(path: Path, text: str, cap: int, skipped: list[dict[str, str]]) -> str:
    if len(text) <= cap:
        return text
    skipped.append({"path": str(path), "reason": f"extracted text truncated at {cap} chars"})
    return text[:cap].rstrip() + "\n\n[...truncated]"


def generic_file_text(item: GenericFile, skipped: list[dict[str, str]]) -> str:
    text = convert_to_text(item.path)
    if item.extension in {".html", ".htm"}:
        text = plain_html_text(text)
    return cap_text(item.path, text.strip(), GENERIC_TEXT_CAP, skipped)


def append_with_total_cap(
    lines: list[str],
    included_chars: int,
    header: str,
    body: str,
    max_chars: int,
) -> tuple[int, bool]:
    block = f"{header}\n\n{body.strip()}\n"
    if included_chars + len(block) <= max_chars:
        lines.extend([header, "", body.strip(), ""])
        return included_chars + len(block), True
    if included_chars >= max_chars:
        lines.extend([header, "", f"(listed only; total briefing cap of {max_chars} chars reached)", ""])
        return included_chars, False
    remaining = max_chars - included_chars
    reserve = len(header) + 24
    body_budget = max(0, remaining - reserve)
    clipped = body.strip()[:body_budget].rstrip()
    if clipped:
        clipped += "\n\n[...truncated]"
    else:
        clipped = f"(listed only; total briefing cap of {max_chars} chars reached)"
    lines.extend([header, "", clipped, ""])
    return max_chars, True


def build_generic_briefing(
    folder: Path,
    report_slug: str,
    files: list[GenericFile],
    skipped: list[dict[str, str]],
    output: Path,
    max_chars: int,
    extra_config: dict | None = None,
    sources: dict[str, Source] | None = None,
    cache_dir: Path | None = None,
    stats: CompressionStats | None = None,
    generic_compress: CompressConfig | None = None,
    image_records: list[ImageRecord] | None = None,
) -> None:
    title = (extra_config or {}).get("title") or report_slug.replace("-", " ").title()
    lines = [f"# {title}", "", f"Source folder: `{folder}`", ""]
    cache_dir = cache_dir or (output.parent / ".compress-cache")
    stats = stats or CompressionStats()
    if extra_config and (extra_config.get("briefing") or {}).get("sections"):
        lines.extend(render_briefing_sections(extra_config, sources or {}, cache_dir, stats))
    included_chars = 0

    overview = [item for item in files if item.bucket == "overview"]
    lines.extend(["## Overview", ""])
    if not overview:
        lines.extend([f"(no matching files found under {folder.name})", ""])
    for item in overview:
        text = generic_file_text(item, skipped)
        included_chars, _ = append_with_total_cap(
            lines,
            included_chars,
            f"### {item.rel_path.as_posix()}",
            text or "(no data)",
            max_chars,
        )

    lines.extend(["## Subproject Docs", ""])
    subdirs = sorted({item.subdir for item in files if item.subdir != "(root)"})
    if not subdirs:
        lines.extend([f"(no matching files found under {folder.name})", ""])
    for subdir in subdirs:
        lines.extend([f"### {subdir.replace('-', ' ').replace('_', ' ').title()}", ""])
        subdir_items = [item for item in files if item.subdir == subdir and item.bucket == "subproject"]
        if not subdir_items:
            lines.extend([f"(no matching files found under {subdir})", ""])
            continue
        for item in subdir_items:
            text = generic_file_text(item, skipped)
            included_chars, _ = append_with_total_cap(
                lines,
                included_chars,
                f"#### {item.rel_path.as_posix()}",
                text or "(no data)",
                max_chars,
            )

    lines.extend(["## Misc Source Text", ""])
    misc = [item for item in files if item.bucket == "misc"]
    if not misc:
        lines.extend([f"(no matching files found under {folder.name})", ""])
    for item in misc:
        text = generic_file_text(item, skipped)
        fallbacks_before = stats.fallbacks
        item_compress = generic_compress if item.extension in {".pdf", ".odt", ".docx", ".rtf"} else None
        text = compress_text(item.path, text, item_compress, cache_dir, stats).strip()
        if item_compress is None and len(text) > GENERIC_MISC_FILE_CAP:
            skipped.append({"path": str(item.path), "reason": f"misc excerpt truncated at {GENERIC_MISC_FILE_CAP} chars"})
            text = text[:GENERIC_MISC_FILE_CAP].rstrip() + "\n\n[...truncated]"
        elif item_compress is not None and stats.fallbacks > fallbacks_before and len(text) > GENERIC_MISC_FILE_CAP:
            skipped.append({"path": str(item.path), "reason": f"misc fallback excerpt truncated at {GENERIC_MISC_FILE_CAP} chars"})
            text = text[:GENERIC_MISC_FILE_CAP].rstrip() + "\n\n[...truncated]"
        included_chars, _ = append_with_total_cap(
            lines,
            included_chars,
            f"### {item.rel_path.as_posix()}",
            text or "(no data)",
            max_chars,
        )

    append_images_section(lines, image_records or [])
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    logging.info("wrote generic briefing %s", output)


def generic_csv_rows(files: list[GenericFile]) -> dict[str, tuple[list[str], list[dict[str, object]]]]:
    by_ext = Counter(item.extension for item in files)
    by_subdir = Counter(item.subdir for item in files)
    by_month = Counter(item.mtime_month for item in files)
    return {
        "files-by-extension": (
            ["extension", "file_count"],
            [{"extension": key, "file_count": by_ext[key]} for key in sorted(by_ext)],
        ),
        "files-by-subdir": (
            ["subdir", "file_count"],
            [{"subdir": key, "file_count": by_subdir[key]} for key in sorted(by_subdir)],
        ),
        "files-by-mtime-month": (
            ["month", "file_count"],
            [{"month": key, "file_count": by_month[key]} for key in sorted(by_month)],
        ),
    }


def generic_todo_rows(files: list[GenericFile]) -> tuple[list[dict[str, str]], list[str]]:
    todo_rows: list[dict[str, str]] = []
    parsed_paths: list[str] = []
    for item in files:
        if item.extension not in {".html", ".htm"}:
            continue
        rows = parse_html_todos(item.path)
        if rows:
            todo_rows.extend(rows)
            parsed_paths.append(item.rel_path.as_posix())
    return todo_rows, parsed_paths


def write_generic_csvs(
    data_dir: Path,
    files: list[GenericFile],
    extra_config: dict | None = None,
    sources: dict[str, Source] | None = None,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for stale_csv in data_dir.glob("*.csv"):
        stale_csv.unlink()
        logging.info("removed stale csv %s", stale_csv)

    for name, (columns, rows) in generic_csv_rows(files).items():
        write_csv(data_dir / f"{name}.csv", columns, rows)

    todo_rows, parsed_paths = generic_todo_rows(files)
    if todo_rows:
        logging.info("generic todo html parsed: %s", ", ".join(parsed_paths))
        counts = Counter(row["status"] for row in todo_rows)
        status_rows = [{"status": status, "count": counts.get(status, 0)} for status in ["done", "in-progress", "pending"]]
        category_counts = Counter(row["category"] for row in todo_rows)
        category_rows = [{"category": key, "count": category_counts[key]} for key in sorted(category_counts)]
        write_csv(data_dir / "todos-by-status.csv", ["status", "count"], status_rows)
        write_csv(data_dir / "todos-by-category.csv", ["category", "count"], category_rows)
    else:
        logging.info("generic todo html parsed: none")

    if extra_config and extra_config.get("csvs"):
        write_csvs({"csvs": extra_config.get("csvs")}, sources or {}, data_dir, clear_stale=False)


def dry_run_generic(folder: Path, report_slug: str, files: list[GenericFile], skipped: list[dict[str, str]], max_chars: int) -> None:
    todo_rows, parsed_paths = generic_todo_rows(files)
    skipped_by_reason = Counter(item["reason"] for item in skipped)
    print(f"folder: {folder}")
    print(f"report_slug: {report_slug}")
    print(f"output: {NOTEBOOK_ROOT / report_slug}")
    print(f"max_chars: {max_chars}")
    print(f"included_files: {len(files)}")
    print(f"skipped_files: {len(skipped)}")
    for reason in sorted(skipped_by_reason):
        print(f"  {reason}: {skipped_by_reason[reason]}")
    print("csvs:")
    print("  files-by-extension.csv")
    print("  files-by-subdir.csv")
    print("  files-by-mtime-month.csv")
    if todo_rows:
        print("  todos-by-status.csv")
        print("  todos-by-category.csv")
        print(f"todo_html: {', '.join(parsed_paths)}")
    else:
        print("todo_html: none")


def log_skipped(skipped: list[dict[str, str]]) -> None:
    for item in skipped:
        logging.info("skipped file: %s (%s)", item["path"], item["reason"])


CSV_TYPES = {
    "directory_counts": csv_directory_counts,
    "html_todo_parse": csv_html_todo_parse,
    "markdown_section_counts": csv_markdown_section_counts,
}


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in apply_columns(rows, columns):
            writer.writerow(row)
    logging.info("wrote csv %s rows=%s", path, len(rows))


def write_image_csv(data_dir: Path, records: list[ImageRecord]) -> None:
    columns = ["path", "description", "width", "height", "bytes", "tier"]
    rows = [
        {
            "path": str(record.path),
            "description": record.description,
            "width": record.width or "",
            "height": record.height or "",
            "bytes": record.size_bytes,
            "tier": record.tier,
        }
        for record in records
    ]
    write_csv(data_dir / "image-descriptions.csv", columns, rows)


def describe_images(records: list[ImageRecord], config: VisionConfig, report_dir: Path, stats: VisionStats) -> list[ImageRecord]:
    if not config.enabled:
        return []
    if not records:
        logging.info("vision enabled but no images found")
        return []
    active_tiers = sorted({record.tier for record in records})
    required_models = {vision_tier(config, tier).model for tier in active_tiers}
    try:
        available_models = ollama_available_models(config.ollama_url)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
        stats.fallback_count += 1
        logging.warning("vision preflight failed: %s; skipping image descriptions", exc)
        return []
    missing = sorted(required_models - available_models)
    if missing:
        stats.fallback_count += 1
        logging.warning(
            "vision model missing: required=%s available=%s; skipping image descriptions",
            ", ".join(missing),
            ", ".join(sorted(available_models)),
        )
        return []

    cache_dir = report_dir / ".vision-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    described: list[ImageRecord] = []
    describers: dict[str, OllamaImageDescriber] = {}
    for record in records:
        tier = vision_tier(config, record.tier)
        try:
            image_bytes = record.path.read_bytes()
            cache_item = image_cache_path(cache_dir, image_bytes, tier)
            stats.attempted_images += 1
            if cache_item.is_file():
                record.description = cache_item.read_text(encoding="utf-8").strip()
                stats.cache_hits += 1
                logging.info("vision cache hit: %s tier=%s", record.path, record.tier)
            else:
                started = time.monotonic()
                describer = describers.setdefault(record.tier, OllamaImageDescriber(config, tier))
                record.description = describer.describe(record.path)
                cache_item.write_text(record.description.rstrip() + "\n", encoding="utf-8")
                logging.info(
                    "vision described: %s tier=%s wall_seconds=%.2f chars=%s",
                    record.path,
                    record.tier,
                    time.monotonic() - started,
                    len(record.description),
                )
            if record.description:
                stats.described_images += 1
                if record.tier == "deep":
                    stats.deep_images += 1
                else:
                    stats.bulk_images += 1
                described.append(record)
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, RuntimeError, binascii.Error) as exc:
            stats.failed_images += 1
            logging.warning("vision describe failed for %s: %s", record.path, exc)
            continue
    return described


def append_images_section(lines: list[str], records: list[ImageRecord]) -> None:
    if not records:
        return
    lines.extend(["## Images", ""])
    groups = sorted({record.group for record in records})
    for group in groups:
        lines.extend([f"### {group}", ""])
        for record in [item for item in records if item.group == group]:
            description = record.description.strip() or "Image description unavailable"
            dimensions = f"{record.width}x{record.height}" if record.width and record.height else "unknown"
            lines.extend(
                [
                    f"![{description}]({record.path})",
                    "",
                    f"**Path:** `{record.path}`  ",
                    f"**Tier:** {record.tier}  ",
                    f"**Dimensions:** {dimensions}  ",
                    "",
                ]
            )


def build_sources(config: dict, config_path: Path) -> dict[str, Source]:
    sources = {}
    compress_defaults = top_level_compress_defaults(config)
    for item in config.get("sources", []):
        name = item["as"]
        compress_value = item.get("compress")
        vision_value = item.get("vision")
        if vision_value is True:
            source_vision = None
        elif vision_value is False:
            source_vision = "false"
        elif vision_value is None:
            source_vision = None
        else:
            source_vision = str(vision_value)
        sources[name] = Source(
            name=name,
            path=resolve_path(item["path"], config_path.parent),
            glob=item.get("glob"),
            convert=item.get("convert"),
            compress=normalize_compress_config(compress_value, compress_defaults),
            vision=source_vision,
        )
    return sources


def build_briefing(
    config: dict,
    sources: dict[str, Source],
    output: Path,
    stats: CompressionStats,
    image_records: list[ImageRecord] | None = None,
) -> None:
    title = config.get("title") or config.get("report_slug") or "Notebook Extract"
    lines = [f"# {title}", "", "Generated by `notebook-extract` from deterministic local sources.", ""]
    lines.extend(render_briefing_sections(config, sources, output.parent / ".compress-cache", stats))
    append_images_section(lines, image_records or [])
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    logging.info("wrote briefing %s", output)


def render_briefing_sections(
    config: dict,
    sources: dict[str, Source],
    cache_dir: Path,
    stats: CompressionStats,
) -> list[str]:
    lines: list[str] = []
    for section in (config.get("briefing") or {}).get("sections", []):
        heading = section.get("heading", "Section")
        source_name = section.get("from")
        source = sources.get(source_name)
        lines.extend([f"## {heading}", ""])
        if source is None:
            logging.warning("briefing section source missing: %s", source_name)
            lines.extend(["(no data)", ""])
            continue
        extract = section.get("extract")
        if extract == "first_h1_section":
            content = first_h1_section(source)
        elif extract == "todo_list_grouped":
            content = todo_group_markdown(source)
        elif section.get("include"):
            content = included_docs(source, list(section.get("include") or []), cache_dir, stats)
        else:
            content = source_excerpt(source, cache_dir, stats, section.get("limit_chars"))
        lines.extend([content or "(no data)", ""])
    return lines


def write_csvs(config: dict, sources: dict[str, Source], data_dir: Path, clear_stale: bool = True) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    if clear_stale:
        for stale_csv in data_dir.glob("*.csv"):
            stale_csv.unlink()
            logging.info("removed stale csv %s", stale_csv)
    for spec in config.get("csvs", []):
        name = slugify(spec["name"])
        csv_type = spec["type"]
        columns = spec.get("columns")
        if not columns:
            raise ValueError(f"csv {name} missing columns")
        handler = CSV_TYPES.get(csv_type)
        if handler is None:
            raise ValueError(f"unsupported csv type: {csv_type}")
        if csv_type == "directory_counts":
            rows = handler(spec)
        else:
            rows = handler(spec, sources)
        write_csv(data_dir / f"{name}.csv", list(columns), rows)


def log_compression_stats(stats: CompressionStats) -> None:
    logging.info(
        "compression stats: attempted_files=%s cache_hits=%s fallbacks=%s",
        stats.attempted_files,
        stats.cache_hits,
        stats.fallbacks,
    )


def log_vision_stats(stats: VisionStats) -> None:
    logging.info(
        "vision stats: attempted_images=%s described_images=%s cache_hits=%s failed_images=%s skipped_images=%s fallback_count=%s bulk_images=%s deep_images=%s",
        stats.attempted_images,
        stats.described_images,
        stats.cache_hits,
        stats.failed_images,
        stats.skipped_images,
        stats.fallback_count,
        stats.bulk_images,
        stats.deep_images,
    )


def list_configs() -> int:
    if not CONFIG_ROOT.is_dir():
        return 0
    for path in sorted(CONFIG_ROOT.glob("*.yml")):
        print(path.stem)
    for path in sorted(CONFIG_ROOT.glob("*.yaml")):
        print(path.stem)
    return 0


def find_config(name: str) -> Path:
    path = Path(name).expanduser()
    if path.is_file():
        return path.resolve()
    for suffix in (".yml", ".yaml"):
        candidate = CONFIG_ROOT / f"{name}{suffix}"
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"config not found: {name}")


def run_extract(config_path: Path) -> Path:
    config = load_config(config_path)
    vision_config = normalize_vision_config(config.get("vision"))
    report_slug = slugify(config.get("report_slug") or config_path.stem)
    report_dir = NOTEBOOK_ROOT / report_slug
    setup_logging(report_dir)
    logging.info("config=%s", config_path)
    logging.info("report_dir=%s", report_dir)
    sources = build_sources(config, config_path)
    stats = CompressionStats()
    vision_stats = VisionStats()
    vision_skipped: list[dict[str, str]] = []
    image_records: list[ImageRecord] = []
    if vision_config.enabled:
        image_records = collect_named_images(sources, vision_config, vision_skipped)
        for item in vision_skipped:
            logging.info("skipped file: %s (%s)", item["path"], item["reason"])
        vision_stats.skipped_images = len(vision_skipped)
        image_records = describe_images(image_records, vision_config, report_dir, vision_stats)
    build_briefing(config, sources, report_dir / "briefing.md", stats, image_records)
    write_csvs(config, sources, report_dir / "data")
    if vision_config.enabled:
        write_image_csv(report_dir / "data", image_records)
    log_compression_stats(stats)
    log_vision_stats(vision_stats)
    return report_dir


def run_generic_extract(
    folder: Path,
    out_slug: str | None,
    config_path: Path | None,
    max_chars: int,
    dry_run: bool,
    compress_config: CompressConfig | None = None,
    vision_config: VisionConfig | None = None,
) -> Path:
    if not folder.is_dir():
        raise NotADirectoryError(f"folder not found: {folder}")

    auto_slug = f"{slugify(folder.name)}-deepdive"
    generic_config = {
        "report_slug": auto_slug,
        "title": auto_slug.replace("-", " ").title(),
        "sources": [],
        "csvs": [],
    }
    override_config: dict = {}
    if config_path is not None:
        override_config = load_config(config_path)
    config = deep_merge(generic_config, override_config)
    if config.get("sources_exclude"):
        excluded = set(config.get("sources_exclude") or [])
        config["sources"] = [item for item in config.get("sources", []) if item.get("as") not in excluded]
    vision_config = vision_config or normalize_vision_config(config.get("vision"))
    report_slug = slugify(out_slug or config.get("report_slug") or auto_slug)
    report_dir = NOTEBOOK_ROOT / report_slug

    files, skipped = walk_generic_folder(folder)
    if dry_run:
        dry_run_generic(folder, report_slug, files, skipped, max_chars)
        return report_dir

    setup_logging(report_dir)
    logging.info("generic_folder=%s", folder)
    logging.info("report_dir=%s", report_dir)
    logging.info("included_files=%s", len(files))
    logging.info("skipped_files_initial=%s", len(skipped))

    config_base = config_path.parent if config_path is not None else folder
    sources = build_sources(config, config_base)
    stats = CompressionStats()
    vision_stats = VisionStats()
    image_records: list[ImageRecord] = []
    if vision_config.enabled:
        image_records = collect_generic_images(folder, vision_config, skipped)
        vision_stats.skipped_images = len([item for item in skipped if item["reason"].startswith("vision")])
        image_records = describe_images(image_records, vision_config, report_dir, vision_stats)
    build_generic_briefing(
        folder=folder,
        report_slug=report_slug,
        files=files,
        skipped=skipped,
        output=report_dir / "briefing.md",
        max_chars=max_chars,
        extra_config=config,
        sources=sources,
        cache_dir=report_dir / ".compress-cache",
        stats=stats,
        generic_compress=compress_config,
        image_records=image_records,
    )
    log_skipped(skipped)
    write_generic_csvs(report_dir / "data", files, extra_config=config, sources=sources)
    if vision_config.enabled:
        write_image_csv(report_dir / "data", image_records)
    log_compression_stats(stats)
    log_vision_stats(vision_stats)
    return report_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract deterministic Notebook briefing and CSV data")
    parser.add_argument("config_name", nargs="?", help="Config name from configs/extract/<name>.yml")
    parser.add_argument("--config", help="Explicit config path")
    parser.add_argument("--folder", help="Generic mode source folder")
    parser.add_argument("--out", help="Generic mode report slug override")
    parser.add_argument("--dry-run", action="store_true", help="Print generic extraction plan without writing files")
    parser.add_argument("--max-chars", type=int, default=100000, help="Generic briefing total character cap")
    parser.add_argument("--compress", action="store_true", help="Generic mode: compress Misc Source Text through Ollama")
    parser.add_argument("--compress-model", default=DEFAULT_COMPRESS_MODEL, help="Ollama model for --compress")
    parser.add_argument("--target-tokens", type=int, default=DEFAULT_COMPRESS_TARGET_TOKENS, help="Target tokens for --compress")
    parser.add_argument("--vision", action="store_true", help="Generic mode: describe discovered images through Ollama vision")
    parser.add_argument("--deep", action="store_true", help="Generic mode: use deep vision tier for all images")
    parser.add_argument("--vision-model", help="Generic mode: override the Ollama model used by the selected vision tier")
    parser.add_argument("--list", action="store_true", help="List available extract configs")
    args = parser.parse_args()

    if args.list:
        return list_configs()
    if args.folder:
        if args.config_name:
            parser.error("do not provide <config-name> with --folder")
        folder = Path(args.folder).expanduser().resolve()
        config_path = Path(args.config).expanduser().resolve() if args.config else None
        compress_config = None
        if args.compress:
            compress_config = normalize_compress_config(
                {
                    "model": args.compress_model,
                    "target_tokens": args.target_tokens,
                },
                CompressConfig(),
            )
        base_vision = load_config(config_path).get("vision") if config_path else None
        vision_config = normalize_vision_config(base_vision, enabled_override=args.vision or None, deep=args.deep, model=args.vision_model)
        report_dir = run_generic_extract(
            folder,
            args.out,
            config_path,
            args.max_chars,
            args.dry_run,
            compress_config=compress_config,
            vision_config=vision_config,
        )
        if not args.dry_run:
            print(report_dir)
        return 0

    if args.out or args.dry_run or args.max_chars != 100000 or args.compress or args.compress_model != DEFAULT_COMPRESS_MODEL or args.target_tokens != DEFAULT_COMPRESS_TARGET_TOKENS or args.vision or args.deep or args.vision_model:
        parser.error("--out, --dry-run, --max-chars, --compress, --compress-model, --target-tokens, --vision, --deep, and --vision-model require --folder")
    if bool(args.config) == bool(args.config_name):
        parser.error("provide either <config-name> or --config <path>")

    config_path = Path(args.config).expanduser().resolve() if args.config else find_config(args.config_name)
    report_dir = run_extract(config_path)
    print(report_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
