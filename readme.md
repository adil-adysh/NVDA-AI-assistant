# NVDA AI Assistant

A practical AI assistant add-on for NVDA that adds summaries, chat, screenshot understanding, and contextual interaction directly into NVDA.

## Overview

NVDA AI Assistant helps you work with:

* web pages
* documents
* applications
* screenshots
* visual interfaces

without leaving NVDA.

The add-on combines quick actions with a persistent chat workflow, allowing summaries, screenshots, and page content to continue naturally into follow-up conversation.

For fully local inference it can also run **LiteRT-LM** or **llama-server**. LiteRT-LM is downloaded on demand; llama-server is discovered on `PATH` or can be configured with an explicit executable path.

---

# Features

## Summaries

Summarize:

* web pages
* virtual buffers
* documents
* active application content

Quick actions can continue directly into chat for follow-up interaction, or open the result in a brand-new conversation (`Add to chat` / `Open in new chat` actions).

---

## Images and screenshots

* Describe the current foreground window
* Describe the focused NVDA object — captures only the currently focused element's screen region
* Attach screenshots directly into chat
* Attach the focused object's image into chat
* Upload image files for analysis
* Continue discussing visual content in conversation

Supported formats:

* PNG
* JPG / JPEG
* WEBP
* GIF
* BMP
* SVG

---

## Chat

The WebView-based chat UI supports:

* streaming responses
* formatted chat output
* keyboard navigation
* conversation history
* persistent conversations
* conversation sidebar management
* provider and model selection

You can:

* continue previous chats
* switch conversations
* attach screenshots and page context
* continue the same conversation across different models
* press `Escape` to hide the window while a response keeps streaming in the background — it reappears automatically when the answer is ready

---

## Context injection

Attach additional context into an active conversation.

### Page content

Inject:

* page structure
* accessibility information
* virtual buffer content
* active application content

directly into chat.

### Screenshot chat

Capture the current screen and attach it to the active conversation.

---

## Provider support

Supports:

* Ollama
* OpenAI-compatible APIs
* Gemini
* LiteRT-LM (fully local)
* llama.cpp server through `llama-server`

The unified OpenAI-compatible adapter also works with any other server that speaks the `/v1/chat/completions` protocol (for example, llama.cpp server).

Features include:

* automatic model discovery
* local and cloud inference
* runtime provider switching
* runtime model switching
* provider enable / disable
* one-click LiteRT-LM runtime installation
* llama-server router presets with local GGUF and Hugging Face models
* API-backed model availability and capability discovery
* per-model sampling settings
* human-readable model labels

Providers and models can be changed directly from the chat interface without restarting the conversation, or from the assistant layer with `T` / `M` followed by a number.

---

## LiteRT-LM (local inference)

LiteRT-LM is a self-contained local inference runtime. The add-on downloads it on demand, so you can run models on your own machine without installing Python or Ollama:

* download the runtime and models with a progress dialog
* choose CPU, GPU, or Intel NPU-accelerated variants
* download or delete models from the model manager
* supports vision, thinking, and multi-token-prediction models
* the local server starts automatically and applies engine settings on restart

Recommended LiteRT-LM models include Gemma 4 E2B/E4B and Qwen3 1.7B/4B/8B.

---

## llama.cpp server (local inference)

The addon integrates with `llama-server` in router mode. It starts the server with a models preset and keeps one server process alive while model selection is sent in each OpenAI-compatible request.

Install llama.cpp and ensure `llama-server` is available on `PATH`, or set **llama-server executable** in the provider configuration. Configure the server endpoint, for example:

```text
http://127.0.0.1:8081
```

Set **Models preset path** to an existing preset such as:

```text
D:\llama-cpp\models.ini
```

The preset may contain global defaults in `[*]`, model-specific options, local `model =` paths, and Hugging Face `hf-repo =` entries. The addon preserves those options when reconciling imported models. Server settings such as host and port remain outside the preset and are configured through the addon.

Example:

```ini
version = 1

[*]
ctx-size = 36864
flash-attn = true

[gemma4-26b]
hf-repo = WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4
```

The addon queries `/models` and falls back to `/v1/models`. Successful responses are cached and treated as the runtime source of truth for model availability, model switching, status, modalities, and context metadata. A model can be configured using its preset section ID or a recognized Hugging Face source alias.

Model switching does not restart a healthy router. The selected canonical model ID is sent with the chat request, and the server routes the request to that model. See [the llama-server integration guide](docs/llama-cpp-server.md) for the complete lifecycle and troubleshooting details.

---

## Think mode

Some providers and models (including most LiteRT-LM and Qwen3 models) support optional think mode for extended reasoning workflows.

---

# Quick start

## Requirements

* NVDA installed
* One configured AI provider:

  * Ollama
  * OpenAI-compatible API
  * Gemini
  * LiteRT-LM (local — runtime downloaded on demand)
  * llama.cpp server (`llama-server`)

---

## Using Ollama

Install Ollama:

```powershell id="55n8ws"
winget install Ollama.Ollama
```

Download a model:

```powershell id="oaq6xv"
ollama pull gemma4:e4b
```

or:

```powershell id="b7xti3"
ollama pull ministral-3:3b
```

List installed models:

```powershell id="d62g3n"
ollama ls
```

---

# Setup

1. Install the NVDA AI Assistant add-on.
2. Open the AI Assistant settings panel.
3. Use **Manage AI Providers** to enable a provider, install the LiteRT-LM runtime if needed, and set the active provider.
4. Choose a model or endpoint.
5. Press `NVDA+Shift+A` to start using the assistant.

Tip: Use **Configure Active Model** to tune per-model sampling settings (context window, temperature, top-k, top-p, max tokens, repetition penalty).

---

# Commands

Press:

```text id="7h19nm"
NVDA+Shift+A
```

Then press:

| Key | Action                             |
| --- | ---------------------------------- |
| `C` | Open chat                          |
| `S` | Summarize current content          |
| `O` | Summarize page structure           |
| `I` | Describe current window            |
| `F` | Describe focused object            |
| `P` | Attach page content to chat        |
| `X` | Attach screenshot to chat          |
| `Z` | Attach focused object image to chat|
| `V` | Attach selected text to chat       |
| `B` | Attach clipboard content to chat   |
| `T` | Select provider (then a digit)     |
| `M` | Select model (then a digit)        |
| `H` | Help                               |

Press `T` or `M` to hear the available providers or models announced with numbers, then press the number to switch instantly.

---

# Chat keyboard shortcuts

The following shortcuts are available inside the chat window:

| Shortcut | Action |
| -------- | ------ |
| `Escape` | Hide the chat window (streaming continues in the background) |
| `Alt+I` | Focus the message input box |
| `Alt+S` | Send the current message |
| `Shift+Enter` | Insert a new line in the message input |
| `Alt+T` | Copy response text to clipboard |
| `Alt+K` | Copy response as formatted markdown |
| `Alt+R` | Clear the current view |
| `Alt+L` | Focus the response content area |
| `Alt+P` | Focus the provider selector |
| `Alt+M` | Focus the model selector |
| `Alt+A` | Attach an image file |

---

# Configuration

The settings panel allows you to:

* choose the active provider and model
* manage AI providers (enable / disable, install the LiteRT-LM runtime, set active provider)
* configure per-model sampling settings (context window, temperature, top-k, top-p, max tokens, repetition penalty)
* set global model defaults
* configure API keys and endpoints
* configure the llama-server executable and models preset path
* enable or disable streaming
* configure image quality and size
* adjust timeout behavior
* enable optional think mode
* log request metrics to a file

---

# Recommended local models

## Ollama

| Model            | Usage                                      |
| ---------------- | ------------------------------------------ |
| `ministral-3:3b` | General local chat and vision              |
| `gemma4:e2b`     | Lightweight reasoning                      |
| `gemma4:e4b`     | Stronger reasoning and image understanding |
| `llama3.2:1b`    | Lightweight CPU inference                  |

Inspect model details with:

```powershell id="p2owd8"
ollama show gemma4:e4b
```

## LiteRT-LM

Download these from the model manager (Hugging Face). CPU and GPU/NPU variants are available where noted.

| Model           | Usage                                                |
| --------------- | ---------------------------------------------------- |
| `gemma-4-e2b`   | Lightweight vision-language model (CPU / GPU / NPU)   |
| `gemma-4-e4b`   | Stronger vision-language model (CPU / GPU)            |
| `qwen3-1.7b`    | Lightweight reasoning model (thinking)                |
| `qwen3-4b`      | Balanced model, competitive with Gemma 4 E4B          |
| `qwen3-8b`      | Stronger reasoning on larger desktops                 |

---

# Technical notes

* A dedicated UI host keeps NVDA responsive during AI operations.
* Chat sessions maintain contextual continuity during interaction.

---

# Troubleshooting

* Verify provider configuration if requests fail.
* Ensure Ollama is running for local inference.
* For LiteRT-LM, install the runtime and download a model from **Manage AI Providers** before use; the local server starts automatically.
* For llama.cpp, verify `llama-server` is on `PATH` or configure its full executable path, verify the endpoint and preset path, and inspect `GET /models` for the canonical model IDs.
* Download required models before use.

---

# Open source and contributions

Issues, suggestions, accessibility feedback, and pull requests are welcome.

---

# License

See `COPYING.txt` for license details.
