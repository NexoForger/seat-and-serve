import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openStore } from './store.mjs';
import { syncPending } from './sync.mjs';

test('offline cash stays provisional through timeout and settles once after replay', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'trt-sync-'));
  const store = openStore(join(dir, 'queue.sqlite'));
  try {
    store.replaceCatalog('Till', 'USD', [{ item: 'SKU001', name_en: 'Coffee', rate: 4,
      station: 'Bar' }]);
    const created = store.apply({ event_id: 'create', expected_revision: 0,
      command: { action: 'create', channel: 'Till' } });
    store.apply({ event_id: 'add', order_id: created.id, expected_revision: 1,
      command: { action: 'add_line', item: 'SKU001', qty: 1 } });
    store.apply({ event_id: 'send', order_id: created.id, expected_revision: 2,
      command: { action: 'send' } });
    store.apply({ event_id: 'cash', order_id: created.id, expected_revision: 3,
      command: { action: 'cash_accepted', amount: 4, currency: 'USD', mode_of_payment: 'Cash' } });
    store.apply({ event_id: 'settle', order_id: created.id, expected_revision: 4,
      command: { action: 'settle_cash' } });
    let timeout = true;
    const captured = [];
    const central = async (method, args) => {
      if (method === 'order_command') {
        const revision = { create: 1, add: 2, send: 3 }[args.event_id];
        return { name: 'REMOTE-1', revision, status: args.command.action === 'send' ? 'Sent' : 'Draft',
          lines: args.command.action === 'create' ? [] : [{ item: 'SKU001', rate: 4 }] };
      }
      assert.equal(method, 'cash_checkout');
      captured.push(args);
      if (timeout) {
        timeout = false;
        throw new TypeError('network lost after commit');
      }
      return { name: 'REMOTE-1', revision: 4, status: 'Settled', pos_invoice: 'POS-1' };
    };
    assert.deepEqual(await syncPending(store, central, 'OUTLET-1'),
      { applied: 3, conflicts: 0, offline: true });
    assert.equal(store.getOrder(created.id).status, 'CashPending');
    assert.deepEqual(await syncPending(store, central, 'OUTLET-1'),
      { applied: 1, conflicts: 0, offline: false });
    assert.equal(store.getOrder(created.id).status, 'Settled');
    assert.equal(store.pending().length, 0);
    assert.equal(captured.length, 2);
    assert.deepEqual(captured[0], captured[1]);
    assert.equal(captured[0].expected_revision, 3);
    assert.deepEqual(captured[0].tenders,
      [{ amount: 4, currency: 'USD', mode_of_payment: 'Cash' }]);
  } finally {
    store.db.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
