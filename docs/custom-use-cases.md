# Custom use cases

NVDA AI Assistant supports user-defined custom AI use cases that extend the built-in assistant commands. Custom use cases are loaded from the add-on configuration and appear in the assistant layer when you press `U`.

## What custom use cases do

A custom use case lets you:

- define a new assistant action with a friendly description
- choose whether it summarizes page content, describes an image, or generates text
- reuse built-in prompt templates or provide your own inline prompt text
- add custom behavior for code explanation, form assistance, developer workflows, and more

## Where to configure them

Custom use cases are saved in the AI Assistant YAML configuration file:

- `%APPDATA%\nvda\AIAssistant\config.yaml`

The file uses the `aiAssistant` top-level section. Custom cases go under `useCases:`.

## Configuration format

Use the `useCases` section to define one or more custom use cases. Each custom use case is keyed by a unique ID.

Example:

```yaml
aiAssistant:
  useCases:
    summarizePage:
      description: "Summarize the current page in simple language."
      llm_method: summarize
      context_profile: ["page"]
      prompt_template_key: page_summary

    explainCode:
      description: "Explain a code snippet or selected code using the built-in code explanation prompt."
      llm_method: generate
      prompt_template_key: explain_code

    customHelp:
      description: "Analyze the current page and suggest the next best action."
      llm_method: generate
      context_profile: ["page"]
      prompt_template: |
        ${system_prompt}
        You are an accessibility assistant. Review the current page content and suggest the most useful next steps for a keyboard user.
        Page title: ${page_title}
        Page text:
        ${text}
```

## Supported fields

- `description` (required): a short text label shown in the custom use case list.
- `llm_method` (required): one of `summarize`, `describe_image`, or `generate`.
- `prompt_template` (optional): an inline prompt string for this use case.
- `prompt_template_key` (optional): a named prompt template to render.
- `prompt_key` (optional, legacy): a legacy alias for `prompt_template_key`.
- `context_profile` (optional): choose one or more context profiles, for example `app`, `page`, or `image`.
- `requires_input` (optional): set `true` if the use case conceptually needs user input.

## Prompt template behavior

A custom use case must provide either `prompt_template` or `prompt_template_key`.

- `prompt_template` lets you write a custom prompt directly in the config.
- `prompt_template_key` reuses a named prompt template from the add-on.

Built-in prompt template keys include:

- `page_summary`
- `image_description`
- `chat`
- `chat_with_page_context`
- `chat_with_image_context`
- `explain_code`

The `explain_code` template is included as a reusable prompt key, but code explanation itself must be defined as a custom use case in `useCases:`.

## Prompt variables

Built-in prompt rendering supports context variables such as:

- `${system_prompt}`
- `${text}`
- `${app_title}`
- `${page_title}`
- `${image_context}`
- `${truncated_notice}`

Use these variables in inline prompt templates to include page or image data.

## Using custom use cases

After defining custom use cases and restarting NVDA if needed, use them like this:

1. Press `NVDA+Shift+A` to activate the assistant layer.
2. Press `U` to list custom use cases.
3. Press a number key (`1`–`9`, or `0` for the tenth entry) to run a custom use case.

If no custom use cases are defined, the add-on will say so when you press `U`.

## Advanced customization

You can also override shared prompt templates separately with a `promptTemplates:` section in the same config file.

Example:

```yaml
aiAssistant:
  promptTemplates:
    explain_code: |
      ${system_prompt}
      Explain the following code block clearly for a developer who is new to the project.
      ${text}
```

This lets you keep custom use cases simple while customizing prompt behavior globally.
