# GitHub Copilot Instructions — NVDA AI Assistant

## 1. Purpose of This File
This repository implements an NVDA add-on with a layered architecture.

Copilot MUST generate code that:
- Respects strict layer boundaries
- Uses existing abstractions (UseCase, ContextPipeline, ProviderProxy)
- Avoids architectural shortcuts

---

## 2. System Overview (Mental Model)

Flow of execution:

NVDA → GlobalPlugin → AIAssistantApplication → UseCaseEngine  
→ ContextPipeline → LLMService → ProviderProxy → Provider  
→ Result → Presenter → NVDA UI

This flow must NOT be bypassed.

---

## 3. Layer Responsibilities (STRICT)

### plugin/
- NVDA entrypoint, gestures, lifecycle
- Threading (BackgroundTaskRunner)
- Calls UseCaseEngine
- NO business logic

### use_case/
- Defines features (summary, image, chat)
- Pure orchestration layer
- Uses:
  - ContextPipeline
  - LLMService
- MUST NOT:
  - Access NVDA APIs
  - Call providers directly

### context/
- Collects structured data from NVDA/browser
- Uses collectors (page, image, etc.)
- Produces `PromptContext`
- No business logic

### providers/
- Implements LLM providers (Gemini, Ollama)
- Hidden behind `ProviderProxy`
- Hot-swappable via config

### service/
- Wraps LLM interaction
- Handles:
  - tool execution
  - streaming
  - chat coordination
- Only layer allowed to interact with providers

### ui/
- Rendering only
- No logic, no provider calls

---

## 4. Dependency Rules (MANDATORY)

Allowed:

plugin → service → use_case → context  
                  ↓  
               providers  

Forbidden:
- use_case → providers
- context → use_case
- ui → service/provider direct calls

---

## 5. Use Case Pattern (REQUIRED)

When adding a feature:

1. Create a class extending `UseCase`
2. Define:
   - spec
   - context_profile
   - execution logic
3. Register in:
   `use_case/registry.py`

Execution MUST go through:
`UseCaseEngine`

Never:
- Call use cases directly from plugin
- Hardcode mappings

---

## 6. Context System Rules

- Always use `ContextPipeline`
- Never manually assemble context in use cases
- Use:
  `ContextProfile = Literal["app", "accessibility", "image"]`

Collectors must:
- Be small and composable
- Return structured data (not raw strings)

---

## 7. Provider Rules

- Always access providers via:
  `ProviderProxy`
- Providers must implement:
  `LLMProvider`

Never:
- Reference provider names outside `providers/`
- Add provider-specific logic elsewhere

---

## 8. LLM / Chat Rules

All model interaction MUST go through:
- `LLMService`
- `ProviderLLMService`
- `ChatCoordinator`

Responsibilities:
- streaming
- tool calls
- session handling

Never:
- Call provider from use_case or UI
- Duplicate chat logic

---

## 9. Tools System

- Register tools in `ToolRegistry`
- Execute via `ToolExecutor`

Never:
- Execute tools directly in use cases

---

## 10. Threading Rules (CRITICAL FOR NVDA)

- Never block main thread
- Use:
  `BackgroundTaskRunner`

All long operations must:
- Run in background
- Return results safely to UI

---

## 11. UI Rules

- Render only
- No logic
- No provider or service calls

Must support:
- streaming updates
- partial responses

---

## 12. Error Handling

- NVDA must never crash
- Always fail gracefully
- Provide user-safe messages
- Log internal errors clearly

---

## 13. Code Style

### Python
- Use type hints everywhere
- Prefer:
  - dataclasses
  - Protocols
  - TypedDict
- Avoid dynamic typing unless necessary

---

## 14. Performance Constraints

- NVDA is latency-sensitive
- Prefer:
  - streaming over blocking
  - small memory footprint
- Avoid:
  - large synchronous operations
  - unnecessary copies

---

## 15. When Generating Code

Copilot must:

1. Identify correct layer
2. Follow existing patterns in that layer
3. Reuse abstractions:
   - UseCaseEngine
   - ContextPipeline
   - ProviderProxy
4. Keep implementation minimal and consistent

---

## 16. What NOT to Do

- Do not bypass UseCaseEngine
- Do not mix UI and logic
- Do not hardcode provider behavior
- Do not access NVDA APIs outside plugin/context
- Do not introduce global state
- Do not duplicate context or chat logic

---

## 17. Good Patterns

✔ Add feature:
UseCase → Register → Trigger via application → Render via presenter

✔ Add provider:
Implement `LLMProvider` → Register in factory

✔ Add tool:
Register in ToolRegistry → Execute via ToolExecutor

---

## 18. Bad Patterns

✘ Provider calls inside use_case  
✘ NVDA API calls inside service  
✘ Prompt building in UI  
✘ Skipping ContextPipeline  
✘ Blocking main thread  

---

## 19. Project Constraints

- NVDA add-on (accessibility-critical)
- Must remain responsive
- Supports:
  - page summarization
  - image description
  - contextual chat

Providers:
- Ollama (preferred, local-first)
- Gemini (optional fallback)

---

## 20. If Uncertain

- Do NOT guess architecture
- Ask for clarification
- Or follow existing similar implementation
