# Household runbook

For the family. This covers what the system does, what you do, and what to do when
something looks wrong. It covers the first piece only: **meeting notes** and **document
search**. Each new piece gets its own section here.

## What it does, in three sentences

After a meeting, the transcript goes to the computer at home, which writes a short summary
and a list of who does what. You get a link, read the summary, and approve or reject it.
Once you approve, the summary goes to Notion and any agreed appointment appears as a
**draft** in Google Calendar: private, with no guests, and not blocking the time until you
accept it.

The full transcript never leaves the house. See [data-boundary.md](data-boundary.md) for
what goes where and why.

## Every day

### Approving meeting notes

1. Open the approval link. *(In this first version the link is only in the activity log.
   Sending it to your phone is the next step.)* To print the newest one:

       grep -o '"approve_url":"[^"]*"' logs/household.jsonl | tail -1

   Check the number after `form-waiting/` is the newest run. An older tab left open still
   shows a form, but answering it does nothing once that run has finished.
2. Read the summary, and **check dates and times especially.** A calendar draft's date is
   worked out from the words said ("tomorrow", "Friday", "October 10"), and the form shows
   those words next to the date: check they match. Vague deadlines like "end of next week"
   are left without a date on purpose, so you choose one. What you see is exactly what will
   be sent. If an account number, card number or date of birth came up in the meeting, it
   has already been removed, and the page says so.
3. Choose one:
   - **Approve notes and calendar draft**: the Notion page is created, and so is a draft
     event.
   - **Approve notes only**: just the Notion page.
   - **Reject**: nothing is written anywhere. Add a note saying why, if you like.
4. The calendar draft is marked *tentative*, has no guests, and starts with **[Draft]**. It
   invites nobody. Its details are private, so anyone the calendar is shared with sees only
   that something is there, and it shows the time as free. Open it, fix anything, add
   people, set it to busy, and save it as a real event.

Nobody has to approve right away. The request waits until someone does, even if the
computer restarts.

### Asking a question about the family's documents

*(In this first version you ask from the Terminal. A simple chat window is planned.)*

    python -m search.ask "When does Ava's EpiPen expire?"

The answer names the document it came from, like `[school-enrollment-ava.md]`. **For
anything that matters, open that document and check.** If the documents don't contain
the answer, it replies `NOT FOUND` instead of guessing.

### Adding a document

Put the file in the documents folder, then rebuild the search index:

    python -m search.index

It takes a few seconds. The index stays on the home computer.

## When something looks wrong

| What you notice | What's going on | What to do |
|---|---|---|
| No approval link, and nothing in Notion | The home computer is off or asleep, or n8n isn't running | Check the computer is on. Open http://localhost:5678. If it doesn't load, restart the computer and wait 2 minutes: everything starts on its own |
| The link opens, but the page is an error | The request was already answered, or it's an old link | Open n8n, then **Executions**, to see what happened to it |
| "This transcript is about N tokens and the model is set to …" | The meeting is longer than the current setting allows | Ask the person who looks after the system to raise `numCtx`, or send the meeting in two halves |
| Calendar drafts stopped appearing, but Notion pages still do | Google's sign-in has expired | In n8n, go to **Credentials**, open **Google Calendar account**, click **Sign in with Google** again, then retry the failed run |
| "Could not find database" | The Notion database was moved or stopped being shared | In Notion, open the database, click **•••**, then **Connections**, and add **household-ai** |
| "Could not find property with name or id: Meeting ID" | The Notion database is missing the column retries rely on | In Notion, click the **+** at the end of the database's column headers (not **+ New page**, which adds a row), choose **Text**, name it **Meeting ID**, then retry the run |
| The same Fathom meeting asks for approval twice | The poller was run by hand with **Execute workflow**. n8n doesn't remember what a hand run sent, so the next scheduled check sends it again | Approving both is safe: they share a Meeting ID, so there's still one page and one draft. Don't run the poller by hand; it checks every 10 minutes on its own |
| "No calendar draft: … couldn't tell which day …" | The meeting named a day in words the system doesn't turn into a date | Choose **Approve notes only** and add the event yourself |
| "Stopped before sending: the payload still contains …" | Something that looks like an ID or account number was about to leave the house | Nothing was written. Tell the person who looks after the system |
| "… is not one of the approval choices" | The approval form was answered in an unexpected way | Nothing was written. Retry the run and choose one of the three options |
| Answers are very slow | The model is dealing with a lot of text at once, or something else is using the computer heavily | Wait. If it happens often, tell the person who looks after the system |
| A meeting from Fathom hasn't shown up after 20 minutes | Fathom hasn't finished the transcript yet, or the poller isn't published | Look for `fathom_transcript_not_ready` in the log (it will arrive on a later check). If there's no `fathom_checked` at all, publish the **Fathom meetings in** workflow |
| Anything failed | Every failure is logged, and the run is kept | In n8n, open **Executions**, open the red one, fix the cause from this table, and click **Retry**. Retrying is always safe: it finds the Notion page and calendar draft it already made instead of making them twice |

**Nothing falls back to the cloud when the home computer has a problem.** A failed meeting
summary waits for you to retry it. It is never quietly sent to an outside service instead.

## Where things are

| What | Where |
|---|---|
| Activity log: what happened and when, never the content | `logs/household.jsonl`, one line per step |
| Workflows, saved credentials, and runs waiting for approval | n8n, at http://localhost:5678 (only reachable from the home computer, or over Tailscale) |
| Documents and their search index | The documents folder and `search/index.json`. Both stay on the home computer |
| The key that unlocks saved credentials | `.env` on the home computer, **and a copy in the family password manager** |

To see only the failures in the log:

    grep '"failed"' logs/household.jsonl

Each failure names the step that failed. `error` is n8n's summary, which for a rejected
request is often just "Bad request"; `detail` is the service's own reason, such as Notion
saying which property it couldn't find.

## Five minutes, once a month

1. Search the log for `"failed"` and check each one was dealt with.
2. Open n8n, then **Executions**, and check nothing has been waiting for approval for weeks.
3. Check the computer has at least 20 GB of free disk space.
4. Check last month's backup exists and opens. *(Encrypted automatic backups are part
   of phase 1.)*

## Twice a year (the maintenance visit)

- Replace the Notion token and Google sign-in, and update the saved credentials.
- Update n8n and Ollama to tested versions, one at a time: change `N8N_VERSION` in `.env`,
  run `python -m unittest discover -s tests`, send the sample meeting through, and re-run
  the model checks in `bench/` before trusting a new model.
- Read through this runbook together and fix anything that turned out to be unclear.

## Known limits

- **The home model is good, not perfect.** On the test questions it got 20 of 21 right; the
  one it missed had the right answer with a wrong date in it. That's why a person
  approves anything that gets written, and why answers name their source.
- **Google's sign-in expires every 7 days** while the Google app is in "testing" mode.
  Before real use, the app has to be published (or made "internal" on Google Workspace),
  or calendar drafts will stop every week.
- **Very long meetings take longer.** How long depends on the computer's memory. The
  numbers for this setup are in [bench/README.md](../bench/README.md).
