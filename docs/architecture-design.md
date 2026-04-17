# NVDA AI Assistant — Context Specification & Filtering Design

## 1. Purpose

This document defines a **user-configurable, deterministic, and structured context system** for NVDA AI Assistant use cases.

The system enables users to:

* Explicitly select what information is sent to the LLM
* Control token usage through field selection and filtering
* Customize prompts using structured variables
* Define app-specific and global behaviors

This design strictly adheres to the following invariants:

* User-controlled context (no hidden expansion)
* Deterministic execution
* Focus-centric data model
* NVDA interaction reality (document vs UIA)
* Declarative, non-programmatic configuration

---

## 2. High-Level Model

A use case is defined as:

> **UseCase = Scope + Content Specification + Prompt**

```text
User YAML
   ↓
UseCaseSpec
   ↓
Scoped Resolution
   ↓
Content Resolution (fields + filters)
   ↓
Prompt Rendering (template variables)
   ↓
LLM Execution
```

---

## 3. Use Case Specification

### 3.1 Structure

```yaml
use_case_id:
  description: string

  scope:
    apps: [string]        # optional (default: global)

  content:
    <field_name>: {}      # or with filters

  prompt: string
```

---

### 3.2 Example

```yaml
explain_table:
  description: "Explain the current table in Excel"

  scope:
    apps: ["excel"]

  content:
    workbook_title: {}

    worksheet_name: {}

    current_table:
      limit:
        rows: 15
        columns: 8

  prompt: |
    Workbook: ${workbook_title}
    Sheet: ${worksheet_name}

    Table:
    ${current_table}

    Explain this table clearly.
```

---

## 4. Scope Resolution

### 4.1 Scope Types

| Type         | Behavior                      |
| ------------ | ----------------------------- |
| Global       | Available in all apps         |
| App-specific | Active only in specified apps |

---

### 4.2 Rules

1. If `scope.apps` is absent → global
2. If present → match current app
3. App-specific overrides global (same ID)

---

## 5. Content Specification

### 5.1 Core Principle

> Users explicitly define **what information** is sent to the LLM.

---

### 5.2 Syntax

```yaml
content:
  <field_name>: {}
```

or

```yaml
content:
  <field_name>:
    select: ...
    include: ...
    exclude: ...
    limit: ...
    sort: ...
```

---

## 6. Field Vocabulary (Controlled)

### 6.1 Document Mode Fields

* `page_title`
* `main_text`
* `headings`
* `links`
* `landmarks`
* `buttons`
* `edit_fields`
* `focused_text`

---

### 6.2 Application (UIA) Fields

* `app_name`
* `window_title`
* `focused_element`
* `nearby_elements`
* `container`
* `workbook_title`
* `worksheet_name`
* `current_table`
* `current_cell`

---

### 6.3 Constraint

> Only predefined fields are allowed. Unknown fields must fail validation.

---

## 7. Filtering System

### 7.1 Design Goals

* Declarative (no scripting)
* Predictable
* Field-specific
* Token-aware

---

## 7.2 Filter Structure

```yaml
<field>:
  select: ...
  include: ...
  exclude: ...
  limit: ...
  sort: ...
```

---

## 8. Selectors

Define the **base dataset**.

### Allowed values:

```yaml
select: all        # default
select: focused
select: nearby
```

Structured:

```yaml
select:
  section: "main"
```

UIA:

```yaml
select:
  container: "form"
```

---

## 9. Include / Exclude Filters

### 9.1 Text Matching

```yaml
include:
  text_contains: ["login"]

exclude:
  text_contains: ["ads"]
```

---

### 9.2 Role-Based (UIA)

```yaml
include:
  role: ["button", "link"]
```

---

### 9.3 Attribute Filters

```yaml
exclude:
  empty: true
```

---

### 9.4 Structural Filters

```yaml
headings:
  include:
    level: [1, 2]
```

---

## 10. Limit and Sorting

```yaml
limit: 10

sort: relevance
```

Or structured:

```yaml
limit:
  rows: 20
  columns: 10
```

---

## 11. Execution Pipeline

For each field:

```text
1. SELECT base set
2. APPLY include filters
3. APPLY exclude filters
4. APPLY sort
5. APPLY limit
6. FORMAT output
```

---

## 12. Prompt System

### 12.1 Template

```yaml
prompt: |
  Title: ${page_title}
  Headings:
  ${headings}
```

---

### 12.2 Rules

1. Variables must match `content` fields
2. Missing variables → validation error
3. Empty fields → render gracefully

---

### 12.3 Variable Formatting

| Type   | Format          |
| ------ | --------------- |
| string | plain text      |
| list   | bullet list     |
| table  | structured grid |

---

## 13. Validation Rules

### Required

* `description`
* `content`
* `prompt`

---

### Content Validation

* Field must exist in vocabulary
* Filters must be valid for that field
* Types must match schema

---

### Prompt Validation

* All `${variables}` must exist in content
* No unknown variables allowed

---

## 14. Error Handling

* Fail fast on invalid config
* Provide user-readable error messages
* Never crash NVDA

---

## 15. Token Control

Token usage is controlled by:

* Number of fields
* Filters (limit, include/exclude)
* Field type (e.g., table vs text)

No hidden truncation beyond safety limits.

---

## 16. Clean Architecture Mapping

| Component       | Responsibility            |
| --------------- | ------------------------- |
| UseCaseSpec     | user-defined behavior     |
| ScopeResolver   | app filtering             |
| ContentResolver | field + filter resolution |
| Collectors      | NVDA data extraction      |
| PromptRenderer  | template binding          |
| LLMService      | execution                 |

---

## 17. Non-Goals

The system must NOT support:

* Arbitrary expressions
* Scripting or lambdas
* Regex (initially)
* Cross-field conditions
* Dynamic decision-making by system

---

## 18. Extensibility

Future extensions may include:

* Presets for common configurations
* Token estimation hints
* Advanced formatting options
* Additional field types

---

## 19. Final Definition

> A use case is a **declarative specification of structured context and prompt instructions**, allowing users to precisely control what information is sent to the LLM and how it is used.

---

## 20. Summary

This design provides:

* Full user control over context
* Predictable and deterministic behavior
* Strong alignment with NVDA interaction models
* Safe extensibility without complexity explosion

It replaces:

* implicit context selection
* opaque prompt construction

with:

> **explicit, structured, and user-defined AI behavior**
