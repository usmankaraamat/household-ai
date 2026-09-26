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
| Account numbers, SSNs, dates of birth, passwords | ✅ always | ❌ never | Redacted automatically before *any* text leaves the house, and the redaction is logged |
| Answers from document search | ✅ | ❌ | Answers come from private documents, so they are private too |
| Meeting transcripts | ✅ summarized at home | ❌ | The recording service already has the transcript. Sending it to Claude would add another company that holds it. The home summary is enough (to be checked in `bench/`) |
| Meeting summaries → Notion | Written at home | ❌ | Only the short summary goes to Notion, not the transcript |
| Calendar events: title, time, attendee first names | | ✅ | Already in Google. Claude handles tricky scheduling ("move piano if the dentist runs late") much better than a small local model |
| Translation of everyday messages | | ✅ if the redaction check passes | Quality matters here, and the text is usually not sensitive |
| Workflow logic ("what should happen next") | | ✅ as instructions, without personal data | Claude writes and fixes the logic. The family's data doesn't need to be in that request |

## Guarantees built into the system

1. **Failures stay private.** If the home model is down or slow, the task waits in a
   queue and someone gets a notification. It is never quietly sent to the cloud instead.
   This matters most, because "fall back to the cloud" is the easiest thing to build by
   accident.
2. **Every cloud call is logged**: when, which workflow, how many characters, and whether
   redaction changed anything. The log records that a call happened, not what it said.
3. **A human approves** anything that goes out in the family's name: Notion pages that
   others read, calendar invites, and later, emails.
4. **Keys stay home.** API keys live in n8n's encrypted store on the Mac mini, never in
   Notion or in documents.
5. **Encrypted at rest.** The Mac mini's disk is encrypted (FileVault), and backups are
   encrypted *before* they leave the house, so a stolen machine or a leaked backup
   reveals nothing.
6. **No open doors.** Remote access goes through a private network (e.g. Tailscale), not
   open ports on the home router.

## Known limits, stated plainly

- **Services already in the cloud are outside this boundary.** Calendar, Gmail, Notion and
  the meeting recorder already hold what the family put there. This design makes sure
  the new AI system adds as little to that as it can. It does not undo what's already
  there.
- **Anthropic's API** doesn't use API data to train its models by default, but it does
  keep requests for a limited time. Check the current terms before phase 1 is signed off,
  and ask about zero data retention if the family wants it.
- **Automatic redaction catches patterns** (numbers, dates, IDs), not meaning. That's
  why the "never" rows above are enforced by *which workflow may call Claude at all*,
  not by redaction alone.
- **The home model is weaker than Claude.** That's the trade-off the family is choosing.
  `bench/` measures how much weaker, on documents like theirs, so the choice is informed.
