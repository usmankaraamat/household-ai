"""Generate the n8n workflow files from this one readable source.

    python workflows/build.py

Writes meeting-to-notion.json and error-handler.json, which n8n imports. Edit
the JavaScript here, not in the exported JSON, so every change shows up in git.
"""
import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_ID, ERROR_ID = "mtgToNotion00001", "hhErrorHandler01"

# Shared by every Code node: one JSON line per step in logs/household.jsonl.
# The log records what happened and when, not what the family said.
LOG = r"""const fs = require('fs');
const log = (step, extra = {}) => fs.appendFileSync('/data/logs/household.jsonl',
  JSON.stringify({ ts: new Date().toISOString(), workflow: $workflow.name, execution: $execution.id, step, ...extra }) + '\n');
"""

CHECK_TRANSCRIPT = LOG + r"""
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
log('received', { title: m.title, chars: m.transcript.length, est_tokens: estTokens });

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
return [{ json: { meeting: { title: m.title, date: m.date, attendees: m.attendees || [] }, request } }];
"""

CHECK_SUMMARY = LOG + r"""
const r = $input.first().json;
const meeting = $('Check transcript').first().json.meeting;
let s;
try {
  s = JSON.parse(r.message.content);
} catch (e) {
  log('bad_model_output', { title: meeting.title });
  throw new Error('The home model did not return valid JSON. Retry the execution, or try another model in Config.');
}
if (typeof s.summary !== 'string' || !Array.isArray(s.action_items)) throw new Error('The summary is missing required fields');

const ev = s.event || {};
const event = ev.needed && /^\d{4}-\d{2}-\d{2}$/.test(ev.date) && /^\d{2}:\d{2}$/.test(ev.start) && /^\d{2}:\d{2}$/.test(ev.end) ? ev : null;
log('summarized', {
  title: meeting.title, model: r.model, prompt_tokens: r.prompt_eval_count, output_tokens: r.eval_count,
  seconds: +(r.total_duration / 1e9).toFixed(1), event_proposed: !!event,
});

const lines = [
  s.summary, '',
  'Decisions:', ...(s.decisions || []).map(d => `- ${d}`), '',
  'Action items:', ...s.action_items.map(a => `- ${a.owner}: ${a.task}${a.due ? ` (by ${a.due})` : ''}`), '',
  event ? `Proposed calendar draft: ${event.title}, ${event.date} ${event.start}-${event.end}` : 'No calendar event proposed.',
];
return [{ json: { meeting, summary: s, event, model: r.model, review: lines.join('\n') } }];
"""

ASK_APPROVAL = LOG + r"""
// Anything that sends this link to a phone (Gmail, Telegram, ntfy) goes here. Send the
// title and the link only: the summary stays on the home machine until someone approves it.
const item = $input.first().json;
log('awaiting_approval', { title: item.meeting.title, approve_url: $execution.resumeFormUrl });
return [{ json: item }];
"""

BUILD_NOTION = LOG + r"""
const form = $input.first().json;
const prev = $('Check summary').first().json;
const cfg = $('Config').first().json;
const title = prev.meeting.title;
if (form.Decision === 'Reject') {
  log('rejected_by_person', { title, note: form['Note for the log'] || '' });
  return [];
}
log('approved', { title, decision: form.Decision, note: form['Note for the log'] || '' });
if (!cfg.notionDatabaseId) throw new Error('Set notionDatabaseId in the Config node');

const rich = t => [{ type: 'text', text: { content: String(t).slice(0, 1900) } }];
const block = (type, t, extra = {}) => ({ object: 'block', type, [type]: { rich_text: rich(t), ...extra } });
const s = prev.summary;
const children = [
  block('heading_2', 'Summary'), block('paragraph', s.summary),
  block('heading_2', 'Decisions'), ...(s.decisions || []).map(d => block('bulleted_list_item', d)),
  block('heading_2', 'Action items'),
  ...s.action_items.map(a => block('to_do', `${a.owner}: ${a.task}${a.due ? ` (by ${a.due})` : ''}`, { checked: false })),
  block('paragraph', `Summarized at home by ${prev.model}. The transcript is not stored in Notion.`),
];
const properties = {
  [cfg.notionTitleProperty]: { title: rich(title) },
  [cfg.notionDateProperty]: { date: { start: prev.meeting.date } },
};
return [{ json: { decision: form.Decision, notionBody: { parent: { database_id: cfg.notionDatabaseId }, properties, children } } }];
"""

BUILD_EVENT = LOG + r"""
const page = $input.first().json;
const prev = $('Check summary').first().json;
const cfg = $('Config').first().json;
const decision = $('Build Notion page').first().json.decision;
log('notion_page_created', { title: prev.meeting.title, notion_url: page.url });

if (decision !== 'Approve notes and calendar draft' || !prev.event) {
  log('done', { title: prev.meeting.title, calendar: 'skipped' });
  return [];
}
const ev = prev.event;
// No attendees and status "tentative": a draft only the family sees. Nobody gets invited.
return [{ json: { calendarBody: {
  summary: `[Draft] ${ev.title}`,
  status: 'tentative',
  description: `Proposed in "${prev.meeting.title}" (${prev.meeting.date}). Notes: ${page.url}`,
  start: { dateTime: `${ev.date}T${ev.start}:00`, timeZone: cfg.timezone },
  end: { dateTime: `${ev.date}T${ev.end}:00`, timeZone: cfg.timezone },
} } }];
"""

LOG_DONE = LOG + r"""
const ev = $input.first().json;
log('done', { title: $('Check summary').first().json.meeting.title, calendar: 'draft created', event_link: ev.htmlLink });
return $input.all();
"""

ON_ERROR = LOG + r"""
// Runs when any household workflow fails after its retries. The failed run keeps its
// data in n8n, so it can be retried from the Executions list once the cause is fixed.
const e = $input.first().json;
log('failed', {
  failed_workflow: e.workflow && e.workflow.name,
  failed_execution: e.execution && e.execution.id,
  node: e.execution && e.execution.lastNodeExecuted,
  error: e.execution && e.execution.error && e.execution.error.message,
  open_in_n8n: e.execution && e.execution.url,
});
// Anything that alerts a person (email, phone) goes here: say what failed, never the content.
return $input.all();
"""

RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}


def node(name, type_, version, x, params, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"household-ai/{name}")), "name": name,
            "type": f"n8n-nodes-base.{type_}", "typeVersion": version, "position": [x, 300],
            "parameters": params, **extra}


def code(name, x, js):
    return node(name, "code", 2, x, {"jsCode": js})


def http(name, x, url, body_expr, cred_type=None, headers=None, timeout=60000):
    p = {"method": "POST", "url": url, "sendBody": True, "specifyBody": "json",
         "jsonBody": body_expr, "options": {"timeout": timeout}}
    if cred_type:
        p.update(authentication="predefinedCredentialType", nodeCredentialType=cred_type)
    if headers:
        p.update(sendHeaders=True, headerParameters={"parameters": [{"name": k, "value": v} for k, v in headers.items()]})
    return node(name, "httpRequest", 4.2, x, p, **RETRY)


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
        ("calendarId", "primary", "string"),
        ("timezone", "America/Los_Angeles", "string"),
    ]
    assignments = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, n)), "name": n, "value": v, "type": t} for n, v, t in values]
    return node("Config", "set", 3.4, 220, {"assignments": {"assignments": assignments},
                                            "includeOtherFields": True, "options": {}})


def chain(names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


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
                 "fieldOptions": {"values": [{"option": "Approve notes and calendar draft"},
                                             {"option": "Approve notes only"}, {"option": "Reject"}]}},
                {"fieldLabel": "Note for the log", "fieldType": "textarea"},
            ]},
            "options": {},
        }),
        code("Build Notion page", 1540, BUILD_NOTION),
        http("Create Notion page", 1760, "https://api.notion.com/v1/pages",
             "={{ JSON.stringify($json.notionBody) }}", cred_type="notionApi",
             headers={"Notion-Version": "2022-06-28"}),
        code("Build calendar draft", 1980, BUILD_EVENT),
        http("Create draft event", 2200,
             "=https://www.googleapis.com/calendar/v3/calendars/{{ encodeURIComponent($('Config').first().json.calendarId) }}/events?sendUpdates=none",
             "={{ JSON.stringify($json.calendarBody) }}", cred_type="googleCalendarOAuth2Api"),
        code("Log done", 2420, LOG_DONE),
    ]
    note = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "household-ai/note")), "name": "What leaves the house",
            "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [440, 20],
            "parameters": {"width": 900, "height": 220, "content":
                "## What leaves the house\nThe transcript goes only to Ollama on this machine. After a person approves, "
                "Notion gets the short summary and Google Calendar gets a tentative draft with no guests. "
                "Every step is logged to logs/household.jsonl, and failures go to the Household errors workflow. "
                "See docs/data-boundary.md."}}
    return {"id": MAIN_ID, "name": "Meeting notes to Notion", "active": False,
            "nodes": nodes + [note], "connections": chain([n["name"] for n in nodes]),
            "settings": {"executionOrder": "v1", "errorWorkflow": ERROR_ID, "saveManualExecutions": True},
            "pinData": {}}


def error_workflow():
    nodes = [node("A household workflow failed", "errorTrigger", 1, 0, {}),
             code("Log the failure", 220, ON_ERROR)]
    return {"id": ERROR_ID, "name": "Household errors", "active": False, "nodes": nodes,
            "connections": chain([n["name"] for n in nodes]), "settings": {"executionOrder": "v1"}, "pinData": {}}


if __name__ == "__main__":
    for filename, wf in [("meeting-to-notion.json", main_workflow()), ("error-handler.json", error_workflow())]:
        (HERE / filename).write_text(json.dumps(wf, indent=2) + "\n", encoding="utf-8")
        print(f"wrote workflows/{filename} ({len(wf['nodes'])} nodes)")
