# NVDA AI Assistant

An experimental NVDA add-on that uses a local Ollama model or Google Gemini to summarize the current page and surface accessible context for NVDA users.

## What it does

- Summarizes the current page content using a local Ollama LLM or Gemini.
- Uses NVDA accessibility state to collect page headings, links, buttons, landmarks, and visible content.
- Includes application context by reading the foreground object title from NVDA.
- Captures the current foreground window as an image and describes it with the selected provider.
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

- Active provider: `Ollama`
- Ollama server URL: `http://127.0.0.1:11434`
- Default Ollama model: `gemma4:e2b`
- Default Gemini model: `gemini-flash-latest`
- Summary keybind: `NVDA+Shift+S`
- Image describe keybind: `NVDA+Shift+I`

## Download

Get the latest published add-on package from the GitHub releases page:

- https://github.com/adil-adysh/NVDA-AI-assistant/releases

Download the newest `.nvda-addon` asset and install it in NVDA.

## Configuration

The add-on stores configuration in NVDA's add-on settings panel under the AI assistant settings.

- Choose the active provider: `Ollama` or `Gemini`.
- For Ollama: configure the server URL, model name, keep-alive duration, and context window size.
- For Gemini: configure the model name, API key, optional bearer token, and base URL.
- Shared runtime settings include request timeout, streaming, progress announcements, retry count, and sampling parameters.

When using Gemini, the add-on can also fall back to the `GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variables if no key is provided in the settings.

## Usage

1. Start your local Ollama server.
2. Install or make sure the configured model is available. The add-on will pull the model automatically if it is missing.
3. Open NVDA and focus a page or application window.
4. Press `NVDA+Shift+S` to summarize the current page.
5. NVDA will announce summary progress and show the final text in a browseable message dialog.
6. Press `NVDA+Shift+I` to capture and describe the current foreground window image.
7. NVDA will announce image description progress and show the final text in a browseable message dialog.

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
- Image description uses a screenshot of the current foreground window and requires a vision-capable Ollama model.
- If Ollama cannot be reached or the model pull fails, NVDA will report a descriptive error message.

## License

See `COPYING.txt` for license details.
