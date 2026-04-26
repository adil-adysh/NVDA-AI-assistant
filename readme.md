# NVDA AI Assistant

A practical NVDA add-on that brings AI-driven summaries, chat, screenshot description, and page content interaction into the screen reader workflow.

## Overview

NVDA AI Assistant helps NVDA users understand web pages, applications, and visual content faster. It keeps you inside NVDA while adding a simple assistant layer for quick actions.

## What it does

- Summarizes the current page or active application content, including web browser pages and virtual page views.
- Describes the current foreground window as an image.
- Opens an AI chat window for questions and follow-up conversation.
- Loads active page content into chat for more relevant answers.
- Attaches screenshots to chat for screen-based interaction.

## Requirements

- NVDA installed and running.
- One of the following:
  - Ollama installed locally on Windows and running.
  - A Gemini API key configured in the AI Assistant settings panel.
- If you use Ollama, a local model downloaded for inference.
- If you use Gemini, no local model is required.

If you are using Ollama on Windows:

- Install it with `winget install Ollama.Ollama`.
- List installed models with `ollama ls`.
- Download a model with `ollama pull gemma4:e4b` or `ollama pull ministral-3:3b`.
- Start the Ollama service before using the add-on.

## Quick start

1. Install NVDA and enable the AI Assistant add-on.
2. Install Ollama on Windows with `winget install Ollama.Ollama`, then start the Ollama service; or set a Gemini API key in the AI Assistant settings panel.
3. Download a local model for Ollama, such as `ollama pull gemma4:e4b` or `ollama pull ministral-3:3b`.
4. Open the AI Assistant settings panel and choose your provider.
5. Focus a page or application window in NVDA.
6. Press NVDA+Shift+A and choose a command.

## How to use it

- Press NVDA+Shift+A to activate the assistant layer.
- Then press:
  - S for summary
  - I for image description
  - C for chat
  - P for page content chat
  - X for screenshot chat
  - T to toggle the active provider
  - H for help
- In the chat window, type a message and press Send or Ctrl+Enter.
- Use the chat history button inside the chat window to review prior conversation turns.

## Configuration

From the AI Assistant settings panel you can:

- Choose the active provider.
- Enable or disable streaming.
- Enable or disable progress announcements.
- Adjust request timeout and retry behavior.
- Configure image size, format, and quality.
- Enable optional think mode when your provider supports it.

## Hardware and model guidance

For local inference, model size and hardware matter. A GPU gives better performance and lets you use larger models, while CPU-only systems work best with smaller models and will be slower.

Recommended model choices:

- `ministral-3:3b` for moderate hardware. It supports completion, vision, and tool-based interactions, making it a solid local choice.
- `gemma4:e2b` or `gemma4:e4b` for stronger systems with more memory. These models are better at richer chat and screen description, and `gemma4:e4b` also supports thinking-style responses.
- `llama3.2:1b` for CPU-only inference, with lower output quality and simpler responses.

If you use a GPU, choose a larger model for better results. If you only have a CPU, choose a smaller model and expect simpler responses.

You can inspect model capabilities from Ollama with:

- `ollama show gemma4:e4b`
- `ollama show ministral-3:3b`

This helps confirm the model supports the features you need.

## Troubleshooting

- If the assistant cannot connect, check your provider settings.
- If a request fails, NVDA will announce the error and show a message.
- If a model is missing, download it in Ollama or update your provider configuration.
- Use the provider toggle from the assistant layer to switch providers quickly.

## Notes

- Page summary works with browser content and virtual page views.
- The add-on uses the current foreground window to identify the active application.
- Image description captures the current screen and describes what is shown.

## Open source and contributions

This project is open source and welcomes issues, suggestions, and contributions. Open an issue or pull request on GitHub to contribute.

## License

See `COPYING.txt` for license details.
