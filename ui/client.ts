export type ApiResult<T> = { message: T; exc?: string };

declare global {
  interface Window { csrf_token?: string }
}

const base = '/api/method/table_remote_till.api.';

async function request<T>(method: string, args: Record<string, unknown>, write = false): Promise<T> {
  const url = base + method + (write ? '' : '?' + new URLSearchParams(
    Object.entries(args).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]),
  ));
  const csrf = window.csrf_token;
  const response = await fetch(url, {
    method: write ? 'POST' : 'GET',
    credentials: 'same-origin',
    headers: {
      'Accept': 'application/json',
      ...(write ? { 'Content-Type': 'application/json' } : {}),
      ...(csrf && !csrf.includes('{{') ? { 'X-Frappe-CSRF-Token': csrf } : {}),
    },
    body: write ? JSON.stringify(args) : undefined,
  });
  const data = await response.json().catch(() => ({})) as ApiResult<T> & { _server_messages?: string };
  if (!response.ok || data.exc) {
    let detail = `Request failed (${response.status})`;
    if (data._server_messages) {
      try { detail = JSON.parse(data._server_messages).map((line: string) => JSON.parse(line).message).join('\n'); }
      catch { /* keep HTTP status */ }
    }
    throw new Error(detail);
  }
  return data.message;
}

export const get = <T>(method: string, args: Record<string, unknown> = {}) => request<T>(method, args);
export const post = <T>(method: string, args: Record<string, unknown>) => request<T>(method, args, true);
export const eventId = () => crypto.randomUUID();

export type CatalogItem = {
  item: string; name_en: string; name_ar?: string; category?: string; rate: number; station?: string;
};
export type Outlet = {
  name: string; title: string; base_currency: string; cash_currency?: string;
  enable_tables: number; enable_tabs: number; enable_retail: number;
};
export type OrderLine = {
  name: string; item: string; item_name: string; qty: number; rate: number; amount: number; station?: string;
};
export type Order = {
  name: string; outlet: string; channel: string; status: string; revision: number;
  currency: string; net_total: number; tax_total: number; grand_total: number; pos_invoice?: string; lines: OrderLine[];
};
