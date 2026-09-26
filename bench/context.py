"""Usable-context benchmark: how much text can each model take before it misses things?

A single sentence (the "needle") is hidden at the start, middle and end of a
long block of household documents, at several context sizes. For each size we
record whether the model finds it, how fast it reads and answers, and how much
of the model still fits in VRAM, because the memory for the context grows with
its size.

The last test overfills the context on purpose. By default Ollama cuts off the
oldest part of an over-long prompt without an error, and this shows what that
looks like.

    python -m bench.context
    python -m bench.context --sizes 4096 8192 --model granite4.2:8b
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search.llm import chat, gpu_share  # noqa: E402

HERE = Path(__file__).resolve().parent
NEEDLE = "Household note: the spare key to the garden shed is hidden inside the blue ceramic flowerpot by the back door."
QUESTION = "Where is the spare key to the garden shed hidden?"
SYSTEM = "Answer the question using only the text provided. If the answer is not in the text, reply with exactly: NOT FOUND"
CHARS_PER_TOKEN = 3.6  # rough for these documents; the real count comes back from the server


def paragraphs():
    docs = sorted((ROOT / "data" / "sample-docs").glob("*.md"))
    text = "\n\n".join(p.read_text(encoding="utf-8") for p in docs)
    return [p for p in text.split("\n\n") if p.strip() and not p.startswith("> Fabricated")]


def haystack(target_tokens, depth):
    source, out, i = paragraphs(), [], 0
    while sum(len(p) for p in out) < target_tokens * CHARS_PER_TOKEN:
        out.append(source[i % len(source)])
        i += 1
    out.insert(int(len(out) * depth), NEEDLE)
    return "\n\n".join(out)


def probe(model, num_ctx, fill_tokens, depth, think):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{haystack(fill_tokens, depth)}\n\nQuestion: {QUESTION}"}]
    text, stats = chat(messages, model, num_ctx=num_ctx, think=think, max_tokens=80)
    share, size_gb = gpu_share(model)
    return {"num_ctx": num_ctx, "fill_tokens": fill_tokens, "depth": depth, "found": "flowerpot" in text.lower(),
            "answer": text[:120], "on_gpu": share, "loaded_gb": size_gb, **stats}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", action="append")
    p.add_argument("--sizes", type=int, nargs="+", default=[4096, 8192, 16384, 32768])
    p.add_argument("--depths", type=float, nargs="+", default=[0.1, 0.5, 0.9])
    args = p.parse_args()

    models = json.loads((HERE / "models.json").read_text())
    if args.model:
        known = {m["model"]: m for m in models}
        models = [known.get(name, {"model": name, "label": name}) for name in args.model]

    rows = []
    for m in models:
        print(f"== {m['label']}")
        for size in args.sizes:
            for depth in args.depths:
                r = probe(m["model"], size, int(size * 0.8), depth, m.get("think"))
                rows.append({"label": m["label"], "test": "fits", **r})
                print(f"  ctx {size:>6} depth {depth:.1f}: {'found' if r['found'] else 'MISSED'}  "
                      f"prompt {r['prompt_tokens']} tok, prefill {r['prefill_tps']} tok/s, "
                      f"decode {r['decode_tps']} tok/s, on GPU {r['on_gpu']}")
        # Deliberate overflow: twice as much text as the context holds, needle near the start.
        r = probe(m["model"], args.sizes[0], args.sizes[0] * 2, 0.1, m.get("think"))
        rows.append({"label": m["label"], "test": "overflow", **r})
        print(f"  OVERFLOW ctx {args.sizes[0]} with ~{args.sizes[0] * 2} tokens: "
              f"{'found' if r['found'] else 'MISSED'}, server counted {r['prompt_tokens']} prompt tokens, "
              f"answer {r['answer']!r}")

    out = HERE / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    (out / f"context-{stamp}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    lines = [f"# Usable-context benchmark — {datetime.date.today().isoformat()}", "",
             "Needle found at depths " + ", ".join(f"{d:.0%}" for d in args.depths) +
             " of the context, which is filled to about 80%.", "",
             "| Model | num_ctx | Found | Prefill tok/s | Decode tok/s | Loaded GB | On GPU |", "|---|---|---|---|---|---|---|"]
    for m in models:
        for size in args.sizes:
            rs = [r for r in rows if r["label"] == m["label"] and r["num_ctx"] == size and r["test"] == "fits"]
            best = lambda k: max((r[k] for r in rs if r[k] is not None), default=None)  # noqa: E731
            gpu = min((r["on_gpu"] for r in rs if r["on_gpu"] is not None), default=None)
            lines.append(f"| {m['label']} | {size} | {sum(r['found'] for r in rs)}/{len(rs)} | {best('prefill_tps')} | "
                         f"{best('decode_tps')} | {rs[-1]['loaded_gb']} | {f'{gpu:.0%}' if gpu is not None else '-'} |")
    lines += ["", "**Overflow test** (twice the text the context holds, needle 10% in):", ""]
    for r in (r for r in rows if r["test"] == "overflow"):
        lines.append(f"- {r['label']}: sent ~{r['fill_tokens']} tokens into num_ctx {r['num_ctx']}; "
                     f"server processed {r['prompt_tokens']}; needle {'found' if r['found'] else 'missed'}; "
                     f"answer: \"{r['answer']}\"")
    md = "\n".join(lines) + "\n"
    (out / "context-latest.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
