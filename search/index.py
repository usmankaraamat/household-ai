"""Build the search index over the household documents.

Each document is split at its "## " headings, so a chunk is one section with the
document's title on top. The index holds the text and embeddings of private
documents, so it stays on the home machine: it's gitignored and never synced.

    python -m search.index
"""
import json
from pathlib import Path

from search.llm import embed

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "sample-docs"
INDEX = ROOT / "search" / "index.json"
EMBED_MODEL = "nomic-embed-text"


def doc_prefix(model):
    # nomic-embed-text expects task prefixes on documents and queries.
    return ("search_document: ", "search_query: ") if "nomic" in model else ("", "")


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
        body = "\n".join(section).strip()
        text = body if body.startswith(title) else f"{title}\n\n{body}"
        yield {"source": path.name, "text": text}


def build(embed_model=EMBED_MODEL):
    items = [c for p in sorted(DOCS.glob("*.md")) for c in chunks(p)]
    prefix, _ = doc_prefix(embed_model)
    vectors = embed([prefix + c["text"] for c in items], model=embed_model)
    for c, v in zip(items, vectors):
        c["vec"] = v
    INDEX.write_text(json.dumps({"embed_model": embed_model, "chunks": items}), encoding="utf-8")
    return items


def load():
    if not INDEX.exists():
        build()
    return json.loads(INDEX.read_text(encoding="utf-8"))


if __name__ == "__main__":
    items = build()
    print(f"Indexed {len(items)} sections from {len({c['source'] for c in items})} documents -> {INDEX}")
