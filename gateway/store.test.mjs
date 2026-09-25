import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openStore } from './store.mjs';

test('local events persist, deduplicate, and enforce revisions', () => {
  const dir = mkdtempSync(join(tmpdir(), 'trt-gateway-'));
  try {
    const path = join(dir, 'queue.sqlite');
    let store = openStore(path);
    store.replaceCatalog('Till', 'USD', [{ item: 'SKU001', name_en: 'Coffee', rate: 4,
      station: 'Bar' }]);
    const created = store.apply({ event_id: 'create-1', expected_revision: 0,
      command: { action: 'create', channel: 'Till' } });
    const add = { event_id: 'add-1', order_id: created.id, expected_revision: 1,
      command: { action: 'add_line', item: 'SKU001', qty: 2 } };
    const added = store.apply(add);
    assert.equal(added.lines[0].rate, 4);
    assert.equal(store.apply(add).lines.length, 1);
    assert.throws(() => store.apply({ ...add, event_id: 'add-2' }), /revision conflict/);
    store.apply({ event_id: 'send-1', order_id: created.id, expected_revision: 2,
      command: { action: 'send' } });
    const ticket = store.state().tickets[0];
    assert.equal(ticket.station, 'Bar');
    assert.equal(store.updateTicket({ ticket_id: ticket.id, status: 'Preparing',
      event_id: 'ticket-1', expected_revision: 1 }).revision, 2);
    store.apply({ event_id: 'cash-1', order_id: created.id, expected_revision: 3,
      command: { action: 'cash_accepted', amount: 10, currency: 'USD' } });
    store.db.close();
    store = openStore(path);
    assert.equal(store.getOrder(created.id).cash[0].amount, 10);
    assert.equal(store.pending().length, 4);
    store.db.close();
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
