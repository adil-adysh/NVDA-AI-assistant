# Changelog

All notable changes to this project will be documented in this file.

## v0.5.6 - 2026-04-14



### Features

- Feat: update addon version to 0.5.6 and improve changelog content

- Feat: add changelog configuration and commit parser settings to cliff.toml

- Feat: enhance GitHub Actions workflow for building and releasing addon with improved version handling and artifact management

- Feat: update default model and configuration parameters for AI assistant

- Feat: refactor AI assistant configuration management with YAML support and remove deprecated bootstrap logic


## v0.5.5 - 2026-04-14



### Features

- Feat: Add candidate providers for browser, terminal, and text editor; enhance extraction context handling

- Feat: Add AI Assistant plugin with core functionality

- Introduced the AIAssistantApplication class to manage the AI assistant's lifecycle and interactions.
- Implemented background task handling with BackgroundTaskRunner for asynchronous operations.
- Created GlobalPlugin to integrate AI assistant commands into NVDA.
- Developed UseCasePresenter for managing chat interactions and displaying results.
- Added AssistantLayerController to handle gesture bindings for the assistant layer.
- Built PluginServices to encapsulate various services required by the AI assistant.
- Established a base coordinator for shared background task management.
- Integrated error handling and progress reporting mechanisms throughout the plugin.
- Registered default tools for the AI assistant's functionality.


## v0.5.4 - 2026-04-12



### Features

- Add image processing and observability features to AI assistant

- Implemented image capture, preprocessing, and encoding services in the image module.
- Added types for image formats and utility functions for image handling.
- Created observability metrics for tracking request performance and errors.
- Developed a metrics reporter to log request metrics to a file.
- Introduced a user interface for chat interactions, including message input and history display.
- Added download progress tracking for model downloads with user feedback.
- Created a settings panel for configuring AI assistant parameters, including provider settings and image processing options.

- Feat: Implement AI Assistant core functionality with LLM provider integration

- Added abstract interface for LLM providers in `interfaces.py`.
- Created session management for LLM providers in `session.py`.
- Developed service layer for chat and LLM interactions in `service` module.
- Implemented chat coordination and message handling in `chat.py`.
- Established LLM service with support for streaming and image description in `llm.py`.
- Introduced settings state management for provider configurations in `settings_state.py`.
- Developed tool management system including definitions, execution, and registry in `tools` module.
- Created use case engine and specifications for various AI functionalities in `use_case` module.
- Added image description and summarization use cases with context handling.


### Refactoring

- Refactor: remove deprecated logger patching script


## v0.5.3 - 2026-04-11



### Features

- Feat: implement provider state management and update chat UI handling

- Feat: update add-on name and version, enhance changelog for v0.5.3

- Feat: enhance provider title refresh and improve tool handling in chat UI

- Feat: implement canonical message and tool handling in AI assistant

- Feat: add provider toggle functionality and update settings management


### Refactoring

- Refactor AI Assistant: Remove deprecated modules, introduce context management, and enhance LLM service integration

- Deleted `image_description.py`, `page_summary.py`, and `screenshot.py` as part of the refactor.
- Introduced `context.py` to define structured contexts for pages and images.
- Added `context_collectors.py` to manage the collection of page and image contexts.
- Implemented `context_pipeline.py` for merging context fragments.
- Created `llm_service.py` to streamline interactions with LLM providers.
- Added `tool_executor.py` for executing tool calls within the LLM service.
- Developed `use_case_engine.py` to manage various use cases and their execution flow.
- Updated prompt builders to utilize new context structures.
- Enhanced error handling and progress reporting throughout the service.


## v0.5.2 - 2026-04-11



### Features

- Feat: enhance error handling and logging across multiple components


### Other

- Bump version to 0.5.2 and update release notes

- Implement AI Assistant Plugin with Ollama Integration

- Refactored settings.py to streamline configuration retrieval and added _get_raw_setting function for better handling of settings.
- Created addonConfig.py to define configuration specifications for the AI Assistant plugin.
- Developed OllamaClient class in client.py to manage interactions with the Ollama API, including methods for generating text, chatting, and managing models.
- Added error handling with custom OllamaClientError class in errors.py for better error reporting.
- Implemented HTTP request handling in http.py for JSON and streaming requests to the Ollama API.
- Defined response validation and extraction functions in response.py to handle API responses effectively.
- Created type definitions in types.py for structured data handling in API requests and responses.
- Added a test file _test.txt for initial testing purposes.


### Refactoring

- Refactor: update OllamaFunction type definition and simplify tool call handling


## v0.5.1 - 2026-04-11



### Features

- Feat: update version to 0.5.1 with logging refactor and improved diagnostics


### Refactoring

- Refactor logging to use centralized logHandler

- Replaced all instances of the standard logging module with a custom logHandler across multiple files.
- Removed logger initialization and replaced logger calls with log calls for consistency.
- Introduced a ToolRegistry class to manage tool definitions and execution, allowing for dynamic tool registration and invocation.
- Added a default tool "get_time" to demonstrate the tool execution mechanism.
- Updated ChatCoordinator and other components to utilize the new ToolRegistry for tool management.
- Enhanced debug logging to provide better insights into tool execution and API interactions.


## v0.5.0 - 2026-04-10



### Features

- Feat: enhance chat functionality by adding commands for page content and screenshot, and improve initial state handling

- Feat: implement AI assistant command layer with gesture bindings for summary, image description, chat, and help

- Feat: implement chat dialog and coordinator for AI interactions, enhance image description prompts, and refactor Ollama client response handling

- Feat: enhance tool call handling in AI assistant for improved functionality and response processing

- Add new image file test.png

- Feat: refactor AI assistant architecture to enhance image processing and metrics reporting

- Feat: implement request metrics logging for image description and page summary tasks

- Feat: add image processing settings and utilities for enhanced image description


### Improvements

- Docs: update README to clarify AI assistant command layer support and adjust usage instructions


## v0.4.2 - 2026-04-10



### Features

- Feat: update addon version to 0.4.2 and enhance changelog details

- Feat: enhance image description progress messaging and result presentation


## v0.4.1 - 2026-04-10



### Features

- Feat: update addon version to 0.4.1 and enhance changelog details

- Feat: localize script category and add script bindings for summarization and description


## v0.4 - 2026-04-10



### Features

- Feat: Update README to include Gemini provider and enhance configuration details

- Feat: Update .gitignore to include .env file

- Feat: Add Gemini provider integration and enhance settings panel functionality

- Feat: Refactor provider configurations and enhance settings panel integration

- Feat: Implement Gemini provider integration and settings panel updates

- Added Gemini client and related types for API interaction.
- Introduced GeminiProvider class for handling Gemini model requests.
- Updated settings panel to support Gemini configuration (API key, token, base URL, model name).
- Enhanced error handling with custom exceptions for Gemini API errors.
- Refactored provider factory to create instances of GeminiProvider and OllamaProvider based on user selection.
- Implemented streaming capabilities for both Gemini and Ollama providers.
- Updated UI components to dynamically enable/disable fields based on selected provider.


### Fixes

- Fix: correct minimum NVDA version to 2025.3 in buildVars.py


## v0.3 - 2026-04-09



### Features

- Feat: Update version and minimum NVDA version in add-on information

- Feat: Refactor settings panel to improve organization and enhance user experience with clearer labels and grouping

- Feat: Refactor settings panel to streamline configuration inputs and enhance error handling

- Feat: Enhance settings panel with advanced configuration options for AI Assistant

- Feat: Add settings panel for AI Assistant with model name and server URL configuration

- Feat: Introduce default configuration values and refactor settings for improved management of AI assistant features

- Feat: Refactor image description and page summary coordinators to use a shared base coordinator for improved task management

- Feat: Enhance image description and page summary features with new prompt builders

- Feat: Update README to include instructions for image capture and description functionality


## v0.2 - 2026-04-09



### Features

- Feat: Implement image description feature with Ollama and add screenshot capture functionality

- Feat: Add download instructions to README for easier access to add-on package


## v0.1 - 2026-04-09



### Features

- Feat: Revise README to clarify NVDA AI Assistant functionality and features

- Feat: Add appTitle extraction to PageSnapshot and update OllamaClient output format

- Feat: Update add-on URLs for documentation and source code in buildVars.py

- Feat: Enhance DownloadProgressTracker with event processing for download progress

- Feat: Add DownloadProgressTracker for model download progress tracking

- Feat: Implement model preloading and add API probe scripts for Ollama integration

- Add AI assistant functionality with Ollama client integration

- Implemented PageSnapshot and SummaryResponse data models for structured page data handling.
- Developed OllamaClient to interact with the Ollama API for generating summaries from web pages.
- Created PageSummaryCoordinator to manage page summary extraction and processing in a separate thread.
- Added error handling and progress reporting for the summarization process.
- Integrated UI feedback for users during the summarization workflow.

- Feat: Add page summarization functionality with Ollama integration

- Introduced PageSnapshot and SummaryResponse models for structured data handling.
- Implemented OllamaClient for interacting with the local Ollama instance, including methods for summarization and model management.
- Created PageSummaryCoordinator to manage the summarization process, including threading and progress reporting.
- Added page_summary.py to handle the extraction and summarization of the current page, ensuring NVDA remains responsive during processing.
- Updated changelog to reflect new features and improvements.

- Add NVDA MCP server configuration and enhance URL announcer with bookmarking features


### Fixes

- Fix: Update default context size and preferred model for Ollama integration


### Other

- Initial commit with proto type to announce url


