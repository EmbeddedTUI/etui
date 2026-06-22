# OCR Tab Plugin (`etui-ocr`)

## Goal

A new tab plugin that takes a path to an image file, sends it to an
Ollama LLM server (default host `10.0.0.249`) for OCR recognition, and
displays the recognized text returned by the model. The user can edit the
OCR prompt, which is pre-filled with a sensible default.

## Repository

This plugin lives in its own repository, separate from the etui core:

```
/home/pawel/src/32bitmicroLLC/EmbeddedTUI/etui_ocr   (git repo, currently empty)
```

The layout below describes the contents of that repo. The plugin is
discovered by etui through the `etui.tabs` entry point, so it does not need
to live inside the etui source tree.

## Overview

Ollama exposes a vision-capable model over an HTTP API. The default model is
`qwen2.5vl:7b`, with `qwen2.5vl:3b/:32b` and `qwen3-vl` variants available as
options. Model names use Ollama `model:tag` syntax and must match what the
server reports via `GET /api/tags`. For OCR we:

1. Read the image file from disk and base64-encode it.
2. POST it to Ollama's `/api/generate` endpoint together with the prompt.
3. Receive the recognized text and render it in the tab.

This mirrors the structure of the existing tab plugins (see
`plugins/etui-serial/`): an `EtuiTabPlugin` exposing a `TabSpec`, a
`create_widget()` returning a Textual widget, and a Textual tab widget that
does the work on a background worker so the UI stays responsive.

## Package layout

```
etui_ocr/                  # repo root: /home/pawel/src/32bitmicroLLC/EmbeddedTUI/etui_ocr
├── pyproject.toml
├── etui_ocr/
│   ├── __init__.py        # exports OcrTabPlugin
│   ├── plugin.py          # EtuiTabPlugin + TabSpec
│   ├── tab.py             # OcrTab widget (UI + worker)
│   └── client.py          # thin Ollama HTTP client
└── tests/
    └── test_tab.py
```

### `pyproject.toml`

Follow `etui-serial/pyproject.toml`:

```toml
[build-system]
requires = ["pdm-backend"]
build-backend = "pdm.backend"

[project]
name = "etui-ocr"
version = "0.1.0"
description = "OCR Tab Plugin for etui (Ollama vision OCR)"
requires-python = ">=3.13,<3.15"
dependencies = [
    "etui>=0.3.0",
    "textual>=8.1.1",
    "httpx>=0.27",
]

[project.entry-points."etui.tabs"]
ocr = "etui_ocr:OcrTabPlugin"

[tool.pdm.build]
includes = ["etui_ocr/"]
```

`httpx` is used for the HTTP call (sync client, run inside a thread worker).
If a dependency-free path is preferred, fall back to `urllib.request`.

## Configuration / defaults

| Setting        | Default                  | Notes                                   |
|----------------|--------------------------|-----------------------------------------|
| Ollama host    | `10.0.0.249`             | Override via `ETUI_OLLAMA_HOST` env var |
| Ollama port    | `11434`                  | Override via `ETUI_OLLAMA_PORT` env var |
| Model          | `qwen2.5vl:7b`           | Select with options (see below)         |
| Default prompt | see below                | Editable in the UI (TextArea/Input)     |
| Timeout        | `120` s                  | Vision models can be slow               |

**Default prompt:**

> "Extract all text from this image exactly as it appears. Preserve line
> breaks and layout. Output only the recognized text with no commentary."

Resolve the host/port at construction time:
`host = os.environ.get("ETUI_OLLAMA_HOST", "10.0.0.249")`.

**Model options** (offered in the `Select`, default first):

```python
OCR_MODELS = [
    "qwen2.5vl:7b",     # default
    "qwen2.5vl:3b",
    "qwen2.5vl:32b",
    "qwen3-vl:8b",
    "qwen3-vl:4b",
    "qwen3-vl:2b",
    "qwen3-vl:32b",
]
```

Optionally auto-populate this list from `GET /api/tags` on the server (see
Future enhancements) while keeping `qwen2.5vl:7b` as the preselected default.

## UI (`tab.py`)

`OcrTab(CancelOnLeaveMixin, BusMixin, Vertical)` — same base mix used by
`SerialTab`.

Control bar (`Horizontal`, `classes="control-bar"`):
- `Input` for the image file path (`id="ocr-path"`, placeholder
  `"/path/to/image.png"`).
- `Button("Browse", id="ocr-browse")` — optional; opens a file picker if one
  is available in etui, otherwise omit and rely on typed path.
- `Select` for the model name (`id="ocr-model"`, options from `OCR_MODELS`,
  default `qwen2.5vl:7b`).
- `Button("Recognize", id="ocr-run", variant="primary")`.

Prompt area:
- `TextArea` (`id="ocr-prompt"`) pre-loaded with the default prompt so the
  user can tweak it before each run.

Output:
- `RichLog`/`TextArea` (`id="ocr-output"`) showing the recognized text and
  status messages.

### Flow

1. On `Button.Pressed` for `ocr-run`:
   - Validate the path exists and is a readable file; `app.notify(..., variant="error")` on failure.
   - Disable the button / show a "Recognizing…" status line.
   - Launch a thread worker (`run_worker(..., thread=True, group="ocr")`)
     so the blocking HTTP call doesn't freeze the UI. Cancel the group on
     leave/unmount, following `SerialTab.disconnect()`.
2. Worker reads the file, base64-encodes it, calls the Ollama client.
3. On completion, `app.call_from_thread(...)` writes the result (or error)
   into the output widget and re-enables the button.

## Ollama client (`client.py`)

```python
import base64, httpx

def ocr_image(path, prompt, *, host, port, model, timeout=120):
    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    url = f"http://{host}:{port}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["response"]
```

Optional enhancement: set `"stream": True` and incrementally append tokens to
the output widget via `call_from_thread` for live feedback on large images.

## Error handling

- File not found / not readable → notify, abort.
- Connection refused / timeout to `10.0.0.249:11434` → write a clear error in
  the output ("Could not reach Ollama at <host>:<port>").
- Non-200 / model-not-found (`raise_for_status`) → surface the server message.
- Unsupported model (text-only model with no vision) → Ollama returns an
  error; pass it through.

## Plugin registration (`plugin.py`)

```python
from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class OcrTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-ocr", title="OCR", order=600)

    def create_widget(self) -> Widget:
        from .tab import OcrTab
        return OcrTab()
```

`__init__.py` exports `OcrTabPlugin` (matching `etui_serial/__init__.py`).

## Testing (`tests/test_tab.py`)

- Mock the Ollama HTTP call (monkeypatch `client.ocr_image` or `httpx.post`)
  and assert the output widget shows the returned text.
- Test invalid path handling produces an error notification and no request.
- Test that env-var overrides for host/port are honored.
- Use Textual's `App.run_test()` pilot harness, as in the other plugins.

## Build / install

- Add to the default-tabs bundle if OCR should ship by default (see the
  release CI note in the git history about installing default tabs).
- For local dev: `pip install -e .` (or `pdm install`) inside the
  `etui_ocr` repo so the `etui.tabs` entry point is registered in the same
  environment as etui.

## Future enhancements

- File picker dialog for `Browse`.
- Batch OCR over a directory of images.
- Save recognized text to a file.
- Streaming token output.
- Model dropdown auto-populated from `GET /api/tags` on the Ollama server.
