// Device contracts and a deterministic simulator for each required category.

class Simulator {
  constructor(kind, operations) {
    this.kind = kind;
    this.operations = operations;
    this.events = [];
  }
  async perform(operation, payload = {}) {
    if (!this.operations.includes(operation)) throw new Error(`Unsupported ${this.kind} operation`);
    const event = { kind: this.kind, operation, payload, at: new Date().toISOString() };
    this.events.push(event);
    return { simulated: true, event };
  }
}

export class ReceiptPrinterAdapter extends Simulator {
  constructor() { super('receipt_printer', ['print_receipt', 'test_print']); }
}
export class KitchenPrinterAdapter extends Simulator {
  constructor() { super('kitchen_printer', ['print_ticket', 'test_print']); }
}
export class BarcodeScannerAdapter extends Simulator {
  constructor() { super('barcode_scanner', ['scan']); }
  async perform(operation, payload = {}) {
    const result = await super.perform(operation, payload);
    return { ...result, barcode: String(payload.barcode || 'SIM-0001') };
  }
}
export class CashDrawerAdapter extends Simulator {
  constructor() { super('cash_drawer', ['open']); }
}
export class CustomerDisplayAdapter extends Simulator {
  constructor() { super('customer_display', ['show_total', 'clear']); }
}
export class ScaleAdapter extends Simulator {
  constructor() { super('scale', ['weigh', 'tare']); }
  async perform(operation, payload = {}) {
    const result = await super.perform(operation, payload);
    return { ...result, kilograms: operation === 'tare' ? 0 : Number(payload.kilograms || 0.5) };
  }
}
export class CardTerminalAdapter extends Simulator {
  constructor() { super('card_terminal', ['simulate_authorization', 'simulate_decline']); }
  async perform(operation, payload = {}) {
    const result = await super.perform(operation, payload);
    return { ...result, approved: operation === 'simulate_authorization', live_authorization: false };
  }
}

export const simulators = {
  receipt_printer: new ReceiptPrinterAdapter(),
  kitchen_printer: new KitchenPrinterAdapter(),
  barcode_scanner: new BarcodeScannerAdapter(),
  cash_drawer: new CashDrawerAdapter(),
  customer_display: new CustomerDisplayAdapter(),
  scale: new ScaleAdapter(),
  card_terminal: new CardTerminalAdapter(),
};

export function device(kind) {
  const adapter = simulators[kind];
  if (!adapter) throw new Error('Unknown device adapter');
  return adapter;
}
