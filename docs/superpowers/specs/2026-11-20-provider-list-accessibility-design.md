# Provider and Model List Accessibility Design

## Intent

Make provider and model selection usable and understandable with the keyboard and NVDA screen reader. Keep the existing native wx dialogs and WebView selectors, while replacing simulated model-state controls with explicit, labeled controls.

## Goals

- In the model manager, replace “Show disabled models” with two labeled filters: **Enabled state** (**All**, **Enabled**, **Disabled**) and **Availability** (**All**, **Available**, **Not downloaded**, **Downloading**, **Failed**). Start both at **All** and combine them with AND semantics.
- Show enabled state as text under a named **Enabled** column and active state under a named **Active** column. Do not use checkbox/radio glyphs as state controls.
- Provide separate **Enable** and **Disable** buttons for the selected model. Enable only the action that applies to its current state; both are keyboard reachable and have clear accessible names.
- Select and focus the configured active model when the model manager first loads. Preserve selection after refreshes and model actions where the selected model remains visible. If filtering hides it, clear selection and disable selection-dependent actions without moving focus unexpectedly.
- Select and focus the active preset when the llama.cpp preset list first loads; preserve selection on later refreshes.
- Give the native General settings provider and active-model controls explicit accessible names matching their visible labels.
- When the provider-management list first opens, select and focus the active provider. After refreshes, preserve the selected provider and deliberately restore focus to the selected row when an action has removed or hidden the focused control.
- Keep the WebView provider/model selectors and Hugging Face cache picker behavior intact; they already have labeled controls and intentional initial focus/selection behavior.

## Non-goals

- Replacing wx list controls or changing provider/model catalog data, sort order, runtime behavior, or persistence semantics.
- Changing model activation rules or the meaning of the existing per-model enabled setting.
- Redesigning unrelated lists or selectors elsewhere in the add-on.

## Approaches

1. **Independent Enabled state and Availability filters plus Enable/Disable actions (selected).** Users can combine filters without a separate option for every pair of states, select a row, review its named state columns, and activate a clearly labeled action. This keeps state changes explicit and keyboard-operable and scales as model states grow.
2. **One combined filter with preset combinations.** This can expose common combinations directly, but makes the choice list grow with each new state and can omit combinations users need. The selected approach keeps each filter focused on one dimension.
3. **A genuine checkbox in each model row.** This gives direct toggling, but does not solve status filtering and depends on the list toolkit exposing each checkbox and its state accessibly. The selected approach uses ordinary buttons instead.

## Behavior details

- The **Enabled state** filter applies to the user-controlled enabled/disabled state. **All** includes both states.
- The **Availability** filter groups `READY`, `DOWNLOADED`, and `REGISTERED` as **Available**; `NOT_DOWNLOADED` as **Not downloaded**; `DOWNLOADING` as **Downloading**; and `FAILED` as **Failed**. This keeps cloud-ready and registered models meaningful in the same UI.
- Apply the two filters together. If a selected model becomes hidden after filtering or after an enable/disable action, clear its selection and disable model-specific actions. Keep keyboard focus on the control the user operated; expose a concise status message explaining that the model is hidden by the current filters when applicable.
- The **Active** column is informational and reflects the single configured active model. Activation continues through the existing **Set Active** button.
- Initial selection is distinct from keyboard focus: on initial list load, both should land on the active model/provider where one exists. On later refreshes, restore focus only when refresh displaced it; do not steal focus from an unrelated control.
- All new user-facing strings use the repository translation conventions. Keep protocol identifiers and diagnostic logs unchanged.

## Constraints

- Follow the repository architecture and accessibility conventions in the root `AGENTS.md`.
- Keep provider management, model visibility, and activation routed through existing services and stores; UI code must not call providers directly.
- Preserve the current WebView/native UI boundary and avoid new dependencies.
- No legacy catalog or settings migration is part of this work.

## Builder decisions

- Use the existing `wx.Choice` pattern for the status filter and ordinary `wx.Button` controls for enable/disable.
- Use visible text values in the model list’s Enabled and Active columns, with column headers, so state is available independently of color or glyph interpretation.
- Keep **All** as the default for both filters so the active model is not accidentally hidden on open.
