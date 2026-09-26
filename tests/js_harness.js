// Runs one n8n Code node's JavaScript outside n8n, for tests/test_workflows.py.
// Reads {code, nodes, input, runIndex} as JSON on stdin and prints
// {ok, result, error, logs}. `nodes` maps a node name to the JSON its $('name') returns.
// The activity log is captured instead of written to /data/logs.
const realRequire = require;
let raw = '';
process.stdin.on('data', d => { raw += d; });
process.stdin.on('end', async () => {
  const { code, nodes = {}, input = {}, runIndex = 0 } = JSON.parse(raw);
  const logs = [];
  const items = json => ({ first: () => ({ json }), all: () => [{ json }] });
  const $ = name => {
    if (!(name in nodes)) throw new Error(`test gave no data for node "${name}"`);
    return items(nodes[name]);
  };
  const fakeRequire = mod => mod === 'fs'
    ? { appendFileSync: (_path, line) => logs.push(JSON.parse(line)) }
    : realRequire(mod);
  const body = `return (async () => {\n${code}\n})();`;
  try {
    const fn = new Function('$', '$input', '$execution', '$workflow', '$runIndex', 'require', body);
    const result = await fn($, items(input), { id: 'test-run', resumeFormUrl: 'http://localhost/form' },
      { name: 'test' }, runIndex, fakeRequire);
    process.stdout.write(JSON.stringify({ ok: true, result, logs }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: e.message, logs }));
  }
});
