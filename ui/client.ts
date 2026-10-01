export type ApiResult<T> = { message: T; exc?: string };

declare global {
  interface Window { csrf_token?: string }
}

const base = '/api/method/table_remote_till.api.';

async function request<T>(method: string, args: Record<string, unknown>, write = false): Promise<T> {
  const url = (method.includes('.') ? '/api/method/table_remote_till.' + method : base + method) + (write ? '' : '?' + new URLSearchParams(
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
export const eventId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

export type CatalogItem = {
  item: string; name_en: string; name_ar?: string; category?: string; rate: number; station?: string;
  deal_kind?: 'Combo' | 'Offer'; deal_description?: string;
  modifier_group?: ModifierGroup | null;
};
export type ModifierOption = { item: string; name_en: string; name_ar?: string; price_delta: number };
export type ModifierGroup = { name: string; title: string; minimum: number; options: ModifierOption[] };
export type GuestAppearance = {
  brand_logo: string; primary_color: string; accent_color: string; page_color: string;
  surface_color: string; text_color: string; muted_color: string; heading_font: string; body_font: string;
  brand_title_en: string; brand_title_ar: string; brand_tagline_en: string; brand_tagline_ar: string;
  hero_title_en: string; hero_title_ar: string;
  hero_subtitle_en: string; hero_subtitle_ar: string; hero_image: string;
  layout_style: 'Cards' | 'Compact list'; card_style: 'Soft' | 'Rounded' | 'Square';
  loading_message_en: string; loading_message_ar: string;
  loading_style: 'Food' | 'Sparkle' | 'Dots'; empty_style: 'Illustrated' | 'Simple';
  success_style: 'Confetti' | 'Sparkle' | 'Check'; motion_style: 'Playful' | 'Calm' | 'Reduced';
};
export type Outlet = {
  name: string; title: string; base_currency: string; cash_currency?: string;
  enable_tables: number; enable_tabs: number; enable_takeaway: number; enable_retail: number;
  appearance?: GuestAppearance;
};
export type OrderLine = {
  name: string; item: string; item_name: string; qty: number; rate: number; amount: number; station?: string;
  note?: string; modifiers?: ModifierOption[];
};
export type Order = {
  name: string; order_number: string; outlet: string; channel: string; table?: string; guest_count?: number; parent_order?: string; reservation?: string;
  status: string; revision: number; bill?: BillSummary; customer?: string;
  currency: string; net_total: number; tax_total: number; grand_total: number; pos_invoice?: string; lines: OrderLine[];
};
export type BillSummary = {
  ticket_count: number; root_revision: number; item_count: number; net_total: number; tax_total: number; grand_total: number;
  amount_due: number; customer?: string; customer_name?: string; promotion?: string; discount_amount: number; discount_label?: string;
  billing_errors?: string[];
  manual_discount_type?: 'Percentage' | 'Amount'; manual_discount_value?: number; manual_discount_reason?: string;
  loyalty: { program?: string; available_points: number; points: number; conversion_factor: number; amount: number };
  order_numbers: string[]; pos_invoice?: string;
  orders: { name: string; order_number: string; status: string; grand_total: number; pos_invoice?: string }[];
};
export type RegisterTableOrder = {
  name: string; order_number: string; table: string; status: string; guest_count: number;
  grand_total: number; line_count: number; parent_order?: string; runner_dispatched_at?: string;
  expired_empty_addon?: boolean;
  creation: string; modified: string;
};
export type RegisterTable = {
  name: string; title: string; seats: number; area: string; area_title: string;
  guest_count: number; orders: RegisterTableOrder[];
  next_reservation?: { reservation_number: string; guest_name: string; party_size: number; time: string; status: string } | null;
};
export type Reservation = {
  name: string; reservation_number: string; guest_name: string; phone?: string; email?: string;
  party_size: number; starts_at: string; ends_at: string; time: string; status: string; source: string;
  special_requests?: string; table: string; table_title: string; order?: string; order_number?: string;
};
