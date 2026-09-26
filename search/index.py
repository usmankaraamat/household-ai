"""Build the search index over the household documents.

Each document is split at its "## " headings, so a chunk is one section with the
document's title on top. A section longer than a couple of paragraphs' worth (a converted
bank statement, say) is split again at paragraph breaks. The index holds the text and
embeddings of private documents, so it stays on the home machine: it's gitignored and
never synced.

    python -m search.index                   # the made-up sample documents
    python -m search.index --docs personal   # your own documents, in personal/docs/

Each set of documents has its own index, so your own papers never mix with the samples
the benchmark runs on.
"""
import argparse
import json
from pathlib import Path

from search.llm import embed

ROOT = Path(__file__).resolve().parent.parent
SETS = {
    "sample": (ROOT / "data" / "sample-docs", ROOT / "search" / "index.json"),
    # personal/ is gitignored as a whole: originals, converted text and this index.
    "personal": (ROOT / "personal" / "docs", ROOT / "personal" / "index.json"),
}
EMBED_MODEL = "nomic-embed-text"
MAX_CHARS = 2000  # roughly 500 tokens: long enough for a section, short enough to embed well


def doc_prefix(model):
    # nomic-embed-text expects task prefixes on documents and queries.
    return ("search_document: ", "search_query: ") if "nomic" in model else ("", "")


def _split(body, limit=MAX_CHARS):
    """Split an over-long section at blank lines, keeping paragraphs whole where possible."""
    if len(body) <= limit:
        return [body]
    parts, current = [], ""
    for para in body.split("\n\n"):
        while len(para) > limit:  # one enormous paragraph: cut it, there's nothing better
            parts.append(para[:limit])
            para = para[limit:]
        if current and len(current) + len(para) + 2 > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    return parts + ([current] if current else [])


def chunks(path):
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.startswith("> Fabricated")]
    title = next((l for l in lines if l.startswith("# ")), path.stem)
    sections, current = [], []
    for line in lines:
        if line.startswith("## ") and current:
            sections.append(current)
            current = []
        current.append(line)
    sections.append(current)
    for section in sections:
        for body in _split("\n".join(section).strip()):
            text = body if body.startswith(title) else f"{title}\n\n{body}"
            yield {"source": path.name, "text": text}


def build(docs="sample", embed_model=EMBED_MODEL):
    folder, index = SETS[docs]
    items = [c for p in sorted(folder.glob("*.md")) for c in chunks(p)]
    if not items:
        raise SystemExit(f"No .md documents in {folder}. For your own files, run python -m search.convert first.")
    prefix, _ = doc_prefix(embed_model)
    vectors = embed([prefix + c["text"] for c in items], model=embed_model)
    for c, v in zip(items, vectors):
        c["vec"] = v
    index.write_text(json.dumps({"embed_model": embed_model, "chunks": items}), encoding="utf-8")
    return items


def load(docs="sample"):
    index = SETS[docs][1]
    if not index.exists():
        build(docs)
    return json.loads(index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--docs", choices=sorted(SETS), default="sample")
    a = p.parse_args()
    items = build(a.docs)
    print(f"Indexed {len(items)} sections from {len({c['source'] for c in items})} documents -> {SETS[a.docs][1]}")
