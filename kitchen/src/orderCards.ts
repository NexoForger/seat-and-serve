export type Ticket = {
  name: string; order: string; station: string; status: string; sent_at: string;
  channel?: string; order_number?: string; table?: string; table_title?: string;
  parent_order_number?: string; tab_label?: string; station_title?: string; revision: number;
  runner_dispatched_at?: string; runner_dispatched_by?: string;
  lines: { name: string; item: string; item_name?: string; qty: number; note?: string; status: string }[];
};

export type OrderType = 'dine-in' | 'to-go' | 'kiosk' | 'counter' | 'other';
export type OrderCard = {
  order: string; orderNumber: string; channel: string; tableTitle: string; tabLabel: string; sentAt: string;
  tickets: Ticket[]; type: OrderType; runnerDispatchedAt?: string; parentOrderNumber?: string;
};

function orderType(channel: string): OrderType {
  if (['Table', 'Tab', 'QR'].includes(channel)) return 'dine-in';
  if (['Takeaway', 'Pickup'].includes(channel)) return 'to-go';
  if (channel === 'Kiosk') return 'kiosk';
  if (['Till', 'Retail'].includes(channel)) return 'counter';
  return 'other';
}

export function groupOrders(tickets: Ticket[]): OrderCard[] {
  const grouped = new Map<string, OrderCard>();
  for (const ticket of tickets) {
    if (ticket.status === 'Cancelled') continue;
    let card = grouped.get(ticket.order);
    if (!card) {
      card = {
        order: ticket.order, orderNumber: ticket.order_number || '', channel: ticket.channel || '',
        tableTitle: ticket.table_title || '', tabLabel: ticket.tab_label || '',
        sentAt: ticket.sent_at, tickets: [], type: orderType(ticket.channel || ''),
        runnerDispatchedAt: ticket.runner_dispatched_at, parentOrderNumber: ticket.parent_order_number,
      };
      grouped.set(ticket.order, card);
    }
    card.tickets.push(ticket);
    if (ticket.sent_at < card.sentAt) card.sentAt = ticket.sent_at;
  }
  return [...grouped.values()]
    .filter(card => card.tickets.some(ticket => ticket.status !== 'Served'))
    .sort((a, b) => a.sentAt.localeCompare(b.sentAt));
}
