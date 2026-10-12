import { connect, isIP } from 'node:net';

function target(address) {
  if (!address) throw new Error('ESC/POS printer address is not configured');
  const [host, portText = '9100'] = address.split(':');
  const port = Number(portText);
  if (isIP(host) !== 4 || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('ESC/POS target must be an IPv4 address with an optional port');
  }
  return { host, port };
}

function printable(value) {
  const result = String(value ?? '').replace(/[\x00-\x1f\x7f]/g, ' ').trim();
  if (result.length > 120 || /[^\x20-\x7e]/.test(result)) {
    throw new Error('This text printer requires ASCII lines of at most 120 characters');
  }
  return result;
}

export function kitchenTicketBytes(ticket, order, reprint = false) {
  if (!ticket?.id || !order?.id || ticket.order_id !== order.id ||
    !Array.isArray(ticket.lines) || !ticket.lines.length || ticket.lines.length > 100) {
    throw new Error('Valid local kitchen ticket and order required');
  }
  const lines = [reprint ? '*** REPRINT ***' : 'KITCHEN TICKET',
    `Ticket ${printable(ticket.id)}`, `Order ${printable(order.remote_id || order.id)}`,
    `Station ${printable(ticket.station)}`, '--------------------------------'];
  for (const line of ticket.lines) {
    if (!Number.isFinite(Number(line.qty)) || Number(line.qty) <= 0) throw new Error('Invalid ticket quantity');
    lines.push(`${Number(line.qty)} x ${printable(line.name || line.item)}`);
  }
  return Buffer.concat([Buffer.from([0x1b, 0x40]),
    Buffer.from(lines.join('\n') + '\n\n\n', 'ascii'),
    Buffer.from([0x1d, 0x56, 0x00])]);
}

export const drawerPulseBytes = Buffer.from([0x1b, 0x40, 0x1b, 0x70, 0x00, 0x19, 0xfa]);

export function sendEscpos(address, payload) {
  const { host, port } = target(address);
  return new Promise((resolve, reject) => {
    const socket = connect({ host, port });
    let done = false;
    const finish = error => {
      if (done) return;
      done = true;
      socket.destroy();
      error ? reject(error) : resolve({ sent: true });
    };
    socket.setTimeout(5000, () => finish(new Error('ESC/POS printer timed out')));
    socket.once('error', finish);
    socket.once('connect', () => socket.end(payload));
    socket.once('close', hadError => { if (!hadError) finish(); });
  });
}
