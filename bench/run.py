"""Accuracy benchmark: the same questions, the same retrieved sections, each model.

    python -m bench.run                       # every model in bench/models.json
    python -m bench.run --model granite4.2:8b

Retrieval runs once per question and is shared by all models, so a wrong answer
is the model's fault, not the search's. Results go to bench/results/.
"""
import argparse
import datetime
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search.ask import answer, retrieve  # noqa: E402
from search.index import load  # noqa: E402
from search.llm import chat, gpu_share  # noqa: E402

HERE = Path(__file__).resolve().parent
TODAY = "2026-09-26"  # fixed, so answers about dates don't drift between runs


def norm(text):
    text = text.lower().replace(",", "").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text)


def score(q, r):
    a = norm(r["answer"])
    refused = "not found" in a
    if q["kind"] == "unanswerable":
        return {"correct": refused, "cited_ok": None}
    correct = not refused and all(any(alt in a for alt in group) for group in q["expect"])
    return {"correct": correct, "cited_ok": set(q["sources"]) <= set(r["cited"])}


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def run_model(m, questions, hits, args):
    kw = {"backend": args.backend, "num_ctx": args.num_ctx, "think": m.get("think")}
    chat([{"role": "user", "content": "Reply with OK."}], m["model"], **kw)  # load it before timing
    share, size_gb = gpu_share(m["model"]) if args.backend == "ollama" else (None, None)
    rows = []
    for q in questions:
        r = answer(q["q"], m["model"], hits=hits[q["id"]], today=TODAY, **kw)
        r.update(score(q, r), id=q["id"], kind=q["kind"])
        rows.append(r)
        print(f"  {q['id']} {'PASS' if r['correct'] else 'FAIL'}  {r['answer'][:90]!r}")
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["correct"])
    cites = [r["cited_ok"] for r in rows if r["cited_ok"] is not None]
    summary = {
        "label": m["label"], "model": m["model"],
        "accuracy": f"{sum(r['correct'] for r in rows)}/{len(rows)}",
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in by_kind.items()},
        "citations_ok": f"{sum(cites)}/{len(cites)}",
        "cut_off": sum(r["stats"].get("stop") == "length" for r in rows),
        "median_seconds": median(r["stats"]["seconds"] for r in rows),
        "median_prefill_tps": median(r["stats"]["prefill_tps"] for r in rows),
        "median_decode_tps": median(r["stats"]["decode_tps"] for r in rows),
        "loaded_gb": size_gb, "on_gpu": share,
    }
    return summary, rows


def report(summaries, retrieval_recall, args):
    lines = [
        f"# Accuracy benchmark — {datetime.date.today().isoformat()}",
        "",
        f"{args.n} questions · top-{args.k} retrieval · num_ctx {args.num_ctx} · backend {args.backend} · temperature 0",
        f"Retrieval found every needed document for {retrieval_recall} questions (same sections given to every model).",
        "",
        "| Model | Correct | Facts | Two-doc | Trap | Says 'not found' when it should | Citations right | Cut off | Median s | Prefill tok/s | Decode tok/s | Loaded GB | On GPU |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        k = s["by_kind"]
        gpu = f"{s['on_gpu']:.0%}" if s["on_gpu"] is not None else "-"
        lines.append(f"| {s['label']} | {s['accuracy']} | {k.get('fact', '-')} | {k.get('multi', '-')} | "
                     f"{k.get('trap', '-')} | {k.get('unanswerable', '-')} | {s['citations_ok']} | {s['cut_off']} | "
                     f"{s['median_seconds']} | {s['median_prefill_tps']} | {s['median_decode_tps']} | "
                     f"{s['loaded_gb']} | {gpu} |")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", action="append", help="model name; repeat to test several (default: models.json)")
    p.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--num-ctx", type=int, default=8192)
    args = p.parse_args()

    models = json.loads((HERE / "models.json").read_text())
    if args.model:
        known = {m["model"]: m for m in models}
        models = [known.get(name, {"model": name, "label": name}) for name in args.model]
    questions = [json.loads(l) for l in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    args.n = len(questions)

    index = load()
    hits = {q["id"]: retrieve(q["q"], index, k=args.k) for q in questions}
    answerable = [q for q in questions if q["sources"]]
    found = sum(set(q["sources"]) <= {h["source"] for h in hits[q["id"]]} for q in answerable)
    retrieval_recall = f"{found}/{len(answerable)}"

    summaries, detail = [], {}
    for m in models:
        print(f"== {m['label']}")
        s, rows = run_model(m, questions, hits, args)
        summaries.append(s)
        detail[m["model"]] = rows

    out = HERE / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    (out / f"accuracy-{stamp}.json").write_text(json.dumps(
        {"args": vars(args), "retrieval_recall": retrieval_recall, "summaries": summaries, "detail": detail},
        indent=1), encoding="utf-8")
    md = report(summaries, retrieval_recall, args)
    (out / "accuracy-latest.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
