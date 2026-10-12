import { createServer } from 'node:https';
import { readFileSync } from 'node:fs';
import { timingSafeEqual } from 'node:crypto';
import { openStore } from './store.mjs';
import { device } from './devices.mjs';
import { syncPending } from './sync.mjs';
import { kitchenTicketBytes, drawerPulseBytes, sendEscpos } from './escpos.mjs';

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
    if (req.method === 'POST' && req.url === '/sync') return send(res, 200, await syncPending(store, central, outlet));
    if (req.method === 'POST' && req.url === '/device/simulate') {
      const input = await body(req);
      return send(res, 200, await device(input.kind).perform(input.operation, input.payload));
    }
    if (req.method === 'POST' && req.url === '/device/kitchen/print') {
      const input = await body(req);
      const ticket = store.state().tickets.find(row => row.id === input.ticket_id);
      const order = ticket && store.getOrder(ticket.order_id);
      const result = await sendEscpos(process.env.TRT_KITCHEN_PRINTER_ADDRESS,
        kitchenTicketBytes(ticket, order, input.reprint === true));
      return send(res, 200, { ...result, ticket_id: ticket.id });
    }
    if (req.method === 'POST' && req.url === '/device/drawer/open') {
      const input = await body(req);
      const order = store.getOrder(input.order_id);
      if (!order?.cash.length) throw new Error('Recorded cash tender required to open drawer');
      const result = await sendEscpos(process.env.TRT_DRAWER_PRINTER_ADDRESS, drawerPulseBytes);
      return send(res, 200, { ...result, order_id: order.id });
    }
    return send(res, 404, { error: 'Not found' });
  } catch (error) { return send(res, 400, { error: String(error) }); }
});

server.listen(Number(process.env.TRT_GATEWAY_PORT || 8443), process.env.TRT_GATEWAY_HOST || '0.0.0.0');
