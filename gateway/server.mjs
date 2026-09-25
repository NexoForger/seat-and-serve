import { createServer } from 'node:https';
import { readFileSync } from 'node:fs';
import { timingSafeEqual } from 'node:crypto';
import { openStore } from './store.mjs';
import { device } from './devices.mjs';

const required = ['TRT_GATEWAY_CERT', 'TRT_GATEWAY_KEY', 'TRT_GATEWAY_TOKEN',
  'TRT_SITE_URL', 'TRT_SITE_API_TOKEN', 'TRT_OUTLET'];
const missing = required.filter(key => !process.env[key]);
if (missing.length) throw new Error(`Missing gateway configuration: ${missing.join(', ')}`);

const store = openStore(process.env.TRT_GATEWAY_DB || './gateway.sqlite');
const site = process.env.TRT_SITE_URL.replace(/\/$/, '');
const outlet = process.env.TRT_OUTLET;
const auth = process.env.TRT_GATEWAY_TOKEN;
const channels = ['Till', 'Table', 'Tab', 'Takeaway', 'Retail'];

function send(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(data));
}

function authenticated(req) {
  const supplied = (req.headers.authorization || '').replace(/^Bearer /, '');
  const actual = Buffer.from(supplied);
  const expected = Buffer.from(auth);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

async function body(req) {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 65536) throw new Error('Request too large');
  }
  return JSON.parse(raw || '{}');
}

async function central(method, args, write = false) {
  const url = new URL(`${site}/api/method/table_remote_till.api.${method}`);
  if (!write) for (const [key, value] of Object.entries(args)) url.searchParams.set(key, value);
  const response = await fetch(url, {
    method: write ? 'POST' : 'GET',
    headers: { Authorization: `token ${process.env.TRT_SITE_API_TOKEN}`,
      ...(write ? { 'Content-Type': 'application/json' } : {}) },
    body: write ? JSON.stringify(args) : undefined,
    signal: AbortSignal.timeout(10000),
  });
  const result = await response.json();
  if (!response.ok || result.exc) throw new Error(result.message || result.exc || `Site HTTP ${response.status}`);
  return result.message;
}

async function refresh() {
  const result = {};
  for (const channel of channels) {
    const catalog = await central('catalog', { outlet, channel });
    store.replaceCatalog(channel, catalog.currency, catalog.items);
    result[channel] = catalog.items.length;
  }
  return result;
}

async function sync() {
  const result = { applied: 0, conflicts: 0, offline: false };
  for (const event of store.pending()) {
    const command = JSON.parse(event.command_json);
    const order = store.getOrder(event.order_id);
    if (command.action === 'cash_accepted') {
      store.mark(event.event_id, 'Conflict', 'Cash requires manager settlement in ERPNext');
      result.conflicts++;
      continue;
    }
    try {
      const remote = await central('order_command', {
        command: command.action === 'create' ? { ...command, outlet } : command,
        event_id: event.event_id, order_name: order.remote_id || undefined,
        expected_revision: event.expected_revision,
      }, true);
      if (command.action === 'create') store.setRemote(order.id, remote.name);
      if (command.action === 'add_line') {
        const local = order.lines.find(row => row.item === command.item);
        const confirmed = remote.lines.find(row => row.item === command.item);
        if (local && confirmed && local.rate !== confirmed.rate) {
          store.mark(event.event_id, 'Conflict', 'Price changed; manager review required', remote.revision);
          result.conflicts++;
          break;
        }
      }
      store.mark(event.event_id, 'Applied', null, remote.revision);
      result.applied++;
    } catch (error) {
      if (error instanceof TypeError || error.name === 'TimeoutError') {
        result.offline = true;
        break;
      }
      store.mark(event.event_id, 'Conflict', String(error));
      result.conflicts++;
      break;
    }
  }
  return result;
}

const server = createServer({ key: readFileSync(process.env.TRT_GATEWAY_KEY),
  cert: readFileSync(process.env.TRT_GATEWAY_CERT) }, async (req, res) => {
  if (!authenticated(req)) return send(res, 401, { error: 'Unauthorized' });
  try {
    if (req.method === 'GET' && req.url === '/state') return send(res, 200, store.state());
    if (req.method === 'POST' && req.url === '/command') {
      const input = await body(req);
      return send(res, 200, { order: store.apply(input), provisional: true });
    }
    if (req.method === 'POST' && req.url === '/ticket') {
      return send(res, 200, { ticket: store.updateTicket(await body(req)), provisional: true });
    }
    if (req.method === 'POST' && req.url === '/refresh') return send(res, 200, await refresh());
    if (req.method === 'POST' && req.url === '/sync') return send(res, 200, await sync());
    if (req.method === 'POST' && req.url === '/device/simulate') {
      const input = await body(req);
      return send(res, 200, await device(input.kind).perform(input.operation, input.payload));
    }
    return send(res, 404, { error: 'Not found' });
  } catch (error) { return send(res, 400, { error: String(error) }); }
});

server.listen(Number(process.env.TRT_GATEWAY_PORT || 8443), process.env.TRT_GATEWAY_HOST || '0.0.0.0');
