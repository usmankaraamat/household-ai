"""Scoring rules for the accuracy benchmark, and document search's citation check."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.run import load_questions, refused, rescore, score  # noqa: E402
from search.ask import citations  # noqa: E402
from search.llm import strip_thinking  # noqa: E402

SAVED = ROOT / "bench" / "results" / "accuracy-2026-09-26-1943.json"
FILTER = {"kind": "multi", "expect": [["overdue"], ["16x25x1"]], "sources": ["hvac-service-record.md"],
          "forbid": ["september 4"]}


def row(answer, cited=("hvac-service-record.md",)):
    return {"answer": answer, "cited": list(cited), "invented_citations": []}


class Refusals(unittest.TestCase):
    def test_a_bare_refusal_counts(self):
        for text in ["NOT FOUND", "NOT FOUND.", "**NOT FOUND**", "NOT FOUND\nSources: [lease.md]"]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_a_refusal_followed_by_a_guess_does_not(self):
        for text in ["NOT FOUND, but it is probably $500", "Not found in the lease. The deductible is $500."]:
            with self.subTest(text=text):
                self.assertFalse(refused(text))


class Scoring(unittest.TestCase):
    def test_right_words_with_a_wrong_value_fail(self):
        self.assertFalse(score(FILTER, row("Yes, overdue: it was due September 4. Size 16x25x1."))["correct"])
        self.assertTrue(score(FILTER, row("Yes, overdue since September 1. Size 16x25x1."))["correct"])

    def test_hedged_answer_is_not_a_correct_answer(self):
        self.assertFalse(score(FILTER, row("NOT FOUND, but probably overdue, 16x25x1"))["correct"])

    def test_saved_results_under_the_strict_rules(self):
        saved = rescore(SAVED, load_questions())
        got = {s["model"]: (s["accuracy"], s["by_kind"]["multi"], s["leaked_thinking"], s["invented_citations"])
               for s in saved["summaries"]}
        self.assertEqual(got["granite4.2:8b"], ("20/21", "3/4", 1, 0))
        self.assertEqual(got["hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M"], ("19/21", "2/4", 0, 0))


class Citations(unittest.TestCase):
    def test_sources_search_never_returned_are_flagged(self):
        cited, invented = citations("Rent is $4,850. Sources: [lease.md] [tax-return.md]", ["lease.md", "passports.md"])
        self.assertEqual((cited, invented), (["lease.md"], ["tax-return.md"]))


class LeakedReasoning(unittest.TestCase):
    def test_paired_and_unpaired_reasoning_are_removed(self):
        self.assertEqual(strip_thinking("<think>hmm</think> Call 555-0177."), ("Call 555-0177.", True))
        self.assertEqual(strip_thinking("Maybe lease.md? Yes. </think> Call 555-0177."), ("Call 555-0177.", True))
        self.assertEqual(strip_thinking("Call 555-0177."), ("Call 555-0177.", False))


if __name__ == "__main__":
    unittest.main()
