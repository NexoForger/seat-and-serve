import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';

export function openStore(path) {
  const db = new DatabaseSync(path);
  db.exec('PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;');
  db.exec(`CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, remote_id TEXT, channel TEXT NOT NULL,
    revision INTEGER NOT NULL, status TEXT NOT NULL, lines_json TEXT NOT NULL,
    cash_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, command_json TEXT NOT NULL,
    expected_revision INTEGER NOT NULL, status TEXT NOT NULL,
    error TEXT, remote_revision INTEGER, created_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
  );
  CREATE TABLE IF NOT EXISTS catalog (
    channel TEXT NOT NULL, item TEXT NOT NULL, name TEXT NOT NULL,
    rate REAL NOT NULL, currency TEXT NOT NULL, station TEXT,
    PRIMARY KEY(channel, item)
  );
  CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, order_id TEXT NOT NULL, station TEXT NOT NULL,
    status TEXT NOT NULL, revision INTEGER NOT NULL, lines_json TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
  );
  CREATE TABLE IF NOT EXISTS ticket_events (
    event_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(id)
  );`);
  if (!db.prepare('PRAGMA table_info(catalog)').all().some(column => column.name === 'station')) {
    db.exec('ALTER TABLE catalog ADD COLUMN station TEXT');
  }

  const orderRow = db.prepare('SELECT * FROM orders WHERE id=?');
  const eventRow = db.prepare('SELECT * FROM events WHERE event_id=?');
  const catalogRow = db.prepare('SELECT * FROM catalog WHERE channel=? AND item=?');
  const insertOrder = db.prepare('INSERT INTO orders (id, channel, revision, status, lines_json, updated_at) VALUES (?,?,?,?,?,?)');
  const updateOrder = db.prepare('UPDATE orders SET revision=?, status=?, lines_json=?, cash_json=?, updated_at=? WHERE id=?');
  const insertEvent = db.prepare('INSERT INTO events (event_id, order_id, command_json, expected_revision, status, created_at) VALUES (?,?,?,?,?,?)');

  function getOrder(id) {
    const row = orderRow.get(id);
    return row && { id: row.id, remote_id: row.remote_id, channel: row.channel,
      revision: row.revision, status: row.status, lines: JSON.parse(row.lines_json),
      cash: JSON.parse(row.cash_json), updated_at: row.updated_at };
  }

  function apply({ event_id, order_id, expected_revision, command }) {
    if (!event_id || !command || typeof command !== 'object' || !Number.isInteger(expected_revision)) {
      throw new Error('Event ID, revision, and command are required');
    }
    const prior = eventRow.get(event_id);
    if (prior) {
      if (prior.order_id !== order_id && order_id || JSON.stringify(command) !== prior.command_json ||
        expected_revision !== prior.expected_revision) throw new Error('Event ID belongs to another command');
      return getOrder(prior.order_id);
    }
    const id = order_id || `local:${randomUUID()}`;
    const existing = getOrder(id);
    if (command.action === 'create') {
      if (existing || expected_revision !== 0) throw new Error('New order requires revision zero');
      if (!['Till', 'Table', 'Tab', 'Takeaway', 'Retail'].includes(command.channel)) {
        throw new Error('Gateway accepts staff channels only');
      }
    } else if (!existing || existing.revision !== expected_revision) {
      throw new Error('Order revision conflict');
    }
    if (existing && ['Settled', 'Void'].includes(existing.status)) throw new Error('Order is closed');
    if (existing && existing.status !== 'Draft' && ['add_line', 'set_qty'].includes(command.action)) {
      throw new Error('Sent order cannot be changed');
    }
    const order = existing || { id, channel: command.channel, revision: 0,
      status: 'Draft', lines: [], cash: [] };
    if (command.action === 'add_line') {
      const item = catalogRow.get(order.channel, command.item);
      if (!item || !(Number(command.qty) > 0)) throw new Error('Item unavailable in cached catalog');
      order.lines.push({ id: randomUUID(), item: item.item, name: item.name,
        qty: Number(command.qty), rate: item.rate, currency: item.currency,
        station: item.station });
    } else if (command.action === 'set_qty') {
      const line = order.lines.find(row => row.id === command.line);
      if (!line || Number(command.qty) < 0) throw new Error('Invalid line or quantity');
      if (Number(command.qty) === 0) order.lines = order.lines.filter(row => row !== line);
      else line.qty = Number(command.qty);
    } else if (command.action === 'send') {
      if (!order.lines.length) throw new Error('Empty order');
      order.status = 'Sent';
    } else if (command.action === 'cash_accepted') {
      if (!(Number(command.amount) > 0) || !['USD', 'LBP'].includes(command.currency)) {
        throw new Error('Invalid cash tender');
      }
      order.cash.push({ amount: Number(command.amount), currency: command.currency,
        accepted_at: new Date().toISOString(), event_id });
    } else if (command.action !== 'create') throw new Error('Unknown command');
    const now = new Date().toISOString();
    db.exec('BEGIN IMMEDIATE');
    try {
      if (existing) updateOrder.run(order.revision + 1, order.status,
        JSON.stringify(order.lines), JSON.stringify(order.cash), now, id);
      else insertOrder.run(id, order.channel, 1, order.status, '[]', now);
      insertEvent.run(event_id, id, JSON.stringify(command), expected_revision, 'Pending', now);
      if (command.action === 'send') {
        const stations = new Map();
        for (const line of order.lines) {
          if (line.station) stations.set(line.station, [...(stations.get(line.station) || []), line]);
        }
        const insertTicket = db.prepare('INSERT INTO tickets VALUES (?,?,?,?,?,?)');
        for (const [station, lines] of stations) {
          insertTicket.run(`localticket:${randomUUID()}`, id, station, 'Queued', 1, JSON.stringify(lines));
        }
      }
      db.exec('COMMIT');
    } catch (error) { db.exec('ROLLBACK'); throw error; }
    return getOrder(id);
  }

  return {
    db, getOrder, apply,
    state() {
      return {
        orders: db.prepare('SELECT id FROM orders ORDER BY updated_at DESC').all().map(row => getOrder(row.id)),
        events: db.prepare('SELECT event_id, order_id, status, error, created_at FROM events ORDER BY created_at').all(),
        tickets: db.prepare('SELECT * FROM tickets ORDER BY rowid').all().map(row => ({
          id: row.id, order_id: row.order_id, station: row.station, status: row.status,
          revision: row.revision, lines: JSON.parse(row.lines_json),
        })),
      };
    },
    replaceCatalog(channel, currency, items) {
      db.exec('BEGIN IMMEDIATE');
      try {
        db.prepare('DELETE FROM catalog WHERE channel=?').run(channel);
        const insert = db.prepare('INSERT INTO catalog VALUES (?,?,?,?,?,?)');
        for (const item of items) insert.run(channel, item.item, item.name_en,
          Number(item.rate), currency, item.station || null);
        db.exec('COMMIT');
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    pending() { return db.prepare("SELECT * FROM events WHERE status='Pending' ORDER BY created_at, rowid").all(); },
    mark(event_id, status, error, remote_revision) {
      db.prepare('UPDATE events SET status=?, error=?, remote_revision=? WHERE event_id=?')
        .run(status, error || null, remote_revision || null, event_id);
    },
    setRemote(id, remote_id) {
      db.prepare('UPDATE orders SET remote_id=? WHERE id=?').run(remote_id, id);
    },
    updateTicket({ ticket_id, status, event_id, expected_revision }) {
      const prior = db.prepare('SELECT * FROM ticket_events WHERE event_id=?').get(event_id);
      if (prior) {
        if (prior.ticket_id !== ticket_id || prior.status !== status) throw new Error('Event ID belongs to another ticket');
        return db.prepare('SELECT * FROM tickets WHERE id=?').get(ticket_id);
      }
      const ticket = db.prepare('SELECT * FROM tickets WHERE id=?').get(ticket_id);
      const next = { Queued: 'Preparing', Preparing: 'Ready', Ready: 'Served' };
      if (!ticket || ticket.revision !== expected_revision || next[ticket.status] !== status) {
        throw new Error('Ticket revision or status conflict');
      }
      db.exec('BEGIN IMMEDIATE');
      try {
        db.prepare('UPDATE tickets SET status=?, revision=? WHERE id=?').run(status, expected_revision + 1, ticket_id);
        db.prepare('INSERT INTO ticket_events VALUES (?,?,?,?)')
          .run(event_id, ticket_id, status, new Date().toISOString());
        db.exec('COMMIT');
      } catch (error) { db.exec('ROLLBACK'); throw error; }
      return db.prepare('SELECT * FROM tickets WHERE id=?').get(ticket_id);
    },
  };
}
