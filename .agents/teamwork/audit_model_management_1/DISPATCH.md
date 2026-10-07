## 2026-10-02T05:03:36Z
You are the Model-Management Architect (Agent 5).
Working directory: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1
Original Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
Repository Root: D:\nvda-addons\NVDA-AI-assistant
Current commit HEAD: ced1cbc

Read ORIGINAL_REQUEST.md first. You are responsible for:
1. Audit F (Model Management Consolidation):
   - Map current responsibilities across service/model_cache.py, provider/catalog.py, provider/controls.py, provider/readiness.py, LiteRT manager, llama-cpp manager, negative visibility settings, catalog snapshots, and UI models tab.
   - Identify fragmented state, duplicate download tracking, conflicting readiness checks, and coupling with NVDA background threads.
2. Invariants A11–A15 (Central ModelManagementService across Multi-Modalities):
   - Design a centralized application ModelManagementService coordinating smaller collaborators across modalities:
     * CHAT
     * VISION
     * OCR
     * TRANSCRIPTION
     * EMBEDDING
     * TTS
   - Define unified model metadata, download state machine, disk cache layout, readiness probing, negative visibility filtering, and multi-model coexistence rules (e.g. running an OCR model alongside an LLM without memory thrashing).
   - Eliminate parallel model stacks and silent fallbacks.

Every finding must include exact file paths and line numbers at HEAD (ced1cbc).
Classify every finding using the mandatory tags: CONFIRMED, LIKELY, DESIGN DETAIL, BLOCKER, UNKNOWN / REQUIRES EXPERIMENT.

Write your full detailed report to:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1\audit_report.md
Write your completion handoff to:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1\handoff.md
Send a summary message when complete using send_message.
