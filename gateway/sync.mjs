// Replay local commands in order. A central timeout leaves the same event ID
// pending, so the next attempt asks ERPNext for the original committed result.
export async function syncPending(store, central, outlet) {
  const result = { applied: 0, conflicts: 0, offline: false };
  for (const event of store.pending()) {
    const command = JSON.parse(event.command_json);
    const order = store.getOrder(event.order_id);
    if (store.hasBlockingConflict(order.id)) {
      result.conflicts++;
      break;
    }
    if (command.action === 'cash_accepted') {
      // Cash is local evidence until one ERPNext POS Invoice settles all tenders.
      continue;
    }
    try {
      if (command.action === 'settle_cash') {
        if (!order.remote_id) throw new Error('Order has not synchronized');
        const expected_revision = store.remoteRevision(order.id);
        if (!Number.isInteger(expected_revision)) throw new Error('Remote order revision is unknown');
        const remote = await central('cash_checkout', {
          order_name: order.remote_id, event_id: event.event_id, expected_revision,
          tenders: order.cash.map(({ amount, currency, mode_of_payment }) =>
            ({ amount, currency, mode_of_payment })),
        }, true);
        if (remote.status !== 'Settled' || !remote.pos_invoice) {
          throw new Error('ERPNext did not confirm a settled POS Invoice');
        }
        store.mark(event.event_id, 'Applied', null, remote.revision);
        store.markCashSettled(order.id);
        result.applied++;
        continue;
      }
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
