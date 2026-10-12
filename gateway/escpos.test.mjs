import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { kitchenTicketBytes, drawerPulseBytes, sendEscpos } from './escpos.mjs';

test('kitchen ticket and drawer pulse are bounded ESC/POS commands', async () => {
  const order = { id: 'local:order', remote_id: 'TRT-100', cash: [{ amount: 10 }] };
  const ticket = { id: 'localticket:1', order_id: order.id, station: 'Grill',
    lines: [{ name: 'Burger', qty: 2 }] };
  const bytes = kitchenTicketBytes(ticket, order);
  assert.match(bytes.toString('ascii'), /2 x Burger/);
  assert.equal(drawerPulseBytes.toString('hex'), '1b401b700019fa');
  assert.throws(() => kitchenTicketBytes({ ...ticket, lines: [{ name: 'غير مدعوم', qty: 1 }] }, order), /ASCII/);
  assert.throws(() => kitchenTicketBytes(ticket, { id: 'other' }), /Valid local/);

  const received = [];
  const server = createServer(socket => socket.on('data', chunk => received.push(chunk)));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const port = server.address().port;
    await sendEscpos(`127.0.0.1:${port}`, bytes);
    assert.deepEqual(Buffer.concat(received), bytes);
    assert.throws(() => sendEscpos('example.com:9100', bytes), /IPv4/);
  } finally {
    server.close();
  }
});
