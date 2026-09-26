# What stays home, what may go to the cloud

One page for the whole household. Everything else in this project follows from it.

## The rule

**Private by default.** Everything is handled on the home machine unless a specific
task needs the cloud *and* the home model has been shown to do that task badly. Every
exception is written down here, with the reason.

## Three zones

| Zone | Where | What lives there |
|---|---|---|
| **Home** | The Mac mini, in the house | Original documents, the search index built from them, the local model (Ollama), n8n, logs, API keys |
| **Cloud the family already uses** | Google Calendar and Gmail, Notion, Fathom or Granola | What the family already chose to keep there: calendar, email, shared notes, meeting recordings |
| **Claude** | Anthropic's API | Short, specific requests only, never whole documents |

## What goes where

| Data | Stays home | May reach Claude | Why |
|---|---|---|---|
| Leases, insurance, tax, medical and legal documents | ✅ always | ❌ never | Highest harm if leaked, and a local model handles "find it and quote it" well enough (see `bench/`) |
| Children's school forms, IDs, health information | ✅ always | ❌ never | Minors' data. No convenience is worth it |
| Account numbers, SSNs, dates of birth, passwords | ✅ always | ❌ never | The outbound check removes them before anything goes to Notion or Google, the approval form shows what was removed, and the count is logged |
| Answers from document search | ✅ | ❌ | Answers come from private documents, so they are private too |
| Meeting transcripts | ✅ summarized at home | ❌ | The recording service already has the transcript. Sending it to Claude would add another company that holds it. Whether the home summary is good enough is **not yet measured**: `bench/` tests document questions, not summaries |
| Meeting summaries → Notion | Written at home | ❌ | Only the short summary goes to Notion, not the transcript |
| Calendar events: title, time, attendee first names | | ✅ | Already in Google. Claude handles tricky scheduling ("move piano if the dentist runs late") much better than a small local model |
| Translation of everyday messages | | ✅ if the redaction check passes | Quality matters here, and the text is usually not sensitive |
| Workflow logic ("what should happen next") | | ✅ as instructions, without personal data | Claude writes and fixes the logic. The family's data doesn't need to be in that request |

## What protects the data today, and what comes later

**Built into this first slice, and covered by tests** (`tests/`):

1. **Nothing goes to Claude.** This slice makes no cloud AI calls at all. The Claude rows
   above describe phase 1.
2. **An outbound check runs before every write to Notion or Google.** It removes SSNs,
   card numbers, labelled account, policy and passport numbers, long numbers and dates of
   birth, then checks the final payload again and stops the run if anything is left.
3. **A human approves** anything that goes out in the family's name, and the approval
   form shows exactly what will be sent, including what the check removed. An unrecognized
   approval choice stops the run before any write.
4. **Retries never duplicate.** Every meeting gets a stable ID. The calendar draft uses it
   as the event ID, so Google refuses a second copy, and the Notion page is looked up by it
   before it is created. A failed create waits and looks again instead of posting twice.
5. **Calendar drafts are private and don't block time.** They have no guests, their
   details are hidden from anyone the calendar is shared with, and the slot stays free
   until someone accepts it.
6. **Failures stay private.** The workflow has no cloud path. If the home model is down,
   the run fails, is logged, and can be retried from n8n once the model is back.
7. **Every step is logged** with the meeting ID and what happened, never what was said.
   Keys stay in n8n's encrypted store on the home machine.

**Phase 1 adds:** a notification to a phone when something needs approval or has failed
(today it is only in the log and in n8n), a queue so a run waits for the home model
instead of failing, and the same outbound check in front of every Claude call.

**Set up on the Mac mini, not in code:** the disk is encrypted (FileVault); backups are
encrypted *before* they leave the house; remote access goes through a private network
(e.g. Tailscale), never an open port on the home router. None of these can be tested from
this repository, so they are on the day-one checklist instead.

## Known limits, stated plainly

- **Services already in the cloud are outside this boundary.** Calendar, Gmail, Notion and
  the meeting recorder already hold what the family put there. This design makes sure
  the new AI system adds as little to that as it can. It does not undo what's already
  there.
- **Anthropic's API** doesn't use API data to train its models by default, but it does
  keep requests for a limited time. Check the current terms before phase 1 is signed off,
  and ask about zero data retention if the family wants it.
- **The outbound check catches shapes** (numbers, IDs, labelled dates), not meaning. A
  summary can still say something private in plain words, which is why a person approves
  every write, and why the "never" rows above are enforced by *which workflow may call
  Claude at all*, not by the check alone.
- **The home model is weaker than Claude.** That's the trade-off the family is choosing.
  `bench/` measures how much weaker, on documents like theirs, so the choice is informed.
