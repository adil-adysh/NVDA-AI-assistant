# Presentation Intent Spec

> **Purpose**: Behavioral contract for how Python expresses UI intent to the host without coupling to specific views.
> **Current location**: `ui/intent.py` (105 lines), consumed by `plugin/presenter.py`, `ui/adapter.py`, `ui/session_state.py`.

## Core concept

Presentation intent is metadata that tells the host *how* to render, not *what* to render. The host renders generically based on these typed intent fields.

## Intent types

### `PresentationIntent`

Controls the overall view mode and window behavior.

```python
class PresentationIntent(TypedDict, total=False):
    interaction_mode: Literal["display", "chat"]
    controls_visible: bool
    attention_policy: Literal["none", "foreground_if_background", "activate_and_focus"]
    focus_target: Literal["content", "composer", "primary_action", "status"]
```

### `DisplayPresentationIntent`

Display-specific layout options.

```python
class DisplayPresentationIntent(TypedDict, total=False):
    variant: Literal["standard", "result_actions"]
    initial_focus: Literal["content", "composer", "primary_action", "status"]
    toolbar: DisplayToolbarIntent

class DisplayToolbarIntent(TypedDict):
    actions: list[Literal["copy_text", "copy_markdown", "clear", "close"]]
    placement: Literal["after_content"]
```

## Builder functions

### `build_presentation_intent(**kwargs) -> PresentationIntent`

Creates a presentation intent dict with only the specified fields.

### `merge_presentation_intent(metadata, **kwargs) -> dict`

Merges presentation intent fields into existing metadata dict. Preserves all existing keys, only overrides specified fields. Used to layer intent onto session state or view model metadata.

### `build_display_presentation(**kwargs) -> DisplayPresentationIntent`

Creates display-specific presentation with defaults:
- `variant`: `"standard"`
- `toolbar.actions`: `[]`
- `toolbar.placement`: `"after_content"`

## Usage patterns

### Pattern A: Chat view opening (presenter.py)

```python
merge_presentation_intent(
    session_state.to_metadata(),
    interaction_mode=INTERACTION_MODE_CHAT,
    controls_visible=True,
    attention_policy=ATTENTION_POLICY_ACTIVATE_AND_FOCUS,
    focus_target=FOCUS_TARGET_COMPOSER,
)
```

### Pattern B: Display result (presenter.py)

```python
merge_presentation_intent(
    {"actions": [...]},
    interaction_mode=INTERACTION_MODE_DISPLAY,
    controls_visible=False,
    attention_policy=ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
    focus_target=FOCUS_TARGET_CONTENT,
)
```

### Pattern C: Display with result actions

```python
build_display_presentation(
    variant=DISPLAY_VARIANT_RESULT_ACTIONS,
    initial_focus=FOCUS_TARGET_PRIMARY_ACTION,
    toolbar_actions=(TOOLBAR_ACTION_COPY_TEXT, TOOLBAR_ACTION_COPY_MARKDOWN, TOOLBAR_ACTION_CLOSE),
)
```

## Consumer-side resolution (Rust / WebUI)

The host resolves intent from either top-level payload fields or `metadata{}`:

1. Check payload root → `attention_policy`, `focus_target`, `controls_visible`
2. Check `metadata` → same fields
3. Check `metadata.display_presentation` → `variant`, `initial_focus`, `toolbar`
4. For `focus_target`: also checks `display_presentation.initial_focus`
5. Apply defaults based on command type (e.g., `open_chat` → `activate_and_focus`)

## Rules

- Streaming updates MUST use `attention_policy = "none"`.
- Final answers MAY use `attention_policy = "foreground_if_background"`.
- One-shot results SHOULD use `controls_visible = False`.
- One-shot results SHOULD use `display_presentation.variant = "result_actions"`.
- `focus_target` only applies when `attention_policy` is not `"none"`.
