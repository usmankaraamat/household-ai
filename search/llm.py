"""Talk to a local model server.

Ollama's native API by default, because it reports prefill and decode timings
separately and lets each request set its context size. Any OpenAI-compatible
server (LM Studio, llama.cpp server) works with backend="openai", with
end-to-end timings only.
"""
import json
import re
import time
import urllib.request

OLLAMA = "http://localhost:11434"
OPENAI = "http://localhost:1234/v1"  # LM Studio's default


def _request(url, body=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def embed(texts, model="nomic-embed-text", base=OLLAMA):
    return _request(f"{base}/api/embed", {"model": model, "input": texts})["embeddings"]


def _rate(tokens, nanoseconds):
    return round(tokens / (nanoseconds / 1e9), 1) if tokens and nanoseconds else None


def chat(messages, model, *, backend="ollama", base=None, num_ctx=8192, think=None,
         temperature=0, max_tokens=512):
    """Return (text, stats). Stats have token counts, tokens/sec and wall-clock seconds."""
    t0 = time.perf_counter()
    if backend == "ollama":
        body = {"model": model, "messages": messages, "stream": False,
                "options": {"num_ctx": num_ctx, "temperature": temperature, "num_predict": max_tokens}}
        if think is not None:
            body["think"] = think
        r = _request(f"{base or OLLAMA}/api/chat", body)
        text = r["message"]["content"]
        # Tokens reused from the prompt cache are counted but take no time, so leave them
        # out of the prefill rate.
        cached = r.get("prompt_eval_cached_count", 0)
        stats = {
            "prompt_tokens": r.get("prompt_eval_count", 0),
            "cached_tokens": cached,
            "output_tokens": r.get("eval_count", 0),
            "prefill_tps": _rate(r.get("prompt_eval_count", 0) - cached, r.get("prompt_eval_duration")),
            "decode_tps": _rate(r.get("eval_count"), r.get("eval_duration")),
            "stop": r.get("done_reason"),
        }
    else:
        r = _request(f"{base or OPENAI}/chat/completions",
                     {"model": model, "messages": messages, "temperature": temperature,
                      "max_tokens": max_tokens})
        text = r["choices"][0]["message"]["content"]
        usage = r.get("usage", {})
        stats = {"prompt_tokens": usage.get("prompt_tokens", 0),
                 "output_tokens": usage.get("completion_tokens", 0),
                 "prefill_tps": None, "decode_tps": None,
                 "stop": r["choices"][0].get("finish_reason")}
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    text, stats["leaked_thinking"] = strip_thinking(text)
    return text, stats


def strip_thinking(text):
    """Remove reasoning a thinking model leaked into its answer, even with thinking off.
    Granite 4.2 has emitted only the closing </think>, with the reasoning before it, so
    everything up to the last </think> goes too. Returns (text, whether anything leaked)."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[1]
    return cleaned.strip(), cleaned != text


def gpu_share(model, base=OLLAMA):
    """How much of a loaded model sits in VRAM: (fraction, total GB). Ollama only."""
    for m in _request(f"{base}/api/ps").get("models", []):
        if model in (m.get("name"), m.get("model")):
            return round(m["size_vram"] / m["size"], 3), round(m["size"] / 1e9, 2)
    return None, None
