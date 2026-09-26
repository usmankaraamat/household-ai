# Usable-context benchmark — 2026-09-26

Needle found at depths 10%, 50%, 90% of the context, which is filled to about 80%.

| Model | num_ctx | Found | Prefill tok/s | Decode tok/s | Loaded GB | On GPU |
|---|---|---|---|---|---|---|
| Granite 4.2 8B Q4_K_M | 4096 | 3/3 | 2180.7 | 63.5 | 5.89 | 100% |
| Granite 4.2 8B Q4_K_M | 8192 | 3/3 | 1941.7 | 30.8 | 6.84 | 92% |
| Granite 4.2 8B Q4_K_M | 16384 | 3/3 | 1364.3 | 6.2 | 8.22 | 76% |
| Granite 4.2 8B Q4_K_M | 32768 | 3/3 | 869.9 | 1.7 | 11.02 | 56% |
| Qwen3.5 9B Q4_K_M | 4096 | 3/3 | 1936.4 | 67.3 | 5.64 | 100% |
| Qwen3.5 9B Q4_K_M | 8192 | 3/3 | 2010.5 | 55.1 | 6.43 | 88% |
| Qwen3.5 9B Q4_K_M | 16384 | 3/3 | 1805.0 | 38.3 | 6.71 | 84% |
| Qwen3.5 9B Q4_K_M | 32768 | 3/3 | 1495.8 | 16.1 | 7.39 | 76% |

**Overflow test** (twice the text the context holds, needle 10% in):

- Granite 4.2 8B Q4_K_M: sent ~8192 tokens into num_ctx 4096; server processed None; needle missed; answer: "SERVER REFUSED (400): {"error":"{\"error\":{\"code\":400,\"message\":\"request (9091 tokens) exceeds the available context size (4096 tokens), try increasing it\",\"type\":\"exceed_context_size_error\",\"n_prompt_tokens\":"
- Qwen3.5 9B Q4_K_M: sent ~8192 tokens into num_ctx 4096; server processed None; needle missed; answer: "SERVER REFUSED (400): {"error":"{\"error\":{\"code\":400,\"message\":\"request (9642 tokens) exceeds the available context size (4096 tokens), try increasing it\",\"type\":\"exceed_context_size_error\",\"n_prompt_tokens\":"
