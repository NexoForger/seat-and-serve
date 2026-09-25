import test from 'node:test';
import assert from 'node:assert/strict';
import { device } from './devices.mjs';

test('every device category has a bounded simulator', async () => {
  const cases = [
    ['receipt_printer', 'print_receipt'], ['kitchen_printer', 'print_ticket'],
    ['barcode_scanner', 'scan'], ['cash_drawer', 'open'],
    ['customer_display', 'show_total'], ['scale', 'weigh'],
    ['card_terminal', 'simulate_authorization'],
  ];
  for (const [kind, operation] of cases) {
    assert.equal((await device(kind).perform(operation)).simulated, true);
    await assert.rejects(device(kind).perform('unknown'), /Unsupported/);
  }
  assert.equal((await device('card_terminal').perform('simulate_authorization')).live_authorization, false);
});
