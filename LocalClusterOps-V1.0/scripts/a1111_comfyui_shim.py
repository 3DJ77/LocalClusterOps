#!/usr/bin/env python3
import argparse
import base64
import json
import random
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

import requests


DEFAULT_NEGATIVE = "text, watermark, blurry, low quality, distorted, deformed"
DEFAULT_CHECKPOINT = "sd_xl_base_1.0.safetensors"


def clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def clamp_float(value, default, minimum, maximum):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_sampler(name):
    if not name:
        return "euler"
    normalized = str(name).strip().lower().replace(" ", "_")
    aliases = {
        "euler_a": "euler_ancestral",
        "k_euler": "euler",
        "k_euler_a": "euler_ancestral",
        "dpm++_2m": "dpmpp_2m",
        "dpm++_2m_karras": "dpmpp_2m",
        "dpmpp_2m_karras": "dpmpp_2m",
    }
    return aliases.get(normalized, normalized)


def build_workflow(payload, checkpoint):
    width = clamp_int(payload.get("width"), 1024, 64, 2048)
    height = clamp_int(payload.get("height"), 1024, 64, 2048)
    steps = clamp_int(payload.get("steps"), 22, 1, 100)
    cfg = clamp_float(payload.get("cfg_scale"), 7.0, 0.0, 30.0)
    seed = payload.get("seed", -1)
    seed = random.randrange(0, 2**32) if seed in (None, "", -1, "-1") else clamp_int(seed, 0, 0, 2**63 - 1)
    sampler = normalize_sampler(payload.get("sampler_name"))
    scheduler = "karras" if "karras" in str(payload.get("sampler_name", "")).lower() else "normal"
    prompt = str(payload.get("prompt") or "").strip()
    negative = str(payload.get("negative_prompt") or DEFAULT_NEGATIVE).strip()
    prefix = f"a1111_shim_{uuid.uuid4().hex}"

    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": prefix},
        },
    }
    info = {
        "prompt": prompt,
        "negative_prompt": negative,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "checkpoint": checkpoint,
    }
    return workflow, info


class ShimHandler(BaseHTTPRequestHandler):
    comfyui_url = "http://127.0.0.1:8188"
    checkpoint = DEFAULT_CHECKPOINT
    timeout = 300

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        if self.path == "/sdapi/v1/options":
            self.send_json(200, {"sd_model_checkpoint": self.checkpoint})
            return
        if self.path == "/sdapi/v1/samplers":
            self.send_json(200, [{"name": name} for name in ["Euler", "Euler a", "DPM++ 2M Karras"]])
            return
        if self.path == "/health":
            response = requests.get(f"{self.comfyui_url}/system_stats", timeout=5)
            self.send_json(200, {"ok": response.ok, "comfyui": self.comfyui_url, "checkpoint": self.checkpoint})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/sdapi/v1/txt2img":
            self.send_json(404, {"error": "not found"})
            return

        try:
            payload = self.read_json()
            workflow, info = build_workflow(payload, self.checkpoint)
            prompt_response = requests.post(
                f"{self.comfyui_url}/prompt",
                json={"prompt": workflow, "client_id": "a1111-comfyui-shim"},
                timeout=30,
            )
            prompt_response.raise_for_status()
            prompt_id = prompt_response.json()["prompt_id"]

            deadline = time.time() + self.timeout
            history = {}
            while time.time() < deadline:
                history_response = requests.get(f"{self.comfyui_url}/history/{prompt_id}", timeout=10)
                history_response.raise_for_status()
                history = history_response.json().get(prompt_id, {})
                if history.get("outputs"):
                    break
                time.sleep(1)

            image_meta = None
            for output in history.get("outputs", {}).values():
                images = output.get("images") or []
                if images:
                    image_meta = images[0]
                    break
            if not image_meta:
                raise RuntimeError(f"ComfyUI did not return an image for prompt_id={prompt_id}")

            image_response = requests.get(
                f"{self.comfyui_url}/view?{urlencode(image_meta)}",
                timeout=30,
            )
            image_response.raise_for_status()
            image_b64 = base64.b64encode(image_response.content).decode("ascii")
            info["infotexts"] = [
                f"{info['prompt']}\nNegative prompt: {info['negative_prompt']}\n"
                f"Steps: {info['steps']}, Sampler: {info['sampler_name']}, CFG scale: {info['cfg_scale']}, "
                f"Seed: {info['seed']}, Size: {info['width']}x{info['height']}, Model: {info['checkpoint']}"
            ]
            self.send_json(200, {"images": [image_b64], "parameters": payload, "info": json.dumps(info)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})


def main():
    parser = argparse.ArgumentParser(description="A1111-compatible txt2img shim for ComfyUI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8189)
    parser.add_argument("--comfyui-url", default="http://127.0.0.1:8188")
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    args = parser.parse_args()

    ShimHandler.comfyui_url = args.comfyui_url.rstrip("/")
    ShimHandler.checkpoint = args.checkpoint
    server = ThreadingHTTPServer((args.host, args.port), ShimHandler)
    print(
        f"A1111 ComfyUI shim listening on http://{args.host}:{args.port}; "
        f"ComfyUI={ShimHandler.comfyui_url}; checkpoint={ShimHandler.checkpoint}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
