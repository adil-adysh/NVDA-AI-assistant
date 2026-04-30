# NVDA Extraction Fixtures and Live Object Contracts

## Purpose

This document captures the live NVDA object contracts observed for Microsoft Edge browser extraction and Microsoft Excel extraction. It is intended to guide the creation of deterministic unit test fixtures for this repo.

## Browser (Edge) contract

### NVDA entrypoints
- `api.getFocusObject()` returns the current focus object.
- `api.getNavigatorObject()` may return the same object as focus in the Edge state observed.
- `api.getForegroundObject()` returns the active window object.

### Observed Edge focus object
- `appModule.appName = "msedge"`
- `role = Role.EDITABLETEXT`
- `name` contains the page title/content description.
- `windowText` contains the Edge window title.
- `treeInterceptor` is a `NVDAObjects.IAccessible.chromium.ChromeVBuf` instance.

### Tree interceptor contract
- has `rootNVDAObject`
- has `isAlive = True`
- has `isReady = True`
- has `makeTextInfo(...)`

### Text extraction contract
- `makeTextInfo(textInfos.POSITION_ALL)` returns a `ChromeVBufTextInfo` object.
- `info.getTextWithFields()` returns a list containing:
  - `str` segments
  - `textInfos.FieldCommand` objects

### Field object contract
Each `FieldCommand` has:
- `.command` such as `controlStart`, `controlEnd`, `formatChange`
- `.field`

The `.field` object supports:
- `.get("role")`
- `.get("IAccessible2::attribute_tag")`
- `.get("IAccessible2::attribute_xml-roles")`
- `.get("name")`
- `.get("IAccessible2::attribute_explicit-name")`
- `.get("isHidden")`

### Live browser semantics seen
- links: `role = Role.LINK`, tag `a`
- headings: `role = Role.HEADING`, tag `h2`, etc.
- landmarks: `role = Role.LANDMARK`, tag `nav`, xml role `navigation`
- buttons: `role = Role.BUTTON`, tag `button`

### Fixture implication for browser
- fake `api` module
- fake `focus`, `navigator`, `foreground`
- fake browser `treeInterceptor` with `makeTextInfo`
- fake `TextInfo.getTextWithFields()` returning field commands
- fake field objects implementing `.get(key)`

## Excel contract

### NVDA entrypoints
- `api.getFocusObject()` returns the Excel selection object.
- `api.getNavigatorObject()` returns the same Excel cell object in the observed state.
- `api.getForegroundObject()` returns the Excel window object.

### Observed Excel focus object
- `appModule.appName = "excel"`
- current focus type can be `ExcelCell` or `ExcelSelection` depending on selection state
- `role = Role.TABLECELL`
- `name` contains the raw Excel selection description, e.g. `A1  name through B1  marks`
- `windowText = "Book1"`
- `treeInterceptor` is `NVDAObjects.window.excel.ExcelBrowseModeTreeInterceptor`

### Excel selection-specific observations
- In the selected range state, focus becomes `NVDAObjects.window.excel.ExcelSelection`
- `focus.name` can contain a descriptive range string with the selected endpoint, selected values, or named range text
- `focus.selection` is an `NVDAObjectTextInfo` with `selection.text` containing the same selection description
- `focus.excelCellInfo` may be absent on `ExcelSelection` objects
- `focus.excelRangeObject()` may return a tuple of selected named range identifiers or selection labels

### Excel tree interceptor contract
- has `rootNVDAObject = ExcelWorksheet`
- has `isAlive = True`
- has `isReady = True`
- does not have `makeTextInfo` on the interceptor itself

### Excel focus object capabilities
- `focus.makeTextInfo(textInfos.POSITION_ALL)` works
- returns `ExcelCellTextInfo`
- `info.getTextWithFields()` returns a minimal list (formatChange + cell text)

### Cell/range extraction contract
Observed cell-specific data is available from:
- `focus.excelCellInfo.address` (when present on `ExcelCell` focus)
- `focus.excelCellInfo.rowNumber` (when present)
- `focus.excelCellInfo.columnNumber` (when present)
- `focus.excelCellInfo.rowSpan` (when present)
- `focus.excelCellInfo.columnSpan` (when present)
- `focus.cellCoordsText`
- `focus.getCellPosition()`
- `focus.name` and `focus.selection.text` for selected range descriptions when focus is `ExcelSelection`

This implies range selection can be modeled by varying:
- `address`
- `rowNumber` / `columnNumber`
- `rowSpan` / `columnSpan`
- `name` / `selection.text` for selection-range descriptions

### Not available or not usable in this state
- `focus.selection()` raised `NotImplementedError`
- `selectionContainer` was `None`
- `focus.columnCount()` / `focus.rowCount()` raised `NotImplementedError`

### Fixture implication for Excel
- fake `api` module
- fake `focus` selection object
- fake `treeInterceptor` with `rootNVDAObject`
- minimal `focus.makeTextInfo(POSITION_ALL)` support if text extraction path is exercised
- fake `excelCellInfo` object with address / row / column / span fields
- fake `cellCoordsText` and optional `name` / `value` / `displayText` / `description`

## Desktop contract

### NVDA entrypoints
- `api.getFocusObject()` returns the current desktop icon item under the desktop list.
- `api.getNavigatorObject()` is expected to return the same desktop item in a similar state.
- `api.getForegroundObject()` returns the active window object, not the desktop root.

### Desktop root structure
- Topmost root is `Desktop` from `csrss`.
- `Desktop` childCount was observed as 6.
- `Desktop` children include:
  - `Windows Input Experience` (`textinputhost`)
  - `WindowRoot` explorer windows
  - `UIA` `Taskbar` (`explorer`)
  - active app windows such as VS Code (`code`)
  - `WindowRoot` `Program Manager` (`explorer`)

### Program Manager / desktop list hierarchy
- The desktop icon list lives under `Program Manager`.
- The observed chain is:
  - `Desktop` (`csrss`, `WINDOW`)
  - `WindowRoot` `Program Manager` (`explorer`, `WINDOW`)
  - `IAccessible` `Program Manager` (`explorer`, `PANE`)
  - nested `WindowRoot` / `IAccessible` wrappers
  - `List` `Desktop` (`explorer`, `LIST`, `childCount = 39`)

### Desktop icon item contract
- Desktop icons are leaf nodes of type `Dynamic_SysListView32EmittingDuplicateFocusEventsListItemIAccessible`.
- Icon items expose:
  - `role = Role.LISTITEM`
  - `name` containing the icon label
  - `windowText = "FolderView"`
  - `treeInterceptor = None`
  - `childCount = 0`
- The focused icon item is one of those list items (e.g. `ghidraRun - Shortcut`).

### Relationship observations
- NVDA creates wrapper layers (`WindowRoot`, `IAccessible`, repeated `List`/`UIA` nodes) above the semantic desktop list.
- The meaningful semantic object for desktop extraction is the `List Desktop` container and its leaf list-item children.
- Identity via Python object `id()` can differ depending on access path, so fixtures should model the semantic contract rather than exact object identity.

### Fixture implication for desktop
- fake `api` module
- fake `focus`, `navigator`, `foreground`
- fake desktop `List` container may be useful for list-level traversal tests
- fake desktop icon item objects with:
  - `role = Role.LISTITEM`
  - `name`
  - `windowText = "FolderView"`
  - `treeInterceptor = None`
  - `childCount = 0`
- treat `Program Manager` / wrapper layers as implementation detail rather than core fixture objects

## Terminal contract

### NVDA entrypoints
- `api.getFocusObject()` returns the current terminal text object.
- `api.getNavigatorObject()` should return the same terminal object in a similar UIA state.
- `api.getForegroundObject()` returns the active terminal window object.

### Observed terminal focus object
- `appModule.appName = "windowsterminal"`
- focus type = `Dynamic__DiffBasedWinTerminalUIAXamlEditableTextEditableTextWithAutoSelectDetectionUIA`
- `name = "pwsh"`
- `windowText = ""`
- `role = 82`
- `childCount = 1`
- `treeInterceptor = None`
- `treeInterceptorClass` is not available / raises `NotImplementedError`

### Text extraction contract
- `focus.makeTextInfo(textInfos.POSITION_ALL)` returns a `NVDAObjects.UIA.UIATextInfo` object.
- `info.getTextWithFields()` returns:
  - one `FieldCommand` with `command = formatChange`
  - a terminal buffer string containing the rendered shell output
- Terminal extraction is UIA text-based rather than browser field-based.
- `focus.basicText` is a short summary string (e.g. `"pwsh pwsh"`).
- `focus.selection` is a `UIATextInfo` object, and `selection.text` may be empty in the current state.

### Parent / wrapper structure
- Terminal focus is wrapped by UIA objects and then by an `IAccessible` terminal window object.
- Observed parent chain includes:
  - UIA wrappers
  - `UIA DesktopWindowXamlSource`
  - `IAccessible` `pwsh`
  - `WindowRoot` `pwsh`
  - top-level `Desktop` root
- The UIA editable text object itself is the meaningful terminal element; wrapper nodes are implementation details.

### Fixture implication for terminal
- fake `api` module
- fake terminal focus object with:
  - `appModule.appName = "windowsterminal"`
  - `role = 82`
  - `name = "pwsh"`
  - `windowText = ""`
  - `treeInterceptor = None`
  - `makeTextInfo(textInfos.POSITION_ALL)` returning a UIATextInfo-like object
  - `info.getTextWithFields()` returning `[FieldCommand(formatChange, {}), terminal_text]`
- fake `basicText` as a short textual summary if code relies on it
- fake `selection` as a `UIATextInfo` object with empty `text` if selection behavior is exercised

## Recommended fixture strategy

### Use shape-based fixtures
- Do not depend on full live NVDA objects.
- Model only the fields and methods the repo actually uses.

### Browser fixture should include
- `focus.appModule.appName = "msedge"`
- `focus.treeInterceptor.makeTextInfo(...)`
- `TextInfo.getTextWithFields()` output stream
- field objects with `.get(key)` support

### Excel fixture should include
- `focus.appModule.appName = "excel"`
- `focus.excelCellInfo.address`
- `focus.excelCellInfo.rowNumber`
- `focus.excelCellInfo.columnNumber`
- `focus.excelCellInfo.rowSpan`
- `focus.excelCellInfo.columnSpan`
- `focus.cellCoordsText`
- `focus.makeTextInfo(textInfos.POSITION_ALL)` if relevant to text extraction

## Notes

- Browser extraction is field-based and rich.
- Excel extraction is more attribute-oriented with cell metadata.
- The same fake `api` module pattern works for both cases.
