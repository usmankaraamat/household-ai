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

from search.ask import answer, citations, retrieve  # noqa: E402
from search.index import load  # noqa: E402
from search.llm import chat, gpu_share, strip_thinking  # noqa: E402

HERE = Path(__file__).resolve().parent
TODAY = "2026-09-26"  # fixed, so answers about dates don't drift between runs


def norm(text):
    text = text.lower().replace(",", "").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text)


def refused(answer):
    """A refusal is NOT FOUND and nothing else, apart from a Sources line. "NOT FOUND, but
    it's probably $500" is a guess, and must not pass as a refusal."""
    body = re.sub(r"(?im)^\s*sources?:.*$", "", answer)
    return re.sub(r"[\s.*_`]", "", body).lower() == "notfound"


def score(q, r):
    """Correct means every `expect` group has a match and no `forbid` phrase appears.
    `forbid` catches answers that contain the right words next to a wrong value, such as
    the right filter size with the wrong due date."""
    a = norm(r["answer"])
    invented = len(r.get("invented_citations") or [])
    if q["kind"] == "unanswerable":
        return {"correct": refused(r["answer"]), "cited_ok": None, "invented": invented}
    correct = (not refused(r["answer"]) and "not found" not in a
               and all(any(alt in a for alt in group) for group in q["expect"])
               and not any(bad in a for bad in q.get("forbid", [])))
    return {"correct": correct, "cited_ok": set(q["sources"]) <= set(r["cited"]), "invented": invented}


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
    return summarize(m, rows, loaded_gb=size_gb, on_gpu=share), rows


def summarize(m, rows, **measured):
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["correct"])
    cites = [r["cited_ok"] for r in rows if r["cited_ok"] is not None]
    return {
        "label": m["label"], "model": m["model"],
        "accuracy": f"{sum(r['correct'] for r in rows)}/{len(rows)}",
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in by_kind.items()},
        "citations_ok": f"{sum(cites)}/{len(cites)}",
        "invented_citations": sum(r.get("invented", 0) for r in rows),
        "leaked_thinking": sum(bool(r["stats"].get("leaked_thinking")) for r in rows),
        "cut_off": sum(r["stats"].get("stop") == "length" for r in rows),
        "median_seconds": median(r["stats"]["seconds"] for r in rows),
        "median_prefill_tps": median(r["stats"]["prefill_tps"] for r in rows),
        "median_decode_tps": median(r["stats"]["decode_tps"] for r in rows),
        **measured,
    }


def rescore(path, questions):
    """Score saved answers again with the current questions and rules. No model runs, so a
    stricter scorer can be applied to old results and the difference is visible."""
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in questions}
    summaries = []
    for old in saved["summaries"]:
        rows = saved["detail"][old["model"]]
        for r in rows:
            r["answer"], leaked = strip_thinking(r["answer"])
            r["stats"]["leaked_thinking"] = r["stats"].get("leaked_thinking") or leaked
            cited, invented = citations(r["answer"], r["retrieved"])
            r.update(cited=cited, invented_citations=invented)
            r.update(score(by_id[r["id"]], r))
        summaries.append(summarize(old, rows, loaded_gb=old.get("loaded_gb"), on_gpu=old.get("on_gpu")))
    saved.update(summaries=summaries, rescored=datetime.date.today().isoformat())
    return saved


def report(summaries, retrieval_recall, args, run_date=None, rescored=None):
    title = f"# Accuracy benchmark — {run_date or datetime.date.today().isoformat()}"
    lines = [
        title + (f" (answers re-scored {rescored} with stricter rules)" if rescored else ""),
        "",
        f"{args['n']} questions · top-{args['k']} retrieval · num_ctx {args['num_ctx']} · backend {args['backend']} · temperature 0",
        f"Retrieval found every needed document for {retrieval_recall} questions (same sections given to every model).",
        "Correct means every required fact is present, no known-wrong value appears, and a refusal is exactly NOT FOUND.",
        "",
        "| Model | Correct | Facts | Two-doc | Trap | Says 'not found' when it should | Citations right | Invented citations | Leaked reasoning | Cut off | Median s | Prefill tok/s | Decode tok/s | Loaded GB | On GPU |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        k = s["by_kind"]
        gpu = f"{s['on_gpu']:.0%}" if s.get("on_gpu") is not None else "-"
        lines.append(f"| {s['label']} | {s['accuracy']} | {k.get('fact', '-')} | {k.get('multi', '-')} | "
                     f"{k.get('trap', '-')} | {k.get('unanswerable', '-')} | {s['citations_ok']} | "
                     f"{s.get('invented_citations', '-')} | {s.get('leaked_thinking', '-')} | {s['cut_off']} | "
                     f"{s['median_seconds']} | {s['median_prefill_tps']} | {s['median_decode_tps']} | "
                     f"{s.get('loaded_gb')} | {gpu} |")
    return "\n".join(lines) + "\n"


def load_questions():
    return [json.loads(l) for l in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", action="append", help="model name; repeat to test several (default: models.json)")
    p.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--num-ctx", type=int, default=8192)
    p.add_argument("--rescore", metavar="RESULTS_JSON", help="score saved answers again; no model is run")
    args = p.parse_args()
    questions = load_questions()
    out = HERE / "results"

    if args.rescore:
        src = Path(args.rescore)
        saved = rescore(src, questions)
        dest = src.with_name(src.stem + ".rescored.json")
        dest.write_text(json.dumps(saved, indent=1), encoding="utf-8")
        run_date = "-".join(src.stem.split("-")[1:4])
        md = report(saved["summaries"], saved["retrieval_recall"], saved["args"], run_date, saved["rescored"])
        (out / "accuracy-latest.md").write_text(md, encoding="utf-8")
        print(md)
        return

    models = json.loads((HERE / "models.json").read_text())
    if args.model:
        known = {m["model"]: m for m in models}
        models = [known.get(name, {"model": name, "label": name}) for name in args.model]
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

    out.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    (out / f"accuracy-{stamp}.json").write_text(json.dumps(
        {"args": vars(args), "retrieval_recall": retrieval_recall, "summaries": summaries, "detail": detail},
        indent=1), encoding="utf-8")
    md = report(summaries, retrieval_recall, vars(args))
    (out / "accuracy-latest.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
