# Roadmap 07: PII Redaction at the Edge

## Objective
Ensure that sensitive user data (PII) never reaches the LLM provider, making the toolkit compliant with HIPAA, GDPR, and enterprise security policies.

## Redaction Strategies
1.  **Pattern-Based (Regex):** Fast, local detection of Emails, Credit Cards, Social Security Numbers, and API Keys.
2.  **Model-Based (NLP):** Use a lightweight local model (like `Presidio` or `GLiNER`) to detect Names, Locations, and Organizations that don't follow strict patterns.

## The `RedactingSegmenter`
A wrapper around existing segmenters:
```python
class RedactingSegmenter(BaseSegmenter):
    def __init__(self, base_segmenter: BaseSegmenter, policies: List[str]):
        self.base = base_segmenter
        self.redactor = Redactor(policies)

    def segment(self, text: str, doc_id: str) -> List[Segment]:
        clean_text = self.redactor.scrub(text)
        return self.base.segment(clean_text, doc_id)
```

## Features
-   **Placeholder Mapping:** Replace "John Doe" with `[NAME_1]`. Allow the `AgentContextManager` to "Un-redact" the response if necessary (locally).
-   **Policy Configuration:** `LEVEL_1` (Strict), `LEVEL_2` (Obfuscate only), `LEVEL_3` (Audit only).

## Success Criteria
-   A user can pass a document containing real names and emails, and the "Context Trace" will show that the data was sanitized **before** being packed for the LLM.
