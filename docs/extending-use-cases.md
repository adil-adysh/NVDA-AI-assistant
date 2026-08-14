# Extending AI Assistant with declarative use cases

Extension authors can register a use case without creating a new orchestration class when the use case follows the standard flow:

1. collect one or more context requests;
2. build a prompt;
3. call the text LLM operation;
4. display the response.

```python
# Import paths depend on how the add-on host loads the global plugin package.
from context.types import ExtractionIntent, PageTextRequest
from use_case.declarative import (
    DeclarativeUseCaseDefinition,
)

definition = DeclarativeUseCaseDefinition(
    id="my_page_question",
    description="Answer a question about the current page.",
    extraction_intent=ExtractionIntent(requests=(PageTextRequest(),)),
    prompt_key="my_page_question",
    result_message="Page answer ready",
    context_policy="query_retrieval",
    context_token_budget=4500,
)

def build_prompt(context):
    return f"Answer using only this page text:\n\n{context.text}"

services.use_case_engine.register_declarative(definition, build_prompt)
```

Context selection is expressed by `ExtractionIntent`. Available built-in requests include `PageTextRequest`, `PageStructureRequest`, `FocusedElementTextRequest`, and the image request types.

For workflows that need confirmation, tools, multiple model calls, or controlled mutation of an NVDA control, implement the existing `UseCase` interface directly and register it with `register_use_case`.

Registration validates duplicate identifiers and unknown context request kinds before execution. The declarative runner remains compatible with the existing progress, streaming, reduction, metadata, and result presentation paths.
