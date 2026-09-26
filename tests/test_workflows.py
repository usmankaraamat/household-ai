"""The n8n workflows: the exported files, the graph, and each Code node's logic.

The JavaScript runs under Node through js_harness.js, one node at a time, with the
nodes it reads mocked. It does not replace a run in n8n against real Notion and Google
accounts; it pins down the logic those runs depend on.
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workflows import build  # noqa: E402

NODE = shutil.which("node")
HARNESS = ROOT / "tests" / "js_harness.js"

CONFIG = {"numCtx": 16384, "model": "granite4.2:8b", "disableThinking": True, "notionDatabaseId": "db123",
          "notionTitleProperty": "Name", "notionDateProperty": "Date", "notionMeetingIdProperty": "Meeting ID",
          "calendarId": "primary", "timezone": "America/Los_Angeles"}
MEETING = {"id": "a" * 32, "title": "Sunday family sync", "date": "2026-09-20", "attendees": ["Dana", "Chris"]}
EVENT = {"needed": True, "title": "Flu shots", "date": "2026-10-10", "start": "10:00", "end": "11:00"}


def run_js(code, input=None, nodes=None, run_index=0):
    out = subprocess.run([NODE, str(HARNESS)], input=json.dumps(
        {"code": code, "input": input or {}, "nodes": nodes or {}, "runIndex": run_index}),
        capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise RuntimeError(out.stderr)
    return json.loads(out.stdout)


def summary(**kw):
    s = {"meeting": MEETING, "model": "granite4.2:8b", "event": EVENT,
         "summary": {"summary": "They agreed on flu shots.", "decisions": ["Flu shots on the 10th"],
                     "action_items": [{"owner": "Dana", "task": "Book the slot", "due": "2026-09-25"}]}}
    s.update(kw)
    return s


class ExportedFiles(unittest.TestCase):
    def test_committed_json_matches_the_generator(self):
        for filename in build.WORKFLOWS:
            committed = (ROOT / "workflows" / filename).read_text(encoding="utf-8")
            self.assertEqual(committed, build.render(filename),
                             f"{filename} is stale: run python workflows/build.py")

    def test_every_connection_points_at_a_real_node(self):
        for make in build.WORKFLOWS.values():
            wf = make()
            names = {n["name"] for n in wf["nodes"]}
            for source, conn in wf["connections"].items():
                self.assertIn(source, names)
                for output in conn["main"]:
                    for target in output:
                        self.assertIn(target["node"], names)

    def test_notion_create_is_never_blindly_retried(self):
        wf = build.main_workflow()
        nodes = {n["name"]: n for n in wf["nodes"]}
        create = nodes["Create Notion page"]
        self.assertNotIn("retryOnFail", create)
        self.assertEqual(create["onError"], "continueErrorOutput")
        success, error = wf["connections"]["Create Notion page"]["main"]
        self.assertEqual(error[0]["node"], "Wait, then look again")
        self.assertEqual(wf["connections"]["Wait, then look again"]["main"][0][0]["node"], "Find existing page")

    def test_form_offers_exactly_the_allowed_decisions(self):
        wait = next(n for n in build.main_workflow()["nodes"] if n["name"] == "Wait for approval")
        offered = [v["option"] for v in wait["parameters"]["formFields"]["values"][0]["fieldOptions"]["values"]]
        self.assertEqual(offered, build.DECISIONS)


@unittest.skipUnless(NODE, "Node.js is not installed")
class OutboundCheck(unittest.TestCase):
    CODE = build.LOG + build.OUTBOUND + "const c = {}; return { out: scrub($input.first().json.text, c), counts: c };"

    def scrub(self, text):
        r = run_js(self.CODE, {"text": text})
        self.assertTrue(r["ok"], r.get("error"))
        return r["result"]

    def test_removes_sensitive_shapes(self):
        cases = {
            "SSN is 123-45-6789": "SSN",
            "card 4111 1111 1111 1111 on file": "card number",
            "Account: BLF-3310-2276": "ID or account number",
            "policy number AX-44810": "ID or account number",
            "passport 583920174 expires soon": "ID or account number",
            "routing 0210000211 and more": "ID or account number",
            "reference 4471928374": "long number",
            "Leo was born on 03/14/2019": "date of birth",
            "DOB: March 14, 2019": "date of birth",
        }
        for text, label in cases.items():
            with self.subTest(text=text):
                r = self.scrub(text)
                self.assertIn(f"[removed: {label}]", r["out"])
                self.assertEqual(r["counts"], {label: 1})

    def test_keeps_ordinary_household_text(self):
        for text in ["Call (310) 555-0199 for repairs", "Rent is $4,850, late after the 5th",
                     "Flu shots on October 10, 10-11 am", "Filter size 16x25x1, due 2026-09-01",
                     "The account holder is Dana", "4111 1111 1111 1112 fails the checksum"]:
            with self.subTest(text=text):
                r = self.scrub(text)
                self.assertEqual(r["out"], text)
                self.assertEqual(r["counts"], {})


@unittest.skipUnless(NODE, "Node.js is not installed")
class CalendarValidation(unittest.TestCase):
    CODE = build.EVENT_CHECK + "const j = $input.first().json; return checkEvent(j.ev, j.meetingDate);"

    def check(self, **changes):
        r = run_js(self.CODE, {"ev": {**EVENT, **changes}, "meetingDate": "2026-09-20"})
        self.assertTrue(r["ok"], r.get("error"))
        return r["result"]

    def test_accepts_a_real_event(self):
        self.assertIsNone(self.check()["problem"])

    def test_rejects_impossible_or_backwards_events(self):
        bad = {"impossible date": {"date": "2026-02-30"}, "not a date": {"date": "next Tuesday"},
               "impossible time": {"start": "25:61"}, "ends before it starts": {"start": "11:00", "end": "10:00"},
               "zero length": {"end": "10:00"}, "over 12 hours": {"start": "06:00", "end": "19:00"},
               "before the meeting": {"date": "2026-09-01"}, "no title": {"title": "  "}}
        for label, change in bad.items():
            with self.subTest(label):
                r = self.check(**change)
                self.assertIsNone(r["event"])
                self.assertTrue(r["problem"])

    def test_no_event_is_not_a_problem(self):
        r = run_js(self.CODE, {"ev": {"needed": False}, "meetingDate": "2026-09-20"})
        self.assertEqual(r["result"], {"event": None, "problem": None})


@unittest.skipUnless(NODE, "Node.js is not installed")
class Nodes(unittest.TestCase):
    def test_meeting_id_is_stable_and_specific(self):
        body = {"title": "Sync", "date": "2026-09-20", "transcript": "We agreed on flu shots."}
        first = run_js(build.CHECK_TRANSCRIPT, nodes={"Config": {**CONFIG, "body": body}})
        again = run_js(build.CHECK_TRANSCRIPT, nodes={"Config": {**CONFIG, "body": body}})
        other = run_js(build.CHECK_TRANSCRIPT, nodes={"Config": {**CONFIG, "body": {**body, "transcript": "Other."}}})
        ids = [r["result"][0]["json"]["meeting"]["id"] for r in (first, again, other)]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])
        self.assertRegex(ids[0], r"^[0-9a-f]{32}$")

    def test_overlong_transcript_is_refused_before_the_model(self):
        body = {"title": "Long", "date": "2026-09-20", "transcript": "word " * 40000}
        r = run_js(build.CHECK_TRANSCRIPT, nodes={"Config": {**CONFIG, "body": body}})
        self.assertFalse(r["ok"])
        self.assertIn("split the meeting", r["error"])

    def test_approval_form_shows_what_will_leave_after_removal(self):
        model = {"summary": "Dana will call about account 88120034 today.", "decisions": [],
                 "action_items": [{"owner": "Dana", "task": "Card 4111 1111 1111 1111", "due": "someday"}],
                 "event": {**EVENT, "date": "2026-02-30"}}
        r = run_js(build.CHECK_SUMMARY, {"model": "m", "message": {"content": json.dumps(model)}, "total_duration": 1e9},
                   nodes={"Check transcript": {"meeting": MEETING}})
        self.assertTrue(r["ok"], r.get("error"))
        out = r["result"][0]["json"]
        self.assertNotIn("88120034", out["review"])
        self.assertNotIn("4111", json.dumps(out))
        self.assertIn("Removed before anything leaves the house", out["review"])
        self.assertIn("not a real date", out["review"])
        self.assertIsNone(out["event"])
        self.assertEqual(out["summary"]["action_items"][0]["due"], "")
        logged = [l for l in r["logs"] if l["step"] == "summarized"][0]
        self.assertNotIn("88120034", json.dumps(logged))

    def notion(self, decision, prev=None):
        return run_js(build.BUILD_NOTION.replace("__DECISIONS__", json.dumps(build.DECISIONS)),
                      {"Decision": decision}, {"Check summary": prev or summary(), "Config": CONFIG})

    def test_unknown_or_missing_decision_writes_nothing(self):
        for decision in ["Approve", "", None, "constructor"]:
            with self.subTest(decision=decision):
                r = self.notion(decision)
                self.assertFalse(r["ok"])
                self.assertIn("Nothing was written", r["error"])

    def test_reject_writes_nothing(self):
        r = self.notion("Reject")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"], [])

    def test_approved_page_carries_the_meeting_id(self):
        r = self.notion("Approve notes only")
        self.assertTrue(r["ok"], r.get("error"))
        out = r["result"][0]["json"]
        self.assertEqual(out["notionBody"]["properties"]["Meeting ID"]["rich_text"][0]["text"]["content"], MEETING["id"])
        self.assertEqual(out["findBody"]["filter"]["rich_text"]["equals"], MEETING["id"])

    def test_guard_blocks_sensitive_text_that_skipped_the_check(self):
        leaked = summary(summary={"summary": "SSN 123-45-6789", "decisions": [], "action_items": []})
        r = self.notion("Approve notes only", leaked)
        self.assertFalse(r["ok"])
        self.assertIn("Stopped before sending", r["error"])

    def test_existing_page_is_reused(self):
        r = run_js(build.PAGE_EXISTS, {"results": [{"id": "p1", "url": "https://notion.so/p1"}]},
                   {"Build Notion page": {"notionBody": {}}, "Check summary": summary()}, run_index=1)
        self.assertEqual(r["result"][0]["json"], {"exists": True, "page": {"id": "p1", "url": "https://notion.so/p1"}})

    def test_gives_up_after_three_create_attempts(self):
        nodes = {"Build Notion page": {"notionBody": {"x": 1}}, "Check summary": summary()}
        self.assertFalse(run_js(build.PAGE_EXISTS, {"results": []}, nodes)["result"][0]["json"]["exists"])
        r = run_js(build.PAGE_EXISTS, {"results": []}, nodes, run_index=3)
        self.assertFalse(r["ok"])
        self.assertIn("will not make a duplicate", r["error"])

    def event(self, decision="Approve notes and calendar draft", page=None):
        return run_js(build.BUILD_EVENT, page or {"id": "p1", "url": "https://notion.so/p1"},
                      {"Check summary": summary(), "Config": CONFIG, "Build Notion page": {"decision": decision}})

    def test_draft_event_is_private_free_and_keyed(self):
        r = self.event()
        self.assertTrue(r["ok"], r.get("error"))
        body = r["result"][0]["json"]["calendarBody"]
        self.assertEqual(body["id"], "hh" + MEETING["id"])
        self.assertRegex(body["id"], r"^[0-9a-v]{5,1024}$")
        self.assertEqual((body["visibility"], body["transparency"], body["status"]), ("private", "transparent", "tentative"))
        self.assertNotIn("attendees", body)

    def test_notes_only_makes_no_event(self):
        self.assertEqual(self.event("Approve notes only")["result"], [])

    def test_calendar_duplicate_counts_as_done_and_errors_fail(self):
        nodes = {"Check summary": summary()}
        self.assertTrue(run_js(build.CHECK_EVENT, {"statusCode": 409}, nodes)["ok"])
        self.assertTrue(run_js(build.CHECK_EVENT, {"statusCode": 200, "body": {}}, nodes)["ok"])
        r = run_js(build.CHECK_EVENT, {"statusCode": 500}, nodes)
        self.assertFalse(r["ok"])
        self.assertIn("cannot be created twice", r["error"])


if __name__ == "__main__":
    unittest.main()
