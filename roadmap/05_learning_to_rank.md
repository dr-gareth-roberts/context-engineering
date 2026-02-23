# Roadmap 05: Learning-to-Rank (Adaptive Weighting)

## Objective
Evolve the context management from static heuristics to a dynamic system that learns which context items actually help the agent succeed.

## The Feedback Loop
1.  **Capture:** When an LLM response is generated, store the `ContextTrace` ID with the response.
2.  **Signal:** The user or a "Judge LLM" provides feedback (Thump up/down).
3.  **Attribute:**
    -   **Positive Signal:** Increase the weight of the features (kind, priority, source) of the `selected` items.
    -   **Negative Signal:** Slightly decrease the weight of the `selected` items or flags them for "Better Compression."

## Implementation: `AdaptiveWeightingManager`
-   **Storage:** A small JSON or SQLite table tracking `feature_weights`.
-   **Optimization:** Use a simple Gradient Descent or Thompson Sampling approach to adjust `ScoringWeights` over time.
-   **UI:** A "Leaderboard" in the Context Inspector showing which `ContextItem` types (e.g., "User Preferences" vs "Doc Segments") are performing best.

## Data Model Extensions
```python
class FeedbackEvent(BaseModel):
    trace_id: str
    score: float # 0.0 to 1.0
    feedback_type: str # "user_click", "judge_eval", "conversion"
```

## Success Criteria
-   After 100 interactions, the system automatically prioritizes "Past Conversation History" over "Documentation" if the user tends to ask follow-up questions.
