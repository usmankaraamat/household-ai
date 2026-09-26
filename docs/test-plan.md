# Test plan: real meetings and real documents

The automated tests (`python -m unittest discover -s tests`) check the logic with no accounts
and no model. This plan checks the whole system for real: a meeting recorded by Fathom
arrives, is summarized at home, is approved, and lands in Notion and Google Calendar; and
your own documents are searched on the home machine.

Every sensitive value below is made up. Say these, not your own numbers.

## Before you start

1. **Pin n8n.** In `.env`, set `N8N_VERSION` to the version you're running
   (`docker compose exec n8n n8n --version`). Compose won't start without it.
2. **Restart n8n** with `docker compose up -d`. The compose file now also allows the
   `crypto` module, which the meeting ID needs.
3. **Notion.** In the meeting-notes database, add a **Text** property named **Meeting ID**.
4. **Import all three workflows** from `workflows/`: meeting notes, the Fathom poller and
   the error handler. Importing replaces the earlier versions. Then attach credentials to
   the new nodes: Notion on **Find existing page** and **Create Notion page**, Google on
   **Create draft event**.
5. **Fathom key.** In n8n, go to **Credentials** → new **Header Auth**. Name: `X-Api-Key`.
   Value: the key from Fathom's API settings. Attach it to **Ask Fathom for recent
   meetings**. The webhook secret isn't used: Fathom can't reach n8n here, so n8n asks
   Fathom instead.
6. **Time zone.** For testing in Pakistan, set `timezone` to `Asia/Karachi` in both the
   meeting workflow's **Config** node and the poller's **Poller config** node. Otherwise a
   4 pm appointment lands at 4 pm Los Angeles time.
7. **Publish** the error handler and the meeting workflow, then the poller. The poller only
   runs on its schedule, and only remembers what it sent, when it's published. The meeting
   workflow's webhook only answers the poller when it's published.
8. **Optional:** install Tailscale on the PC and your phone, so the approval link (a
   `localhost` address) opens on the phone too.

## Test A: meeting notes

Hold a short dummy meeting that Fathom records: a Google Meet call between your phone and
laptop, or Fathom's iPhone app in person. Say every line in this script at some point:

| Say | Expected in the approval form and in Notion |
|---|---|
| "My CNIC is 35202-1234567-1" | `[removed: CNIC]` |
| "The card is 4111 1111 1111 1111" | `[removed: card number]` |
| "Passport number AB1234567" | `passport number [removed: ID or account number]` |
| "IBAN PK36SCBL0000001123456702" | `[removed: IBAN]` |
| "I was born on 03/14/1998" | `born on [removed: date of birth]` |
| "Dentist next Thursday, four to five pm" | A private `[Draft] Dentist` on the right Thursday, 16:00–17:00 |
| "Send the report by the end of next week" | An action item with a due date. **Check the date by hand:** this is where the model went wrong before |

Fathom decides how a spoken number is written: `35202-1234567-1`, or with spaces, or in
words. **Look at the transcript in Fathom and note exactly how each number came out.** The
check matches written shapes, so a number written in an unusual way may pass straight
through. That's worth knowing and worth a new pattern and test, not a surprise in Notion.

Then check each step:

- [ ] Within about 10 minutes, the poller's run shows the meeting as new and sent
      (n8n → **Executions**, or `fathom_checked` / `fathom_sent` in `logs/household.jsonl`).
      If it says `fathom_transcript_not_ready`, wait for the next check.
- [ ] The meeting workflow's run is waiting for approval, and `awaiting_approval` in the log
      has the link.
- [ ] The approval form says what was removed, and none of the numbers above appear in it.
- [ ] Approve notes and calendar draft. The Notion page appears on your phone with no
      numbers in it and a filled-in **Meeting ID**.
- [ ] The calendar draft is private, shows the time as free, and has no guests.
- [ ] Nothing in `logs/household.jsonl` contains the numbers you said. It records steps and
      counts, not content.

## Failure tests

- [ ] **Reject** a second dummy meeting. Nothing is written to Notion or the calendar.
- [ ] **Same meeting twice:** send the sample meeting with the `curl` command in the README,
      approve it (notes and calendar), then send it again and approve that too. Both runs
      get the same meeting ID, so the second logs `notion_page_existed` and
      `draft already existed`, and there's still only one page and one event.
- [ ] **Power cut while waiting:** start a meeting's run, shut the PC down before approving,
      start it again, then open the approval link. It still works.
- [ ] **Poller while off:** record a meeting while the PC is off. After it's back on, the
      next check picks the meeting up (it looks back 48 hours).
- [ ] **Too long:** send a transcript longer than the model's setting with the manual
      command in the README. The error names the size and says what to do.

## Test B: your own documents

Nothing here touches n8n, Notion or the cloud. It all stays on the PC.

1. `pip install pypdf`, for PDFs.
2. For photos and scanned PDFs, pull a vision model that fits in 8 GB. Check the name on
   ollama.com first, e.g. `ollama pull qwen2.5vl:7b`.
3. Copy a few documents into `personal/originals/`. The whole `personal/` folder is
   gitignored, so it can never reach GitHub.
4. `python -m search.convert --vision-model qwen2.5vl:7b`
5. **Open each file in `personal/docs/` and compare it with the original,** digit by digit
   for ID numbers and dates. A vision model can misread a 3 as an 8, and search will then
   repeat the mistake confidently. Note every misread.
6. `python -m search.index --docs personal`
7. Ask about ten questions with `python -m search.ask "…" --docs personal`, including:
   - two whose answer is in exactly one document (passport expiry, degree issue date)
   - one that needs two documents
   - two the documents can't answer. Expect `NOT FOUND`.

## What to write down

| | Result |
|---|---|
| How Fathom wrote each spoken number | |
| Removed values that still reached Notion | |
| Correct calendar date and time | |
| Due-date mistakes | |
| Duplicates after a retry | |
| Approval survived a restart | |
| Conversion misreads (per document) | |
| Correct answers / questions asked | |
| Correct `NOT FOUND`s | |
| Minutes from the end of the meeting to the Notion page | |

Anything that fails here gets a test in `tests/` before it's fixed, so it can't come back.
