# LocalClusterOps

Local-first orchestration console for multi-runtime LLM workflows, automation, and report generation.

---

## Overview

LocalClusterOps provides a single control surface for:

- Local model runtime routing
- Task-focused runtime lanes
- Report generation and notebook pipelines
- Optional image workflow integration (ComfyUI/A1111 shim)
- Offline/local-auth operation

---

## Repository Layout

| Path | Purpose |
|---|---|
| `LocalClusterOps-V1.0/` | Main application, scripts, and runtime tooling |
| `bin/` | Repository-level helper tools (including release guard) |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Linux/macOS shell | Scripts are Bash-based |
| Node.js + npm | Workspace-capable npm required |
| Initial network access | Needed for first `npm install` |
| Local runtime storage | `.local-runtime/` is created automatically |
| Default model runtime | OpenAI-compatible endpoint at `127.0.0.1:11434` |

---

## Runtime Endpoints (Default)

| Lane | Endpoint | Role |
|---|---|---|
| Local Runtime | `127.0.0.1:11434` | Primary model lane |
| Task Runtime | `127.0.0.1:11436` | Optional task-specialized lane |
| Direct Runtime / Report Proxy | `127.0.0.1:11437` | Optional report authoring lane |
| ComfyUI (optional) | `127.0.0.1:8188` | Workflow image generation |
| A1111 shim (optional) | `127.0.0.1:8189` | A1111-compatible image path |

---

## Quick Start

1. Enter the app directory:

   ```bash
   cd LocalClusterOps-V1.0
   ```

2. Install dependencies:

   ```bash
   npm install
   ```

3. Build frontend assets:

   ```bash
   npm run frontend
   ```

4. Start local services:

   ```bash
   ./scripts/local-chat-up.sh
   ```

5. Verify runtime health:

   ```bash
   ./scripts/local-chat-status.sh
   ./scripts/runtime-status.sh
   ```

6. Stop services when done:

   ```bash
   ./scripts/local-chat-down.sh
   ```

---

## Core Scripts

| Script | Purpose |
|---|---|
| `scripts/local-chat-up.sh` | Start local chat/backend stack |
| `scripts/local-chat-status.sh` | Check local stack status |
| `scripts/local-chat-down.sh` | Stop local stack |
| `scripts/runtime-status.sh` | Runtime/service health summary |
| `scripts/report-proxy-up.sh` | Start report proxy |
| `scripts/report-proxy-status.sh` | Check report proxy health |
| `scripts/report-proxy-down.sh` | Stop report proxy |
| `scripts/notebook_extract.py` | Extract source material for reports |
| `scripts/notebook_renderer.py` | Render notebook/report artifacts |
| `scripts/report_proxy.py` | Proxy layer for report workflows |
| `scripts/a1111_comfyui_shim.py` | ComfyUI/A1111 bridge path |

---

## Configuration

Primary local configuration file:

- `LocalClusterOps-V1.0/librechat.local.yaml`

Environment variables can override ports, URLs, and service/unit names for custom deployments.

---

## Optional Integrations

- ComfyUI image workflow support
- A1111-compatible shim routing
- Remote runtime lane over SSH (if configured)
- Task runtime separation for specialized workloads

---

## Release Guard

Before push, run from repo root:

```bash
bin/release-guard.sh
```

Use this during active edits:

```bash
bin/release-guard.sh --allow-dirty
```

---

## License

See `LICENSE` for project licensing details.
