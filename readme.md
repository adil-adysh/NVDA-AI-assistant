# NVDA AI Assistant

An experimental NVDA add-on that uses a local Ollama model to summarize the current page and surface accessible context for NVDA users.

## What it does

- Summarizes the current page content using a local Ollama LLM.
- Uses NVDA accessibility state to collect page headings, links, buttons, landmarks, and visible content.
- Includes application context by reading the foreground object title from NVDA.
- Announces model installation progress and summary progress through NVDA messages.

## Key features

- **Automatic model detection and install**: checks whether `gemma4:e2b` is installed and pulls it if needed.
- **Accessible summary experience**: displays the final summary in an NVDA browseable message dialog.
- **Context-aware prompt**: includes app title, page title, counts of headings/links/buttons/landmarks, and whether content was trimmed.
- **Streaming progress feedback**: shows partial progress updates while generating the summary.

## Requirements

- NVDA-compatible Python build setup for add-on development.
- A local Ollama HTTP server running and reachable.
- Recommended Ollama URL: `http://127.0.0.1:11434`.

## Default behavior

- Ollama server URL: `http://127.0.0.1:11434`
- Default model: `gemma4:e2b`
- Default keybind: `NVDA+Shift+S`

## Download

Get the latest published add-on package from the GitHub releases page:

- https://github.com/adil-adysh/NVDA-AI-assistant/releases

Download the newest `.nvda-addon` asset and install it in NVDA.

## Configuration

The add-on reads the following environment variables when it starts:

- `BROWSER_ASSISTANT_OLLAMA_URL` – custom Ollama HTTP API URL.
- `BROWSER_ASSISTANT_OLLAMA_MODEL` – Ollama model name to use.
- `BROWSER_ASSISTANT_OLLAMA_TIMEOUT_SECONDS` – request timeout in seconds.
- `BROWSER_ASSISTANT_OLLAMA_NUM_CTX` – context window size for generation.
- `BROWSER_ASSISTANT_OLLAMA_KEEP_ALIVE` – Ollama keep-alive duration.
- `BROWSER_ASSISTANT_OLLAMA_MAX_RETRIES` – retry count for Ollama requests.
- `BROWSER_ASSISTANT_OLLAMA_RETRY_BACKOFF_SECONDS` – base backoff seconds for retries.

## Usage

1. Start your local Ollama server.
2. Install or make sure the configured model is available. The add-on will pull the model automatically if it is missing.
3. Open NVDA and focus a page or application window.
4. Press `NVDA+Shift+S` to summarize the current page.
5. NVDA will announce summary progress and show the final text in a browseable message dialog.

## Development

- Add-on source code lives under `addon/globalPlugins/AI-assistant/`.
- Build metadata is defined in `buildVars.py`.
- Packaging and localization helpers are provided by the included `site_scons/` tooling.
- Use `pyproject.toml` configuration for Ruff and Pyright checks.

### Useful commands

- Run Python syntax checks:
  - `python -m py_compile addon/globalPlugins/AI-assistant/ollama_client.py`
- Run Ruff linting:
  - `python -m ruff check addon/globalPlugins/AI-assistant/`
- Build the NVDA add-on package:
  - `scons`

## Notes

- The add-on currently uses the NVDA foreground object title (`windowText`) when available to identify the current application.
- If Ollama cannot be reached or the model pull fails, NVDA will report a descriptive error message.

## License

See `COPYING.txt` for license details.
