"""Ask a question of the household documents, answered by a local model.

    python -m search.ask "When is Leo's next flu shot due?" --model granite4.2:8b

The question, the retrieved sections and the answer never leave this machine.
"""
import argparse
import datetime
import math
import re

from search.index import doc_prefix, load
from search.llm import chat, embed

SYSTEM = """You answer questions for a family, using only excerpts from their household documents.
Today is {today}.

Rules:
- Use only the excerpts. If they do not contain the answer, reply with exactly: NOT FOUND
- Answer in one to three short sentences, with the specific numbers, dates and names.
- End with the documents you used, in square brackets, like: Sources: [lease.md] [passports.md]"""


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def retrieve(question, index=None, k=5):
    index = index or load()
    _, prefix = doc_prefix(index["embed_model"])
    qvec = embed([prefix + question], model=index["embed_model"])[0]
    ranked = sorted(index["chunks"], key=lambda c: _cosine(qvec, c["vec"]), reverse=True)
    return ranked[:k]


def citations(text, retrieved):
    """Split the answer's [file.md] citations into ones search actually returned and ones the
    model invented. An invented source is worse than none: it looks checkable and isn't."""
    named = sorted(set(re.findall(r"\[([\w.-]+\.md)\]", text)))
    return [n for n in named if n in retrieved], [n for n in named if n not in retrieved]


def answer(question, model, hits=None, today=None, **chat_kw):
    hits = hits if hits is not None else retrieve(question)
    excerpts = "\n\n".join(f'<excerpt source="{h["source"]}">\n{h["text"]}\n</excerpt>' for h in hits)
    messages = [
        {"role": "system", "content": SYSTEM.format(today=today or datetime.date.today().isoformat())},
        {"role": "user", "content": f"{excerpts}\n\nQuestion: {question}"},
    ]
    text, stats = chat(messages, model, **chat_kw)
    retrieved = [h["source"] for h in hits]
    cited, invented = citations(text, retrieved)
    return {"answer": text, "cited": cited, "invented_citations": invented,
            "retrieved": retrieved, "stats": stats}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    p.add_argument("--model", default="granite4.2:8b")
    p.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    p.add_argument("--k", type=int, default=5, help="sections to retrieve")
    p.add_argument("--think", action="store_true", help="let thinking models reason first (slower)")
    a = p.parse_args()
    think = None if a.backend != "ollama" else a.think
    r = answer(a.question, a.model, hits=retrieve(a.question, k=a.k), backend=a.backend, think=think)
    if not r["answer"] and r["stats"].get("stop") == "length":
        r["answer"] = "(No answer: the model ran out of output tokens, probably while thinking.)"
    print(r["answer"])
    if r["invented_citations"]:
        print(f"\nWARNING: cites {', '.join(r['invented_citations'])}, which search did not return. "
              "Don't rely on this answer without opening the documents.")
    s = r["stats"]
    print(f"\n[{s['seconds']}s · {s['prompt_tokens']} prompt tokens · {s['decode_tps']} tok/s]")
