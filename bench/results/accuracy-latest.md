# Accuracy benchmark — 2026-09-26 (answers re-scored 2026-09-26 with stricter rules)

21 questions · top-5 retrieval · num_ctx 8192 · backend ollama · temperature 0
Retrieval found every needed document for 18/18 questions (same sections given to every model).
Correct means every required fact is present, no known-wrong value appears, and a refusal is exactly NOT FOUND.

| Model | Correct | Facts | Two-doc | Trap | Says 'not found' when it should | Citations right | Invented citations | Leaked reasoning | Cut off | Median s | Prefill tok/s | Decode tok/s | Loaded GB | On GPU |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Granite 4.2 8B Q4_K_M | 20/21 | 13/13 | 3/4 | 1/1 | 3/3 | 17/18 | 0 | 1 | 0 | 3.4 | 1032.8 | 48.4 | 6.84 | 92% |
| Qwen3.5 9B Q4_K_M | 19/21 | 13/13 | 2/4 | 1/1 | 3/3 | 18/18 | 0 | 0 | 0 | 3.4 | 940.6 | 54.0 | 6.43 | 88% |
