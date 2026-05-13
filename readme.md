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

---

# Features

## Summaries

Summarize:

* web pages
* virtual buffers
* documents
* active application content

Quick actions can continue directly into chat for follow-up interaction.

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

Features include:

* automatic model discovery
* local and cloud inference
* runtime provider switching
* runtime model switching

Providers and models can be changed directly from the chat interface without restarting the conversation.

---

## Think mode

Some providers and models support optional think mode for extended reasoning workflows.

---

# Quick start

## Requirements

* NVDA installed
* One configured AI provider:

  * Ollama
  * OpenAI-compatible API
  * Gemini

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
3. Configure your provider.
4. Choose a model or endpoint.
5. Press `NVDA+Shift+A` to start using the assistant.

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
| `T` | Toggle provider                    |
| `H` | Help                               |

---

# Configuration

The settings panel allows you to:

* choose the active provider
* configure API keys and endpoints
* enable or disable streaming
* configure image quality and size
* adjust timeout behavior
* enable optional think mode

---

# Recommended local models

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

---

# Technical notes

* A dedicated UI host keeps NVDA responsive during AI operations.
* Chat sessions maintain contextual continuity during interaction.

---

# Troubleshooting

* Verify provider configuration if requests fail.
* Ensure Ollama is running for local inference.
* Download required models before use.

---

# Open source and contributions

Issues, suggestions, accessibility feedback, and pull requests are welcome.

---

# License

See `COPYING.txt` for license details.
