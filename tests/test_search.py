"""Turning personal documents into searchable text, and splitting long sections."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search import convert  # noqa: E402
from search.index import MAX_CHARS, _split, chunks  # noqa: E402

try:
    import pypdf  # noqa: F401
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False


def make_pdf(path, pages):
    """A minimal PDF, one page per string; an empty string makes a page with no text."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def make_docx(path, paragraphs):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')


class Convert(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_word_paragraphs_come_through(self):
        f = self.dir / "cv.docx"
        make_docx(f, ["Usman Karamat", "", "BE Mechanical, NUST"])
        text, how, problem = convert.convert(f)
        self.assertEqual(text, "Usman Karamat\n\nBE Mechanical, NUST")
        self.assertIsNone(problem)

    @unittest.skipUnless(HAVE_PYPDF, "pypdf is not installed")
    def test_text_pdf_is_read_and_scans_are_marked(self):
        f = self.dir / "statement.pdf"
        make_pdf(f, ["Degree issued 2025, attested by HEC on 12 March 2026", ""])
        text, how, problem = convert.convert(f)
        self.assertIn("## Page 1\n\nDegree issued 2025", text)
        self.assertIn("## Page 2\n\n[scanned page, not converted", text)
        self.assertEqual(problem, "pages [2] are scans")

    def test_photos_are_never_sent_without_a_local_vision_model(self):
        f = self.dir / "cnic-front.jpg"
        f.write_bytes(b"\xff\xd8\xff")
        text, how, problem = convert.convert(f)
        self.assertIsNone(text)
        self.assertIn("--vision-model", problem)

    def test_output_names_are_safe(self):
        self.assertEqual(convert.out_name(Path("HBL Statement (Aug).pdf")), "hbl-statement-aug.md")


class Splitting(unittest.TestCase):
    def test_short_sections_are_untouched(self):
        self.assertEqual(_split("one\n\ntwo"), ["one\n\ntwo"])

    def test_long_sections_split_at_paragraphs(self):
        paras = [f"Transaction {i}: " + "x" * 300 for i in range(20)]
        parts = _split("\n\n".join(paras))
        self.assertTrue(all(len(p) <= MAX_CHARS for p in parts))
        self.assertEqual("\n\n".join(parts), "\n\n".join(paras))  # nothing lost, nothing repeated

    def test_every_piece_keeps_the_document_title(self):
        f = Path(tempfile.mkdtemp()) / "statement.md"
        f.write_text("# HBL statement\n\n" + "\n\n".join("y" * 900 for _ in range(6)), encoding="utf-8")
        pieces = list(chunks(f))
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(p["text"].startswith("# HBL statement") for p in pieces))


if __name__ == "__main__":
    unittest.main()
