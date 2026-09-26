"""Turn your own documents into text the search can read. Nothing leaves this machine.

    python -m search.convert                                   # text PDFs, Word, .txt, .md
    python -m search.convert --vision-model qwen2.5vl:7b        # also photos and scans

Put originals in personal/originals/. Each becomes personal/docs/<name>.md, which
`python -m search.index --docs personal` then indexes. Originals are never changed.

- Text PDFs are read with pypdf (pip install pypdf). The rest of the project needs no
  packages; this is only for PDFs.
- Word files (.docx) are read with the standard library.
- Photos (.jpg, .png) and scanned PDF pages have no text to read. With --vision-model, a
  vision model in Ollama on this machine transcribes them. Without it they're listed as
  skipped, never sent anywhere else.

A transcription can misread a digit. Everything converted is marked as such, and anything
that matters should be checked against the original.
"""
import argparse
import base64
import datetime
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
ORIGINALS = ROOT / "personal" / "originals"
DOCS = ROOT / "personal" / "docs"
IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
MIN_PAGE_CHARS = 40  # a PDF page with less text than this is treated as a scan

TRANSCRIBE = ("Transcribe all the text in this image exactly as written, line by line, keeping "
              "numbers, dates and names exactly. Do not summarize, translate or add anything. "
              "Write [unreadable] for anything you cannot read.")


def read_docx(path):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paras = ["".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t")) for p in root.iter(f"{{{ns['w']}}}p")]
    return "\n\n".join(p for p in paras if p.strip())


def transcribe(image_bytes, model):
    from search.llm import OLLAMA, _request
    r = _request(f"{OLLAMA}/api/chat", {
        "model": model, "stream": False, "options": {"temperature": 0},
        "messages": [{"role": "user", "content": TRANSCRIBE,
                      "images": [base64.b64encode(image_bytes).decode()]}]})
    return r["message"]["content"].strip()


def read_pdf(path, vision_model):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("PDFs need pypdf: pip install pypdf")
    pages, scanned = [], []
    for n, page in enumerate(PdfReader(path).pages, 1):
        text = (page.extract_text() or "").strip()
        if len(text) >= MIN_PAGE_CHARS:
            pages.append(f"## Page {n}\n\n{text}")
        elif vision_model and page.images:
            read = "\n\n".join(transcribe(img.data, vision_model) for img in page.images)
            pages.append(f"## Page {n} (transcribed from a scan)\n\n{read}")
        else:
            scanned.append(n)
            pages.append(f"## Page {n}\n\n[scanned page, not converted: run with --vision-model]")
    return "\n\n".join(pages), scanned


def convert(path, vision_model=None):
    """Return (markdown, how, problem). problem is None when the whole file was converted."""
    ext = path.suffix.lower()
    if ext in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace"), "copied", None
    if ext == ".docx":
        return read_docx(path), "read from Word", None
    if ext == ".pdf":
        text, scanned = read_pdf(path, vision_model)
        return text, "read from PDF", f"pages {scanned} are scans" if scanned else None
    if ext in IMAGES:
        if not vision_model:
            return None, None, "a photo or scan: run with --vision-model"
        return transcribe(path.read_bytes(), vision_model), f"transcribed by {vision_model}", None
    return None, None, f"{ext} files aren't supported"


def out_name(path):
    return re.sub(r"[^\w.-]+", "-", path.stem).strip("-").lower() + ".md"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vision-model", help="an Ollama vision model for photos and scans, e.g. qwen2.5vl:7b")
    p.add_argument("--force", action="store_true", help="convert again even if the text is up to date")
    a = p.parse_args(argv)
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    files = sorted(f for f in ORIGINALS.iterdir() if f.is_file())
    if not files:
        sys.exit(f"Put your documents in {ORIGINALS} first.")
    done = 0
    for f in files:
        dest = DOCS / out_name(f)
        if dest.exists() and dest.stat().st_mtime >= f.stat().st_mtime and not a.force:
            continue
        text, how, problem = convert(f, a.vision_model)
        if text is None:
            print(f"  skipped   {f.name}: {problem}")
            continue
        header = (f"# {f.name}\n\n> Converted from {f.name} on {datetime.date.today().isoformat()} ({how}). "
                  "Check anything important against the original.\n\n")
        dest.write_text(header + text.strip() + "\n", encoding="utf-8")
        done += 1
        print(f"  converted {f.name} -> {dest.name}" + (f"  (partly: {problem})" if problem else ""))
    print(f"{done} converted. Next: python -m search.index --docs personal")


if __name__ == "__main__":
    main()
