"""Generate the n8n workflow files from this one readable source.

    python workflows/build.py

Writes meeting-to-notion.json and error-handler.json, which n8n imports. Edit
the JavaScript here, not in the exported JSON, so every change shows up in git.
tests/test_workflows.py runs each Code node's JavaScript on its own under Node.
"""
import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_ID, ERROR_ID, POLL_ID = "mtgToNotion00001", "hhErrorHandler01", "fathomPoller0001"

# The only choices the approval form offers. Anything else stops the run before a write.
DECISIONS = ["Approve notes and calendar draft", "Approve notes only", "Reject"]

# Shared by every Code node: one JSON line per step in logs/household.jsonl.
# The log records what happened and when, not what the family said.
LOG = r"""const fs = require('fs');
const log = (step, extra = {}) => fs.appendFileSync('/data/logs/household.jsonl',
  JSON.stringify({ ts: new Date().toISOString(), workflow: $workflow.name, execution: $execution.id, step, ...extra }) + '\n');
"""

# The outbound check. Everything that leaves the house (to Notion or Google) passes through
# scrub() before the approval form, so the form shows exactly what will be sent. The same
# patterns run again just before each write as a guard. They catch shapes (numbers, IDs,
# labelled dates), not meaning: see docs/data-boundary.md.
OUTBOUND = r"""
const hit = (counts, label) => { counts[label] = (counts[label] || 0) + 1; return `[removed: ${label}]`; };
const luhn = s => {
  const d = s.replace(/\D/g, '');
  let sum = 0;
  for (let i = 0; i < d.length; i++) {
    let n = +d[d.length - 1 - i];
    if (i % 2) { n *= 2; if (n > 9) n -= 9; }
    sum += n;
  }
  return d.length >= 13 && sum % 10 === 0;
};
const ID_LABEL = /\b(?:account|acct|policy|member|routing|passport|licen[cs]e|ssn|cnic|nic|ntn|iban)\b(?:\s*(?:no\.?|number|#|id))?\s*[:#]?\s*((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{5,})/gi;
const DOB = /\b(?:dob|date of birth|born(?: on)?)\b\s*[:\-]?\s*(\d{1,4}[\/.-]\d{1,2}[\/.-]\d{1,4}|[A-Z][a-z]+ \d{1,2},? \d{4})/gi;
function scrub(text, counts) {
  // Most specific first, so a CNIC is called a CNIC and not a card or a long number.
  return String(text)
    .replace(/\b\d{5}-\d{7}-\d\b/g, () => hit(counts, 'CNIC'))
    .replace(/\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b/g, () => hit(counts, 'IBAN'))
    .replace(/\b\d{3}-\d{2}-\d{4}\b/g, () => hit(counts, 'SSN'))
    .replace(/\b(?:\d[ -]?){12,18}\d\b/g, m => luhn(m) ? hit(counts, 'card number') : m)
    .replace(ID_LABEL, (m, v) => m.slice(0, m.length - v.length) + hit(counts, 'ID or account number'))
    .replace(/\b\d{9,}\b/g, () => hit(counts, 'long number'))
    .replace(DOB, (m, v) => m.slice(0, m.length - v.length) + hit(counts, 'date of birth'));
}
// The guard: throws if anything sensitive-shaped is about to leave, whatever the path.
// Pass the family's content only, not IDs the system made (Notion and meeting IDs are hex).
function assertClean(payload) {
  const found = {};
  scrub(JSON.stringify(payload), found);
  if (Object.keys(found).length) {
    log('outbound_blocked', { found });
    throw new Error(`Stopped before sending: the payload still contains ${Object.keys(found).join(', ')}. Nothing was written.`);
  }
}
"""

# Calendar proposals are checked as real dates and times, not just their shape.
EVENT_CHECK = r"""
function checkEvent(ev, meetingDate) {
  if (!ev || !ev.needed) return { event: null, problem: null };
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ev.date || '');
  const minutes = s => {
    const m = /^(\d{2}):(\d{2})$/.exec(s || '');
    return m && +m[1] < 24 && +m[2] < 60 ? +m[1] * 60 + +m[2] : null;
  };
  if (!String(ev.title || '').trim()) return { event: null, problem: 'it has no title' };
  if (!d) return { event: null, problem: `"${ev.date}" is not a date` };
  const day = new Date(Date.UTC(+d[1], +d[2] - 1, +d[3]));
  if (day.getUTCFullYear() !== +d[1] || day.getUTCMonth() !== +d[2] - 1 || day.getUTCDate() !== +d[3]) {
    return { event: null, problem: `${ev.date} is not a real date` };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(meetingDate || '') && ev.date < meetingDate) {
    return { event: null, problem: `${ev.date} is before the meeting itself` };
  }
  const start = minutes(ev.start), end = minutes(ev.end);
  if (start === null || end === null) return { event: null, problem: `${ev.start}-${ev.end} is not a valid time` };
  if (end <= start) return { event: null, problem: `it ends (${ev.end}) before it starts (${ev.start})` };
  if (end - start > 12 * 60) return { event: null, problem: 'it is longer than 12 hours' };
  return { event: ev, problem: null };
}
"""

CHECK_TRANSCRIPT = LOG + r"""
const crypto = require('crypto');
const cfg = $('Config').first().json;
const m = cfg.body || {};
if (!m.title || !m.transcript) throw new Error('The request needs a title and a transcript');

// Ollama refuses prompts longer than its context. Catch that here, before the model call,
// with a message the family can act on (older Ollama versions silently cut the text instead).
const estTokens = Math.ceil(m.transcript.length / 3.6);
if (estTokens > cfg.numCtx * 0.75) {
  log('rejected_too_long', { title: m.title, est_tokens: estTokens, num_ctx: cfg.numCtx });
  throw new Error(`This transcript is about ${estTokens} tokens and the model is set to ${cfg.numCtx}. Raise numCtx in Config, or split the meeting.`);
}
// One stable ID per meeting. Every write outside the house is keyed on it, so a retry or a
// resent transcript finds the page and event it already made instead of making another.
const meetingId = crypto.createHash('sha256')
  .update(m.meeting_id ? `id:${m.meeting_id}` : `${m.title}\n${m.date}\n${m.transcript}`)
  .digest('hex').slice(0, 32);
log('received', { title: m.title, meeting_id: meetingId, chars: m.transcript.length, est_tokens: estTokens });

const SYSTEM = `You summarize a family's meeting transcript for their shared notes. Use only what was said.
Return JSON with:
- summary: 2 to 4 plain sentences.
- decisions: what was agreed, one short line each.
- action_items: one per task, with owner (first name), task, and due (YYYY-MM-DD if a date was said, otherwise "").
- event: if they agreed on a specific appointment with a date and a time, needed=true with title, date (YYYY-MM-DD), start and end (HH:MM, 24-hour). Otherwise needed=false and empty strings.
The meeting date is given, so resolve words like "Friday" or "the 10th" to real dates.`;

const str = { type: 'string' };
const schema = {
  type: 'object',
  properties: {
    summary: str,
    decisions: { type: 'array', items: str },
    action_items: { type: 'array', items: { type: 'object', properties: { owner: str, task: str, due: str }, required: ['owner', 'task', 'due'] } },
    event: { type: 'object', properties: { needed: { type: 'boolean' }, title: str, date: str, start: str, end: str }, required: ['needed', 'title', 'date', 'start', 'end'] },
  },
  required: ['summary', 'decisions', 'action_items', 'event'],
};

const request = {
  model: cfg.model,
  stream: false,
  format: schema,
  options: { num_ctx: cfg.numCtx, temperature: 0 },
  messages: [
    { role: 'system', content: SYSTEM },
    { role: 'user', content: `Meeting: ${m.title}\nDate: ${m.date}\nAttendees: ${(m.attendees || []).join(', ')}\n\nTranscript:\n${m.transcript}` },
  ],
};
if (cfg.disableThinking) request.think = false;
return [{ json: { meeting: { id: meetingId, title: m.title, date: m.date, attendees: m.attendees || [] }, request } }];
"""

CHECK_SUMMARY = LOG + OUTBOUND + EVENT_CHECK + r"""
const r = $input.first().json;
const meeting = $('Check transcript').first().json.meeting;
let s;
try {
  s = JSON.parse(r.message.content);
} catch (e) {
  log('bad_model_output', { meeting_id: meeting.id });
  throw new Error('The home model did not return valid JSON. Retry the execution, or try another model in Config.');
}
if (typeof s.summary !== 'string' || !Array.isArray(s.action_items)) throw new Error('The summary is missing required fields');

// Everything below is what may leave the house, already passed through the outbound check.
const removed = {};
const clean = t => scrub(t, removed);
const title = clean(meeting.title);
const out = {
  summary: clean(s.summary),
  decisions: (s.decisions || []).map(clean),
  action_items: s.action_items.map(a => ({ owner: clean(a.owner || ''), task: clean(a.task || ''),
    due: /^\d{4}-\d{2}-\d{2}$/.test(a.due || '') ? a.due : '' })),
};
const { event: proposed, problem } = checkEvent(s.event, meeting.date);
const event = proposed && { ...proposed, title: clean(proposed.title) };
log('summarized', {
  meeting_id: meeting.id, model: r.model, prompt_tokens: r.prompt_eval_count, output_tokens: r.eval_count,
  seconds: +(r.total_duration / 1e9).toFixed(1), event_proposed: !!event, event_problem: problem, removed,
});

const removedCount = Object.values(removed).reduce((a, b) => a + b, 0);
const lines = [
  'This is exactly what will be sent to Notion' + (event ? ' and Google Calendar' : '') + ' if you approve.',
  removedCount ? `Removed before anything leaves the house: ${Object.entries(removed).map(([k, v]) => `${v} ${k}`).join(', ')}.` : 'Nothing needed removing.',
  '',
  out.summary, '',
  'Decisions:', ...out.decisions.map(d => `- ${d}`), '',
  'Action items:', ...out.action_items.map(a => `- ${a.owner}: ${a.task}${a.due ? ` (by ${a.due})` : ''}`), '',
  event ? `Proposed calendar draft: ${event.title}, ${event.date} ${event.start}-${event.end}`
    : problem ? `No calendar draft: the model proposed an event, but ${problem}.` : 'No calendar event proposed.',
];
return [{ json: { meeting: { ...meeting, title }, summary: out, event, model: r.model, review: lines.join('\n') } }];
"""

ASK_APPROVAL = LOG + r"""
// Anything that sends this link to a phone (Gmail, Telegram, ntfy) goes here. Send the
// title and the link only: the summary stays on the home machine until someone approves it.
const item = $input.first().json;
log('awaiting_approval', { meeting_id: item.meeting.id, approve_url: $execution.resumeFormUrl });
return [{ json: item }];
"""

BUILD_NOTION = LOG + OUTBOUND + r"""
const DECISIONS = __DECISIONS__;
const form = $input.first().json;
const prev = $('Check summary').first().json;
const cfg = $('Config').first().json;
const id = prev.meeting.id;
if (!DECISIONS.includes(form.Decision)) {
  log('unknown_decision', { meeting_id: id });
  throw new Error(`"${form.Decision}" is not one of the approval choices. Nothing was written.`);
}
if (form.Decision === 'Reject') {
  log('rejected_by_person', { meeting_id: id, note: form['Note for the log'] || '' });
  return [];
}
log('approved', { meeting_id: id, decision: form.Decision, note: form['Note for the log'] || '' });
if (!cfg.notionDatabaseId) throw new Error('Set notionDatabaseId in the Config node');

const rich = t => [{ type: 'text', text: { content: String(t).slice(0, 1900) } }];
const block = (type, t, extra = {}) => ({ object: 'block', type, [type]: { rich_text: rich(t), ...extra } });
const s = prev.summary;
const children = [
  block('heading_2', 'Summary'), block('paragraph', s.summary),
  block('heading_2', 'Decisions'), ...s.decisions.map(d => block('bulleted_list_item', d)),
  block('heading_2', 'Action items'),
  ...s.action_items.map(a => block('to_do', `${a.owner}: ${a.task}${a.due ? ` (by ${a.due})` : ''}`, { checked: false })),
  block('paragraph', `Summarized at home by ${prev.model}. The transcript is not stored in Notion.`),
];
const properties = {
  [cfg.notionTitleProperty]: { title: rich(prev.meeting.title) },
  [cfg.notionDateProperty]: { date: { start: prev.meeting.date } },
  [cfg.notionMeetingIdProperty]: { rich_text: rich(id) },
};
assertClean({ title: prev.meeting.title, children });
const notionBody = { parent: { database_id: cfg.notionDatabaseId }, properties, children };
const findBody = { filter: { property: cfg.notionMeetingIdProperty, rich_text: { equals: id } }, page_size: 1 };
return [{ json: { decision: form.Decision, notionBody, findBody } }];
"""

# Notion has no idempotency key, so the page is found by its Meeting ID before it is
# created. If the create call fails, the flow waits and looks again rather than blindly
# posting a second time: a create whose response was lost shows up on the next look.
PAGE_EXISTS = LOG + r"""
const q = $input.first().json;
const built = $('Build Notion page').first().json;
const id = $('Check summary').first().json.meeting.id;
const page = Array.isArray(q.results) && q.results[0];
if (page) {
  log('notion_page_existed', { meeting_id: id, notion_url: page.url, attempt: $runIndex + 1 });
  return [{ json: { exists: true, page: { id: page.id, url: page.url } } }];
}
if ($runIndex >= 3) {
  log('notion_create_gave_up', { meeting_id: id });
  throw new Error('Notion did not confirm the page after 3 attempts. Check Notion, then retry this run: it looks for the page first, so it will not make a duplicate.');
}
if ($runIndex > 0) log('notion_create_retry', { meeting_id: id, attempt: $runIndex + 1 });
return [{ json: { exists: false, notionBody: built.notionBody } }];
"""

BUILD_EVENT = LOG + OUTBOUND + r"""
const j = $input.first().json;
const page = j.page || j;
const prev = $('Check summary').first().json;
const cfg = $('Config').first().json;
const decision = $('Build Notion page').first().json.decision;
const id = prev.meeting.id;
if (!j.page) log('notion_page_created', { meeting_id: id, notion_url: page.url });

if (decision !== 'Approve notes and calendar draft' || !prev.event) {
  log('done', { meeting_id: id, calendar: 'skipped' });
  return [];
}
const ev = prev.event;
const calendarBody = {
  // Google accepts an ID from the caller. Sending the same one twice returns 409 instead of
  // a second event, which makes this write safe to retry. Base32hex allows 0-9 and a-v.
  id: `hh${id}`,
  summary: `[Draft] ${ev.title}`,
  status: 'tentative',
  // Private hides the details from anyone the calendar is shared with, and transparent
  // leaves the time free, so a draft neither shows its contents nor blocks the slot.
  visibility: 'private',
  transparency: 'transparent',
  description: `Proposed in "${prev.meeting.title}" (${prev.meeting.date}). Notes: ${page.url}`,
  start: { dateTime: `${ev.date}T${ev.start}:00`, timeZone: cfg.timezone },
  end: { dateTime: `${ev.date}T${ev.end}:00`, timeZone: cfg.timezone },
};
assertClean({ summary: calendarBody.summary, title: prev.meeting.title });
return [{ json: { calendarBody } }];
"""

CHECK_EVENT = LOG + r"""
const r = $input.first().json;
const id = $('Check summary').first().json.meeting.id;
if (r.statusCode === 200 || r.statusCode === 201) {
  log('done', { meeting_id: id, calendar: 'draft created', event_link: r.body && r.body.htmlLink });
} else if (r.statusCode === 409) {
  log('done', { meeting_id: id, calendar: 'draft already existed' });
} else {
  throw new Error(`Google Calendar answered ${r.statusCode}. Retry this run once the cause is fixed: the event ID is fixed, so it cannot be created twice.`);
}
return [{ json: { statusCode: r.statusCode } }];
"""

# The Fathom poller. n8n at home only listens to its own machine, so Fathom (on the internet)
# can't push meetings to it. Instead the home machine asks Fathom every few minutes, and
# nothing from outside ever gets in. Each new meeting is handed to the meeting workflow's
# webhook, one run per meeting, so everything after this is the same path a manual test uses.
POLL_NEW = LOG + r"""
const cfg = $('Poller config').first().json;
const r = $input.first().json;
const meetings = r.items || r.meetings;
if (!Array.isArray(meetings)) throw new Error(`Fathom's reply had no list of meetings (keys: ${Object.keys(r).join(', ')})`);
if (r.next_cursor) log('fathom_more_pages', { note: 'more meetings than one page; the rest arrive on the next checks' });

// Remembered between runs (only in an active workflow): which meetings were already sent.
const seen = $getWorkflowStaticData('global');
seen.sent = seen.sent || {};
const day = t => new Intl.DateTimeFormat('en-CA', { timeZone: cfg.timezone, year: 'numeric', month: '2-digit', day: '2-digit' })
  .format(new Date(t));

const out = [];
for (const m of meetings) {
  const key = `fathom-${m.recording_id}`;
  if (seen.sent[key]) continue;
  const lines = (m.transcript || []).map(t => `${(t.speaker && t.speaker.display_name) || 'Someone'}: ${t.text}`);
  if (!lines.length) {  // Fathom lists a meeting before its transcript is ready
    log('fathom_transcript_not_ready', { meeting_id: key });
    continue;
  }
  const speakers = [...new Set((m.transcript || []).map(t => t.speaker && t.speaker.display_name).filter(Boolean))];
  const invitees = (m.calendar_invitees || []).map(i => i.name).filter(Boolean);
  out.push({ json: { key, body: {
    meeting_id: key,
    title: m.meeting_title || m.title || 'Untitled meeting',
    date: day(m.recording_start_time || m.scheduled_start_time || m.created_at),
    attendees: invitees.length ? invitees : speakers,
    transcript: lines.join('\n'),
  } } });
}
log('fathom_checked', { listed: meetings.length, new: out.length });
return out;
"""

POLL_REMEMBER = LOG + r"""
// Runs only after every new meeting reached the meeting workflow. A meeting that failed to
// send isn't remembered, so the next check sends it again; the meeting workflow is keyed on
// the same ID, so a resend can't make a second Notion page or calendar draft.
const seen = $getWorkflowStaticData('global');
seen.sent = seen.sent || {};
const now = Date.now();
for (const item of $('New meetings only').all()) seen.sent[item.json.key] = now;
for (const [k, t] of Object.entries(seen.sent)) if (now - t > 30 * 864e5) delete seen.sent[k];
log('fathom_sent', { meetings: $('New meetings only').all().map(i => i.json.key) });
return [{ json: { sent: $('New meetings only').all().length } }];
"""

ON_ERROR = LOG + r"""
// Runs when any household workflow fails after its retries. The failed run keeps its
// data in n8n, so it can be retried from the Executions list once the cause is fixed.
const e = $input.first().json;
const err = (e.execution && e.execution.error) || {};
// For a failed API call, n8n's message is generic ("Bad request - please check your
// parameters"); the service's own reason ("Could not find property ... Meeting ID") is in
// description. Log both, capped, since a service's error can quote part of the request.
const cap = t => (typeof t === 'string' && t ? t.slice(0, 300) : undefined);
log('failed', {
  failed_workflow: e.workflow && e.workflow.name,
  failed_execution: e.execution && e.execution.id,
  node: e.execution && e.execution.lastNodeExecuted,
  error: cap(err.message),
  detail: err.description !== err.message ? cap(err.description) : undefined,
  http_code: err.httpCode,
  open_in_n8n: e.execution && e.execution.url,
});
// Anything that alerts a person (email, phone) goes here: say what failed, never the content.
return $input.all();
"""

RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}


def node(name, type_, version, x, params, y=300, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"household-ai/{name}")), "name": name,
            "type": f"n8n-nodes-base.{type_}", "typeVersion": version, "position": [x, y],
            "parameters": params, **extra}


def code(name, x, js, y=300):
    return node(name, "code", 2, x, {"jsCode": js}, y)


def http(name, x, url, body_expr, cred_type=None, headers=None, timeout=60000, retry=True,
         full_response=False, y=300, **extra):
    """retry=True only for requests that are safe to repeat: reads, and writes with a
    caller-chosen ID. full_response hands every status code to the next node instead of
    failing, so it can tell "created" from "already there"."""
    options = {"timeout": timeout}
    if full_response:
        options["response"] = {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}
    p = {"method": "POST", "url": url, "sendBody": True, "specifyBody": "json",
         "jsonBody": body_expr, "options": options}
    if cred_type:
        p.update(authentication="predefinedCredentialType", nodeCredentialType=cred_type)
    if headers:
        p.update(sendHeaders=True, headerParameters={"parameters": [{"name": k, "value": v} for k, v in headers.items()]})
    return node(name, "httpRequest", 4.2, x, p, y, **(RETRY if retry else {}), **extra)


def config(x):
    values = [
        ("model", "granite4.2:8b", "string"),
        # Granite 4.2 and Qwen3.5 both think by default: slower, and it can eat the whole answer.
        ("disableThinking", True, "boolean"),
        ("ollamaUrl", "http://host.docker.internal:11434", "string"),
        ("numCtx", 16384, "number"),
        ("notionDatabaseId", "", "string"),
        ("notionTitleProperty", "Name", "string"),
        ("notionDateProperty", "Date", "string"),
        # A Text property in the Notion database. It is how a retry finds the page it made.
        ("notionMeetingIdProperty", "Meeting ID", "string"),
        ("calendarId", "primary", "string"),
        ("timezone", "America/Los_Angeles", "string"),
    ]
    assignments = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, n)), "name": n, "value": v, "type": t} for n, v, t in values]
    return node("Config", "set", 3.4, x, {"assignments": {"assignments": assignments},
                                          "includeOtherFields": True, "options": {}})


def link(*targets):
    """One output: every target listed. Pass several lists for a node with several outputs."""
    return {"main": [[{"node": t, "type": "main", "index": 0} for t in out] for out in targets]}


NOTION = {"Notion-Version": "2022-06-28"}


def main_workflow():
    nodes = [
        node("Transcript arrives", "webhook", 2, 0,
             {"httpMethod": "POST", "path": "meeting-transcript", "responseMode": "onReceived", "options": {}},
             webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "household-ai/webhook"))),
        config(220),
        code("Check transcript", 440, CHECK_TRANSCRIPT),
        http("Summarize at home (Ollama)", 660, "={{ $('Config').first().json.ollamaUrl }}/api/chat",
             "={{ JSON.stringify($json.request) }}", timeout=600000),
        code("Check summary", 880, CHECK_SUMMARY),
        code("Ask for approval", 1100, ASK_APPROVAL),
        node("Wait for approval", "wait", 1.1, 1320, {
            "resume": "form",
            "formTitle": "Approve meeting notes",
            "formDescription": "={{ $json.review }}",
            "formFields": {"values": [
                {"fieldLabel": "Decision", "fieldType": "dropdown", "requiredField": True,
                 "fieldOptions": {"values": [{"option": d} for d in DECISIONS]}},
                {"fieldLabel": "Note for the log", "fieldType": "textarea"},
            ]},
            "options": {},
        }),
        code("Build Notion page", 1540, BUILD_NOTION.replace("__DECISIONS__", json.dumps(DECISIONS))),
        http("Find existing page", 1760,
             "=https://api.notion.com/v1/databases/{{ $('Config').first().json.notionDatabaseId }}/query",
             "={{ JSON.stringify($('Build Notion page').first().json.findBody) }}",
             cred_type="notionApi", headers=NOTION),
        code("Page exists?", 1980, PAGE_EXISTS),
        node("Already in Notion?", "if", 2.2, 2200, {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "household-ai/exists")),
                                "leftValue": "={{ $json.exists }}", "rightValue": "",
                                "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                "combinator": "and"},
            "options": {}}),
        # Not retried automatically: a create whose response was lost would be posted twice.
        # A failure takes the error output, waits, and looks the page up again instead.
        http("Create Notion page", 2420, "https://api.notion.com/v1/pages",
             "={{ JSON.stringify($json.notionBody) }}", cred_type="notionApi", headers=NOTION,
             retry=False, y=420, onError="continueErrorOutput"),
        node("Wait, then look again", "wait", 1.1, 2640, {"resume": "timeInterval", "amount": 5, "unit": "seconds"},
             y=560, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "household-ai/wait-retry"))),
        code("Build calendar draft", 2860, BUILD_EVENT),
        http("Create draft event", 3080,
             "=https://www.googleapis.com/calendar/v3/calendars/{{ encodeURIComponent($('Config').first().json.calendarId) }}/events?sendUpdates=none",
             "={{ JSON.stringify($json.calendarBody) }}", cred_type="googleCalendarOAuth2Api", full_response=True),
        code("Check calendar result", 3300, CHECK_EVENT),
    ]
    order = [n["name"] for n in nodes]
    connections = {a: link([b]) for a, b in zip(order, order[1:])
                   if a not in ("Already in Notion?", "Create Notion page", "Wait, then look again")}
    connections.update({
        "Already in Notion?": link(["Build calendar draft"], ["Create Notion page"]),  # true, false
        "Create Notion page": link(["Build calendar draft"], ["Wait, then look again"]),  # success, error
        "Wait, then look again": link(["Find existing page"]),
    })
    note = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "household-ai/note")), "name": "What leaves the house",
            "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [440, 20],
            "parameters": {"width": 900, "height": 220, "content":
                "## What leaves the house\nThe transcript goes only to Ollama on this machine. The summary passes an "
                "outbound check (IDs, account and card numbers, dates of birth) and the approval form shows exactly "
                "what will be sent. After a person approves, Notion gets the summary and Google Calendar gets a "
                "private draft that doesn't block time. Both writes are keyed on the meeting ID, so retries never "
                "duplicate. Every step is logged to logs/household.jsonl. See docs/data-boundary.md."}}
    return {"id": MAIN_ID, "name": "Meeting notes to Notion", "active": False,
            "nodes": nodes + [note], "connections": connections,
            "settings": {"executionOrder": "v1", "errorWorkflow": ERROR_ID, "saveManualExecutions": True},
            "pinData": {}}


def fathom_workflow():
    poller = node("Poller config", "set", 3.4, 220, {"assignments": {"assignments": [
        {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"poll/{n}")), "name": n, "value": v, "type": t} for n, v, t in [
            # Look back this far on every check. Long enough to catch a transcript that took
            # hours to be ready, or a machine that was off; already-sent meetings are skipped.
            ("lookbackHours", 48, "number"),
            # The meeting date is worked out in this time zone. Match the meeting workflow's Config.
            ("timezone", "America/Los_Angeles", "string"),
            # Inside the n8n container, n8n itself is on localhost:5678.
            ("meetingWebhook", "http://localhost:5678/webhook/meeting-transcript", "string"),
        ]]}, "includeOtherFields": False, "options": {}})
    nodes = [
        node("Every 10 minutes", "scheduleTrigger", 1.2, 0,
             {"rule": {"interval": [{"field": "minutes", "minutesInterval": 10}]}}),
        poller,
        node("Ask Fathom for recent meetings", "httpRequest", 4.2, 440, {
            "method": "GET", "url": "https://api.fathom.ai/external/v1/meetings",
            # The key goes in an n8n "Header Auth" credential: name X-Api-Key, value the key.
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendQuery": True, "queryParameters": {"parameters": [
                {"name": "created_after",
                 "value": "={{ new Date(Date.now() - $json.lookbackHours * 3600e3).toISOString() }}"},
                {"name": "include_transcript", "value": "true"},
            ]},
            "options": {"timeout": 60000}}, **RETRY),
        code("New meetings only", 660, POLL_NEW),
        http("Send to the meeting workflow", 880, "={{ $('Poller config').first().json.meetingWebhook }}",
             "={{ JSON.stringify($json.body) }}"),
        code("Remember what was sent", 1100, POLL_REMEMBER),
    ]
    order = [n["name"] for n in nodes]
    return {"id": POLL_ID, "name": "Fathom meetings in", "active": False, "nodes": nodes,
            "connections": {a: link([b]) for a, b in zip(order, order[1:])},
            "settings": {"executionOrder": "v1", "errorWorkflow": ERROR_ID}, "pinData": {}}


def error_workflow():
    nodes = [node("A household workflow failed", "errorTrigger", 1, 0, {}),
             code("Log the failure", 220, ON_ERROR)]
    return {"id": ERROR_ID, "name": "Household errors", "active": False, "nodes": nodes,
            "connections": {nodes[0]["name"]: link([nodes[1]["name"]])},
            "settings": {"executionOrder": "v1"}, "pinData": {}}


WORKFLOWS = {"meeting-to-notion.json": main_workflow, "fathom-poller.json": fathom_workflow,
             "error-handler.json": error_workflow}


def render(filename):
    return json.dumps(WORKFLOWS[filename](), indent=2) + "\n"


if __name__ == "__main__":
    for filename in WORKFLOWS:
        (HERE / filename).write_text(render(filename), encoding="utf-8")
        print(f"wrote workflows/{filename} ({len(json.loads(render(filename))['nodes'])} nodes)")
