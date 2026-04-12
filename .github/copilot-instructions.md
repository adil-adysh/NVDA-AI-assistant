# Project Guidelines

## Code Style
- Python add-on code lives under [addon/globalPlugins/AI-assistant/](addon/globalPlugins/AI-assistant/).
- Follow the repo's formatting and typing rules from [pyproject.toml](pyproject.toml): tabs for indentation, Ruff line length 110, and Pyright strict mode.
- Keep type hints in new code and preserve the existing `pyright: report...=false` exceptions only where the current module already needs them.
- Prefer small, focused changes that match the surrounding module style instead of broad refactors.

## Architecture
- The add-on starts in [addon/globalPlugins/AI-assistant/__init__.py](addon/globalPlugins/AI-assistant/__init__.py) where `GlobalPlugin` wires together context collection, provider access, tools, chat, and UI.
- Context gathering flows through [addon/globalPlugins/AI-assistant/context/pipeline.py](addon/globalPlugins/AI-assistant/context/pipeline.py) and the collector/extractor modules under [addon/globalPlugins/AI-assistant/context/](addon/globalPlugins/AI-assistant/context/).
- Provider selection is abstracted through [addon/globalPlugins/AI-assistant/providers/](addon/globalPlugins/AI-assistant/providers/) and the chat orchestration layer lives in [addon/globalPlugins/AI-assistant/service/](addon/globalPlugins/AI-assistant/service/).
- Canonical message and tool types live in [addon/globalPlugins/AI-assistant/core/](addon/globalPlugins/AI-assistant/core/); keep provider adapters aligned with those shared types.
- Build metadata, packaging inputs, and localization sources are defined in [buildVars.py](buildVars.py) and [sconstruct](sconstruct).

## Build and Test
- Build the add-on package with `scons`.
- Run linting with `python -m ruff check addon/globalPlugins/AI-assistant/`.
- Run syntax checks with `python -m py_compile addon/globalPlugins/AI-assistant/<file>.py` for targeted modules.
- Use [readme.md](readme.md) for user-facing behavior, and [addon/doc/en/readme.md](addon/doc/en/readme.md) for the generated help document source.

## Conventions
- Treat the Ollama backend as stateless across requests; chat history must stay client-managed in the coordinator/service layer.
- Keep provider-specific logic behind the provider/adapters boundary; do not leak Ollama or Gemini request details into UI or use-case code unless necessary.
- When testing in a shared terminal, clear or override environment variables such as `OLLAMA_MODEL`, `GEMINI_API_KEY`, and `GOOGLE_API_KEY` so prior runs do not affect the result.
- Update [buildVars.py](buildVars.py) instead of editing generated manifest or packaging outputs directly whenever the change is about add-on metadata.
- Link to existing docs rather than duplicating them; the repo currently has the main overview in [readme.md](readme.md) and release notes in [changelog.md](changelog.md).
