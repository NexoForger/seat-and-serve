<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { eventId, get, post, type CatalogItem, type Order, type Outlet, type RegisterTable, type RegisterTableOrder, type Reservation } from '../../ui/client';
import '../../ui/styles.css';
import './register.css';
import Icon from '../../ui/Icon.vue';
import Feedback from '../../ui/Feedback.vue';
import ModifierPicker from '../../ui/ModifierPicker.vue';
import { money } from '../../ui/format';

const outlets = ref<Outlet[]>([]);
const outlet = ref('');
const channel = ref('');
const step = ref<'type' | 'tables' | 'reservations' | 'catalog'>('type');
const catalog = ref<CatalogItem[]>([]);
const order = ref<Order | null>(null);
const search = ref('');
const tabLabel = ref('');
const notice = ref('');
const noticeKind = ref<'success' | 'info' | 'warning' | 'error' | 'busy'>('info');
const busy = ref(false);
const options = ref<{ cash_modes: string[]; base_currency: string; fx_rate?: { lbp_per_usd: number };
  opening_entry?: string; pos_invoice_mode: boolean } | null>(null);
const tenders = ref<{ mode_of_payment: string; currency: string; amount: number }[]>([]);
const canManageDiscount = ref(false);
const billCustomer = ref('');
const selectedCustomerName = ref('');
const customerQuery = ref('');
const customerMatches = ref<{ name: string; customer_name: string; mobile_no?: string }[]>([]);
const couponInput = ref('');
const manualType = ref<'' | 'Percentage' | 'Amount'>('');
const manualValue = ref(0);
const manualReason = ref('');
const loyaltyPoints = ref(0);
const language = ref<'en' | 'ar'>('en');
const rtl = computed(() => language.value === 'ar');
const text = (en: string, ar: string) => rtl.value ? ar : en;
function setNotice(message: string, kind: typeof noticeKind.value = 'info') {
  notice.value = message;
  noticeKind.value = kind;
}
const category = ref('');
const loading = ref(true);
const showPayment = ref(false);
const showTools = ref(false);
const showSearch = ref(false);
const selectedItem = ref<CatalogItem | null>(null);
const tables = ref<RegisterTable[]>([]);
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const reservationDate = ref(localDate());
const reservationParty = ref(2);
const reservationTable = ref('');
const reservationTime = ref('');
const reservationSlots = ref<string[]>([]);
const reservationRows = ref<Reservation[]>([]);
const reservationGuest = ref('');
const reservationPhone = ref('');
const reservationEmail = ref('');
const reservationNotes = ref('');
const reservationLoading = ref(false);
const pendingSeatedOrder = ref<Order | null>(null);
const selectedTable = ref<RegisterTable | null>(null);
const selectedTableTickets = computed(() => [...(selectedTable.value?.orders || [])]
  .sort((a, b) => Number(b.line_count > 0) - Number(a.line_count > 0)));
const runnerNeeded = (table: RegisterTable) => table.orders.some(ticket =>
  ticket.status === 'Ready' && !!ticket.runner_dispatched_at);
const tableAreas = computed(() => {
  const groups = new Map<string, { title: string; tables: RegisterTable[] }>();
  for (const table of tables.value) {
    const key = table.area || 'dining-room';
    if (!groups.has(key)) groups.set(key, { title: table.area_title || text('Dining room', 'صالة الطعام'), tables: [] });
    groups.get(key)?.tables.push(table);
  }
  return [...groups.values()];
});
const guestCount = ref(2);
const selectedOutlet = computed(() => outlets.value.find(row => row.name === outlet.value));
const DEALS_CATEGORY = '__deals__';
const hasDeals = computed(() => catalog.value.some(item => item.deal_kind === 'Combo' || item.deal_kind === 'Offer'));
const categories = computed(() => [...new Set(catalog.value.filter(item => !item.deal_kind).map(item => item.category).filter(Boolean))] as string[]);
const displayCategory = (name: string) => name.replace(/^TRT SAMPLE\s+/i, '');
const itemCount = computed(() => order.value?.lines.reduce((sum, line) => sum + line.qty, 0) || 0);
const billTicketCount = computed(() => order.value?.bill?.ticket_count || 1);
const billItemCount = computed(() => order.value?.bill?.item_count || itemCount.value);
const billNetTotal = computed(() => order.value?.bill?.net_total ?? order.value?.net_total ?? 0);
const billTaxTotal = computed(() => order.value?.bill?.tax_total ?? order.value?.tax_total ?? 0);
const billGrandTotal = computed(() => order.value?.bill?.grand_total ?? order.value?.grand_total ?? 0);
const billAmountDue = computed(() => order.value?.bill?.amount_due ?? billGrandTotal.value);
const billOrderNumbers = computed(() => order.value?.bill?.order_numbers || (order.value ? [order.value.order_number] : []));
const billSettingsDirty = computed(() => !!order.value?.bill && (
  billCustomer.value !== (order.value.bill.customer || '') ||
  couponInput.value.trim().toUpperCase() !== (order.value.bill.promotion || '') ||
  manualType.value !== (order.value.bill.manual_discount_type || '') ||
  (manualType.value !== '' && (manualValue.value !== (order.value.bill.manual_discount_value || 0) ||
    manualReason.value.trim() !== (order.value.bill.manual_discount_reason || ''))) ||
  loyaltyPoints.value !== (order.value.bill.loyalty?.points || 0)));
const editable = computed(() => !order.value || order.value.status === 'Draft');
const visibleItems = computed(() => catalog.value.filter(item =>
  (!category.value || (category.value === DEALS_CATEGORY ? !!item.deal_kind : item.category === category.value)) &&
  [item.item, item.name_en, item.name_ar || '', item.deal_description || ''].some(value =>
    value.toLowerCase().includes(search.value.trim().toLowerCase()))));
const itemGroups = computed(() => {
  const groups = new Map<string, CatalogItem[]>();
  for (const item of visibleItems.value) {
    const name = item.deal_kind === 'Combo' ? text('Combo deals', 'الوجبات المجمّعة') :
      item.deal_kind === 'Offer' ? text('Offers', 'العروض') : item.category || text('Other items', 'أصناف أخرى');
    groups.set(name, [...(groups.get(name) || []), item]);
  }
  return [...groups].map(([name, items]) => ({ name, items, tone: items[0]?.deal_kind ? 2 : Math.max(0, categories.value.indexOf(name)) % 4 }));
});
const price = (value: number) => money(value, order.value?.currency || selectedOutlet.value?.base_currency || 'USD', language.value);
const saleTypes = [
  { value: 'Table', en: 'Dine in', ar: 'داخل المطعم', detail: 'Choose a table and resume its tickets', detailAr: 'اختر طاولة واستأنف طلباتها', icon: 'grid' },
  { value: 'Takeaway', en: 'Takeaway', ar: 'سفري', detail: 'Prepare an order for collection', detailAr: 'جهّز طلباً للاستلام', icon: 'bag' },
  { value: 'Till', en: 'Counter', ar: 'الصندوق', detail: 'Serve and charge at the register', detailAr: 'خدمة ودفع عند الصندوق', icon: 'till' },
  { value: 'Tab', en: 'Open tab', ar: 'حساب مفتوح', detail: 'Keep a running guest tab', detailAr: 'افتح حساباً مستمراً للضيف', icon: 'list' },
  { value: 'Retail', en: 'Retail', ar: 'تجزئة', detail: 'Sell packaged or retail items', detailAr: 'بيع الأصناف المعبأة', icon: 'bag' },
];
const availableSaleTypes = computed(() => saleTypes.filter(sale =>
  sale.value === 'Table' ? selectedOutlet.value?.enable_tables :
  sale.value === 'Takeaway' ? selectedOutlet.value?.enable_takeaway :
  sale.value === 'Tab' ? selectedOutlet.value?.enable_tabs :
  sale.value === 'Retail' ? selectedOutlet.value?.enable_retail : true));
const channelTitle = computed(() => saleTypes.find(sale => sale.value === channel.value));

async function load() {
  try {
    const data = await get<{ outlets: Outlet[]; roles: string[] }>('bootstrap');
    outlets.value = data.outlets;
    canManageDiscount.value = data.roles.some(role => role === 'System Manager' || role === 'TRT Manager');
    outlet.value ||= data.outlets[0]?.name || '';
    await loadTables();
    if (!outlet.value) setNotice(text('Configure an outlet in Frappe Desk to begin.', 'أضف فرعاً في فرابي للبدء.'), 'warning');
  } catch (error) { setNotice(String(error), 'error'); }
  finally { loading.value = false; }
}

async function loadTables() {
  if (!outlet.value) return;
  try {
    let data = await get<RegisterTable[]>('register_tables', { outlet: outlet.value });
    if (data.some(table => table.orders.some(ticket => ticket.expired_empty_addon))) {
      await post('cleanup_empty_addon_drafts', { outlet: outlet.value });
      data = await get<RegisterTable[]>('register_tables', { outlet: outlet.value });
    }
    tables.value = data;
    if (selectedTable.value) {
      selectedTable.value = data.find(table => table.name === selectedTable.value?.name) || null;
    }
    if (order.value?.channel === 'Table' && order.value.parent_order && order.value.status === 'Draft' &&
      !order.value.lines.length && !data.some(table => table.orders.some(ticket => ticket.name === order.value?.name))) {
      order.value = null;
      tenders.value = [];
      showPayment.value = false;
      setNotice(text('The empty add-on expired after 5 minutes. Tap an item to start a new one.',
        'انتهت صلاحية الطلب الإضافي الفارغ بعد ٥ دقائق. اضغط على صنف لبدء طلب جديد.'), 'warning');
    }
  } catch (error) { setNotice(String(error), 'error'); }
}

async function loadCatalog() {
  if (!outlet.value || !channel.value) return;
  order.value = null;
  selectedItem.value = null;
  tenders.value = [];
  catalog.value = []; options.value = null; category.value = ''; search.value = '';
  loading.value = true; notice.value = ''; showPayment.value = false;
  try {
    const data = await get<{ items: CatalogItem[] }>('catalog', { outlet: outlet.value, channel: channel.value });
    catalog.value = data.items;
    options.value = await get('checkout_options', { outlet: outlet.value });
    await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { loading.value = false; }
}

async function openTableOrder(ticket: RegisterTableOrder) {
  if (!selectedTable.value || busy.value || loading.value) return;
  const tableName = selectedTable.value.name;
  order.value = null;
  tenders.value = [];
  showPayment.value = false;
  busy.value = true; notice.value = '';
  try {
    const saved = await get<Order>('register_order', { outlet: outlet.value, order_name: ticket.name });
    if (saved.channel !== 'Table' || saved.table !== tableName || selectedTable.value?.name !== tableName)
      throw new Error(text('This ticket does not belong to the selected table.', 'هذا الطلب لا يخص الطاولة المحددة.'));
    order.value = saved;
    guestCount.value = saved.guest_count || guestCount.value;
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function selectTable(table: RegisterTable) {
  if (busy.value || loading.value) return;
  if (selectedTable.value?.name === table.name && order.value?.table === table.name) {
    step.value = 'catalog';
    return;
  }
  selectedTable.value = table;
  guestCount.value = table.guest_count || Math.min(table.seats || 2, 2);
  order.value = null;
  tenders.value = [];
  showPayment.value = false;
  step.value = 'catalog';
  if (selectedTableTickets.value.length) await openTableOrder(selectedTableTickets.value[0]);
}

function openReservations() {
  if (busy.value || loading.value || !selectedOutlet.value?.enable_tables) return;
  if (order.value?.status === 'Draft' && order.value.lines.length &&
    !window.confirm(text('Leave this draft? It stays saved in the register.', 'مغادرة المسودة؟ ستبقى محفوظة في الصندوق.'))) return;
  channel.value = '';
  order.value = null;
  selectedTable.value = null;
  step.value = 'reservations';
  showTools.value = false;
  notice.value = '';
  void refreshReservations();
}

async function refreshReservations() {
  if (!outlet.value) return;
  reservationLoading.value = true;
  try {
    reservationRows.value = await get<Reservation[]>('reservations.register_reservations',
      { outlet: outlet.value, date: reservationDate.value });
    await refreshReservationSlots();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { reservationLoading.value = false; }
}

async function refreshReservationSlots() {
  reservationTime.value = '';
  reservationSlots.value = [];
  if (!outlet.value || !reservationDate.value || !reservationParty.value) return;
  try {
    const available = await get<{ slots: string[] }>('reservations.reservation_availability', {
      outlet: outlet.value, date: reservationDate.value, party_size: reservationParty.value,
      table: reservationTable.value || undefined,
    });
    reservationSlots.value = available.slots;
  } catch (error) { setNotice(String(error), 'error'); }
}

async function bookAtRegister() {
  if (!reservationTime.value || busy.value) return;
  busy.value = true; notice.value = '';
  try {
    const saved = await post<{ reservation_number: string }>('reservations.register_book_reservation', {
      request_id: eventId(), payload: { outlet: outlet.value, date: reservationDate.value,
        time: reservationTime.value, party_size: reservationParty.value,
        guest_name: reservationGuest.value.trim(), phone: reservationPhone.value.trim(),
        email: reservationEmail.value.trim(), special_requests: reservationNotes.value.trim(),
        table: reservationTable.value || undefined },
    });
    setNotice(text(`Reservation ${saved.reservation_number} confirmed.`, `تم تأكيد الحجز ${saved.reservation_number}.`), 'success');
    reservationGuest.value = ''; reservationPhone.value = ''; reservationEmail.value = '';
    reservationNotes.value = '';
    await refreshReservations();
    await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function changeReservation(row: Reservation, action: 'Cancelled' | 'No Show') {
  if (busy.value) return;
  busy.value = true; notice.value = '';
  try {
    await post('reservations.update_reservation', { reservation_name: row.name, action });
    setNotice(text('Reservation updated.', 'تم تحديث الحجز.'), 'success');
    await refreshReservations(); await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function seatReservation(row: Reservation) {
  if (busy.value) return;
  busy.value = true; notice.value = '';
  try {
    pendingSeatedOrder.value = await post<Order>('reservations.seat_reservation', {
      reservation_name: row.name, request_id: eventId(),
    });
    step.value = 'catalog';
    channel.value = 'Table';
    setNotice(text(`${row.guest_name} seated at ${row.table_title}.`, `جلس ${row.guest_name} على ${row.table_title}.`), 'success');
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function chooseType(value: string) {
  if (busy.value || loading.value) return;
  selectedTable.value = null;
  order.value = null;
  channel.value = value;
  step.value = value === 'Table' ? 'tables' : 'catalog';
  notice.value = '';
  if (value === 'Table') await loadTables();
}

function showTypes() {
  if (busy.value || loading.value) return;
  if (order.value?.status === 'Draft' && order.value.lines.length && order.value.channel !== 'Table' &&
    !window.confirm(text('Leave this order? Its draft stays saved in the system.', 'مغادرة هذا الطلب؟ ستبقى المسودة محفوظة في النظام.'))) return;
  step.value = 'type';
  channel.value = '';
  selectedTable.value = null;
  order.value = null;
  showPayment.value = false;
  notice.value = '';
}

function chooseTicket(event: Event) {
  const ticket = selectedTableTickets.value.find(row => row.name === (event.target as HTMLSelectElement).value);
  if (ticket) void openTableOrder(ticket);
}

const tableContextLabel = computed(() => {
  if (channel.value !== 'Table') return '';
  if (!selectedTable.value) return text('Choose a table above', 'اختر طاولة من الأعلى');
  if (order.value?.table === selectedTable.value.name)
    return `${text('Viewing', 'عرض')} ${order.value.order_number} · ${order.value.status}`;
  if (selectedTable.value.orders.length) return text('Choose an open ticket or start an add-on order.', 'اختر طلباً مفتوحاً أو ابدأ طلباً إضافياً.');
  return text('New order for ', 'طلب جديد لـ ') + selectedTable.value.title;
});

async function createOrder() {
  if (!outlet.value) return;
  if (channel.value === 'Table' && !selectedTable.value) {
    setNotice(text('Choose a table first.', 'اختر طاولة أولاً.'), 'warning');
    return;
  }
  if (order.value?.status === 'Draft' && !order.value.lines.length) {
    setNotice(text('This ticket is empty. Add an item to use it.', 'هذا الطلب فارغ. أضف صنفاً لاستخدامه.'), 'warning');
    return;
  }
  if (order.value?.status === 'Draft' && order.value.lines.length &&
    !window.confirm(text('Start a new order? The current draft will remain open in the system.', 'هل تريد بدء طلب جديد؟ سيبقى الطلب الحالي مفتوحاً في النظام.'))) return;
  const currentOrder = order.value;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'create', outlet: outlet.value, channel: channel.value,
        ...(channel.value === 'Table' ? {
          table: selectedTable.value?.name,
          guest_count: guestCount.value,
          parent_order: currentOrder?.table === selectedTable.value?.name &&
            currentOrder?.status !== 'Settled' && currentOrder?.status !== 'Void'
            ? currentOrder?.name
            : (selectedTableTickets.value.find(ticket => ticket.line_count > 0) || selectedTableTickets.value[0])?.name,
        } : {}),
        tab_label: tabLabel.value || undefined },
      event_id: eventId(), expected_revision: 0,
    });
    setNotice(text('Order started.', 'بدأ الطلب.'), 'success');
    tenders.value = []; showPayment.value = false;
    if (channel.value === 'Table') await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

function choose(item: CatalogItem) {
  if (item.modifier_group) selectedItem.value = item;
  else void add(item);
}

async function addSelected(modifiers: string[], note: string) {
  if (selectedItem.value) await add(selectedItem.value, modifiers, note);
}

async function add(item: CatalogItem, modifiers: string[] = [], note = '') {
  if (busy.value || !editable.value) return;
  if (!order.value) await createOrder();
  if (!order.value) return;
  const attemptedOrder = order.value;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'add_line', item: item.item, qty: 1, modifiers, note }, event_id: eventId(),
      order_name: order.value.name, expected_revision: order.value.revision,
    });
    if (tenders.value.length === 1 && tenders.value[0].currency === order.value.currency)
      tenders.value[0].amount = billAmountDue.value;
    selectedItem.value = null;
    setNotice(text(`${item.name_en} added to the order.`, `تمت إضافة ${item.name_ar || item.name_en} إلى الطلب.`), 'success');
  } catch (error) {
    if (attemptedOrder.channel === 'Table' && attemptedOrder.parent_order && !attemptedOrder.lines.length) {
      await loadTables();
      if (!order.value) return;
    }
    setNotice(String(error), 'error');
  }
  finally { busy.value = false; }
}

async function changeQty(line: Order['lines'][number], qty: number) {
  if (!order.value || busy.value || !editable.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'set_qty', line: line.name, qty }, event_id: eventId(),
      order_name: order.value.name, expected_revision: order.value.revision,
    });
    if (tenders.value.length === 1 && tenders.value[0].currency === order.value.currency)
      tenders.value[0].amount = billAmountDue.value;
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

function addTender() {
  tenders.value.push({ mode_of_payment: options.value?.cash_modes[0] || 'Cash',
    currency: order.value?.currency || 'USD', amount: tenders.value.length ? 0 : billAmountDue.value });
}

function syncBillSettings() {
  const bill = order.value?.bill;
  if (!bill) return;
  billCustomer.value = bill.customer || '';
  selectedCustomerName.value = bill.customer_name || bill.customer || '';
  customerQuery.value = '';
  customerMatches.value = [];
  couponInput.value = bill.promotion || '';
  manualType.value = bill.manual_discount_type || '';
  manualValue.value = bill.manual_discount_value || 0;
  manualReason.value = bill.manual_discount_reason || '';
  loyaltyPoints.value = bill.loyalty?.points || 0;
}

async function searchCustomers() {
  if (customerQuery.value.trim().length < 2) return;
  try {
    customerMatches.value = await get('register_customers', { outlet: outlet.value, query: customerQuery.value.trim() });
  } catch (error) { setNotice(String(error), 'error'); }
}

async function applyBillSettings() {
  if (!order.value || busy.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('configure_bill', {
      order_name: order.value.name, expected_revision: order.value.bill?.root_revision ?? order.value.revision,
      event_id: eventId(), config: {
        customer: billCustomer.value, coupon_code: couponInput.value.trim().toUpperCase(),
        manual_discount_type: manualType.value, manual_discount_value: manualValue.value,
        manual_discount_reason: manualReason.value.trim(), loyalty_points: loyaltyPoints.value,
      },
    });
    syncBillSettings();
    if (tenders.value.length === 1 && tenders.value[0].currency === order.value.currency)
      tenders.value[0].amount = billAmountDue.value;
    setNotice(text('Bill savings and customer updated.', 'تم تحديث العميل وخصومات الحساب.'), 'success');
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function togglePayment() {
  if (showPayment.value) { showPayment.value = false; return; }
  if (!order.value || busy.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await get<Order>('register_order', { outlet: outlet.value, order_name: order.value.name });
    if (order.value.status === 'Settled') {
      setNotice(text('This table bill is already paid.', 'تم دفع حساب هذه الطاولة.'), 'warning');
      return;
    }
    showPayment.value = true;
    syncBillSettings();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function checkout() {
  if (!order.value) return;
  if (billSettingsDirty.value) {
    setNotice(text('Apply bill settings before payment.', 'طبّق إعدادات الحساب قبل الدفع.'), 'warning');
    return;
  }
  busy.value = true; notice.value = '';
  try {
    const previousTotal = billAmountDue.value;
    order.value = await get<Order>('register_order', { outlet: outlet.value, order_name: order.value.name });
    if (Math.abs(billAmountDue.value - previousTotal) > 0.001) {
      setNotice(text('The table bill changed. Review the payment amount and confirm again.', 'تغيّر حساب الطاولة. راجع قيمة الدفع ثم أكّد مجدداً.'), 'warning');
      return;
    }
    const chosen = billAmountDue.value <= 0 ? [] : tenders.value.length ? tenders.value : [{
      mode_of_payment: options.value?.cash_modes[0] || 'Cash',
      currency: order.value.currency, amount: billAmountDue.value,
    }];
    order.value = await post<Order>('cash_checkout', { order_name: order.value.name,
      tenders: chosen, event_id: eventId(), expected_revision: order.value.revision });
    setNotice(text(`Paid · POS Invoice ${order.value.pos_invoice}`, 'تم الدفع وتسجيل فاتورة نقطة البيع'), 'success');
    options.value = await get('checkout_options', { outlet: outlet.value });
    if (channel.value === 'Table') await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

async function send() {
  if (!order.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'send' }, event_id: eventId(),
      order_name: order.value.name, expected_revision: order.value.revision,
    });
    setNotice(text('Sent to kitchen.', 'أُرسل الطلب إلى المطبخ.'), 'success');
    await loadTables();
  } catch (error) { setNotice(String(error), 'error'); }
  finally { busy.value = false; }
}

watch(outlet, async (nextOutlet, previousOutlet) => {
  if (!nextOutlet || !previousOutlet || nextOutlet === previousOutlet) return;
  channel.value = '';
  step.value = 'type';
  selectedTable.value = null;
  order.value = null;
  await loadTables();
});
watch(channel, async nextChannel => {
  if (!nextChannel) return;
  await loadCatalog();
  if (pendingSeatedOrder.value) {
    order.value = pendingSeatedOrder.value;
    selectedTable.value = tables.value.find(table => table.name === order.value?.table) || null;
    guestCount.value = order.value.guest_count || guestCount.value;
    pendingSeatedOrder.value = null;
  }
});
let tableRefreshTimer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  void load();
  tableRefreshTimer = setInterval(() => {
    if ((step.value === 'tables' || channel.value === 'Table') && !busy.value && !loading.value)
      void loadTables();
  }, 5000);
});
onUnmounted(() => { if (tableRefreshTimer) clearInterval(tableRefreshTimer); });
</script>

<template>
  <div class="register-shell" :class="{ 'register-shell-flow': step !== 'catalog' }" :dir="rtl ? 'rtl' : 'ltr'" :lang="language">
    <header class="register-identity">
      <button class="register-menu-button" type="button" :aria-label="text('Open register menu', 'فتح قائمة الصندوق')" :aria-expanded="showTools" @click="showTools = !showTools">☰</button>
      <div class="register-name"><strong>S&S</strong><small>{{ text('Seat & Serve · Waiter register', 'سيت آند سيرف · صندوق النادل') }}</small></div>
      <select v-model="outlet" :disabled="busy || loading || !!order?.lines.length" :aria-label="text('Outlet', 'الفرع')"><option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option></select>
      <Transition name="register-drop"><div v-if="showTools" class="register-tools">
        <a href="/kitchen">{{ text('Kitchen display', 'شاشة المطبخ') }}</a>
        <a href="/app">{{ text('Manager Desk', 'لوحة الإدارة') }}</a>
        <button v-if="selectedOutlet?.enable_tables" type="button" @click="openReservations">{{ text('Reservations', 'الحجوزات') }}</button>
        <a v-if="selectedOutlet?.enable_tables" :href="'/reservations?outlet=' + encodeURIComponent(outlet)" target="_blank" rel="noopener">{{ text('Guest reservation page', 'صفحة حجز الضيوف') }}</a>
        <a :href="options?.opening_entry ? '/app/pos-closing-entry' : '/app/pos-opening-entry'">{{ options?.opening_entry ? text('Close shift', 'إغلاق الوردية') : text('Open shift', 'فتح الوردية') }}</a>
        <button type="button" @click="language = rtl ? 'en' : 'ar'; showTools = false">{{ rtl ? 'English' : 'العربية' }}</button>
      </div></Transition>
    </header>

    <nav v-if="step === 'catalog'" class="register-categories" :aria-label="text('Menu categories', 'فئات القائمة')">
      <button type="button" :class="{ active: !category }" :aria-pressed="!category" @click="category = ''">{{ text('All items', 'كل الأصناف') }}</button>
      <button v-if="hasDeals" type="button" class="register-deals-tab" :class="{ active: category === DEALS_CATEGORY }" :aria-pressed="category === DEALS_CATEGORY" @click="category = DEALS_CATEGORY">{{ text('Combo deals / Offers', 'الوجبات والعروض') }}</button>
      <button v-for="name in categories" :key="name" type="button" :class="{ active: category === name }" :aria-pressed="category === name" :title="displayCategory(name)" @click="category = name">{{ displayCategory(name) }}</button>
      <button class="register-search-toggle" type="button" :aria-label="text('Search items', 'ابحث عن الأصناف')" :aria-expanded="showSearch" @click="showSearch = !showSearch; if (!showSearch) search = ''"><Icon name="search" /></button>
    </nav>

    <aside v-if="step === 'catalog'" id="current-order" class="register-order" :aria-label="text('Current order', 'الطلب الحالي')">
      <div class="register-order-status"><span class="register-led" />{{ order ? `${order.order_number || text('Order', 'طلب')} · ${order.status}` : text('Ready to order…', 'جاهز للطلب…') }}<span class="register-order-count">{{ itemCount }}</span></div>
      <div class="register-sale-context"><strong>{{ channelTitle ? text(channelTitle.en, channelTitle.ar) : '' }}</strong><button type="button" :disabled="busy || loading" @click="showTypes">{{ text('Change order type', 'تغيير نوع الطلب') }}</button></div>
      <div v-if="channel === 'Table'" class="register-table-context"><div class="register-table-context-head"><strong>{{ selectedTable?.title || text('No table selected', 'لم يتم اختيار طاولة') }}</strong><button type="button" :disabled="busy || loading" @click="step = 'tables'">{{ text('Change table', 'تغيير الطاولة') }}</button></div><span>{{ tableContextLabel }}</span><label><span>{{ text('People', 'الأشخاص') }}</span><input v-model.number="guestCount" type="number" min="1" :max="selectedTable?.seats || 99" :disabled="!!order?.lines.length" /></label><label v-if="selectedTableTickets.length" class="register-ticket-select"><span>{{ text('Open ticket', 'الطلب المفتوح') }}</span><select :value="order?.name || ''" :disabled="busy || loading" @change="chooseTicket"><option value="" disabled>{{ text('Select ticket', 'اختر طلباً') }}</option><option v-for="ticket in selectedTableTickets" :key="ticket.name" :value="ticket.name">{{ ticket.order_number }} · {{ ticket.status }} · {{ price(ticket.grand_total) }}</option></select></label></div>
      <label v-if="channel === 'Tab'" class="register-tab-name"><span>{{ text('Tab name', 'اسم الحساب') }}</span><input v-model="tabLabel" :disabled="!!order?.lines.length" :placeholder="text('Enter a name', 'أدخل اسماً')" /></label>
      <div class="register-lines">
        <Transition name="feedback"><Feedback v-if="busy" class="register-feedback" kind="busy" :message="text('Working on it…', 'جارٍ التنفيذ…')" :language="language" /><Feedback v-else-if="notice" class="register-feedback" :kind="noticeKind" :message="notice" :language="language" dismissible @dismiss="notice = ''" /></Transition>
        <p v-if="!order?.lines.length" class="register-empty-order">{{ text('Tap an item to start this order.', 'اضغط على صنف لبدء الطلب.') }}</p>
        <TransitionGroup name="order-line" tag="div" class="register-line-list"><div v-for="line in order?.lines || []" :key="line.name" class="register-line">
          <div><strong>{{ line.item_name }}</strong><small v-if="line.modifiers?.length" class="register-line-modifiers">{{ line.modifiers.map(option => rtl ? option.name_ar || option.name_en : option.name_en).join(', ') }}</small><small v-if="line.note" class="register-line-modifiers">{{ line.note }}</small><div class="register-qty"><button type="button" :disabled="busy || !editable" :aria-label="text('Decrease quantity of ', 'تقليل كمية ') + line.item_name" @click="changeQty(line, line.qty - 1)">−</button><span>{{ line.qty }}</span><button type="button" :disabled="busy || !editable" :aria-label="text('Increase quantity of ', 'زيادة كمية ') + line.item_name" @click="changeQty(line, line.qty + 1)">+</button></div></div>
          <strong>{{ price(line.amount) }}</strong>
        </div></TransitionGroup>
      </div>
      <div class="register-summary">
        <div class="register-summary-label"><span class="register-led" />{{ channel === 'Table' ? text('Table bill', 'حساب الطاولة') : text('Summary', 'الملخص') }}<span>{{ billItemCount }} {{ text('items', 'صنف') }}</span></div>
        <div v-if="channel === 'Table'" class="register-bill-context"><strong>{{ billTicketCount }} {{ billTicketCount === 1 ? text('ticket in this bill', 'طلب في هذا الحساب') : text('tickets in this bill', 'طلبات في هذا الحساب') }}</strong><span>{{ billOrderNumbers.join(' · ') }}</span></div>
        <div class="register-total"><span>{{ text('Total', 'الإجمالي') }}</span><strong>{{ price(billGrandTotal) }}</strong></div>
        <div class="register-breakdown"><span>{{ text('Subtotal', 'المجموع') }} {{ price(billNetTotal) }}</span><span>{{ text('Tax included', 'الضريبة مشمولة') }} {{ price(billTaxTotal) }}</span></div>
        <div v-if="order?.bill?.discount_amount || order?.bill?.loyalty?.amount" class="register-savings"><span v-if="order.bill.discount_amount">{{ order.bill.discount_label || text('Discount', 'الخصم') }} −{{ price(order.bill.discount_amount) }}</span><span v-if="order.bill.loyalty?.amount">{{ text('Loyalty points', 'نقاط الولاء') }} −{{ price(order.bill.loyalty.amount) }}</span><strong>{{ text('Amount due', 'المبلغ المستحق') }} {{ price(billAmountDue) }}</strong></div>
        <div class="register-actions"><button type="button" :disabled="busy || !order?.lines.length || order?.status !== 'Draft'" @click="send">{{ text('Send to kitchen', 'إرسال للمطبخ') }}</button><button type="button" :disabled="busy || !outlet || loading" @click="createOrder">{{ channel === 'Table' && selectedTableTickets.length ? text('Add items', 'إضافة أصناف') : text('New order', 'طلب جديد') }}</button><button type="button" :disabled="busy || !billItemCount || order?.status === 'Settled'" :aria-expanded="showPayment" @click="togglePayment">{{ text('Cash payment', 'الدفع النقدي') }}</button></div>
        <Transition name="register-panel"><div v-if="showPayment && billItemCount && order?.status !== 'Settled'" class="register-payment">
          <h2>{{ channel === 'Table' ? text('Pay table bill', 'دفع حساب الطاولة') : text('Cash payment', 'الدفع النقدي') }}</h2>
          <p v-if="channel === 'Table'" class="register-payment-summary">{{ text('This payment includes', 'يشمل هذا الدفع') }} {{ billOrderNumbers.join(', ') }} · {{ price(billGrandTotal) }}</p>
          <p v-for="error in order?.bill?.billing_errors || []" :key="error" class="register-payment-warning" role="alert">{{ error }}</p>
          <div class="register-benefits">
            <h3>{{ text('Customer & savings', 'العميل والخصومات') }}</h3>
            <p>{{ text('Combo prices apply automatically. Add one coupon or ask a manager for a manual discount.', 'أسعار الوجبات المجمعة تُطبق تلقائياً. أضف قسيمة واحدة أو اطلب خصماً يدوياً من المدير.') }}</p>
            <label>{{ text('Find customer for loyalty', 'ابحث عن عميل للولاء') }}<input v-model="customerQuery" type="search" :placeholder="text('Name or mobile number', 'الاسم أو رقم الهاتف')" @input="searchCustomers" /></label>
            <div v-if="customerMatches.length" class="register-customer-results"><button v-for="customer in customerMatches" :key="customer.name" type="button" @click="billCustomer = customer.name; selectedCustomerName = customer.customer_name; customerQuery = ''; customerMatches = []">{{ customer.customer_name }}<small>{{ customer.mobile_no || customer.name }}</small></button></div>
            <p v-if="billCustomer">{{ text('Selected customer:', 'العميل المختار:') }} {{ selectedCustomerName }} <button type="button" class="register-inline-button" @click="billCustomer = ''; selectedCustomerName = ''; customerQuery = ''; loyaltyPoints = 0">{{ text('Use walk-in', 'عميل عابر') }}</button></p>
            <label>{{ text('Coupon code', 'رمز القسيمة') }}<input v-model="couponInput" type="text" maxlength="32" autocomplete="off" :disabled="!!manualType" :placeholder="text('Enter code', 'أدخل الرمز')" /></label>
            <div v-if="canManageDiscount" class="register-manual-discount"><label>{{ text('Manager discount', 'خصم المدير') }}<select v-model="manualType" :disabled="!!couponInput.trim()"><option value="">{{ text('None', 'لا يوجد') }}</option><option value="Percentage">{{ text('Percentage', 'نسبة مئوية') }}</option><option value="Amount">{{ text('Fixed amount', 'مبلغ ثابت') }}</option></select></label><label v-if="manualType">{{ text('Value', 'القيمة') }}<input v-model.number="manualValue" type="number" min="0" step="any" /></label><label v-if="manualType">{{ text('Reason', 'السبب') }}<input v-model="manualReason" type="text" maxlength="140" /></label></div>
            <label v-if="order?.bill?.loyalty?.program || billCustomer">{{ text('Redeem loyalty points', 'استبدال نقاط الولاء') }}<input v-model.number="loyaltyPoints" type="number" min="0" step="1" /></label>
            <p v-if="order?.bill?.loyalty?.program">{{ text('Available', 'المتاح') }}: {{ order.bill.loyalty.available_points }} {{ text('points', 'نقطة') }} · {{ text('Program', 'البرنامج') }}: {{ order.bill.loyalty.program }}</p>
            <button type="button" class="register-apply-benefits" :disabled="busy || !billSettingsDirty" @click="applyBillSettings">{{ text('Apply to bill', 'تطبيق على الحساب') }}</button>
            <p v-if="billSettingsDirty" class="register-payment-warning">{{ text('Apply changes before confirming payment.', 'طبّق التغييرات قبل تأكيد الدفع.') }}</p>
            <strong class="register-amount-due">{{ text('Amount due', 'المبلغ المستحق') }} · {{ price(billAmountDue) }}</strong>
          </div>
          <p v-if="!options?.opening_entry" class="register-payment-warning">{{ text('Open today’s POS shift before checkout.', 'افتح وردية اليوم قبل الدفع.') }} <a href="/app/pos-opening-entry">{{ text('Open shift', 'فتح الوردية') }}</a></p>
          <p v-if="options && !options.pos_invoice_mode" class="register-payment-warning">{{ text('Set POS Settings to POS Invoice mode.', 'اضبط وضع فاتورة نقطة البيع.') }}</p>
          <div v-for="(tender, index) in tenders" :key="index" class="register-tender"><select v-model="tender.mode_of_payment" :aria-label="text('Payment method', 'وسيلة الدفع')"><option v-for="mode in options?.cash_modes || []" :key="mode">{{ mode }}</option></select><select v-model="tender.currency" :aria-label="text('Currency', 'العملة')"><option>{{ order?.currency || 'USD' }}</option><option v-if="order?.currency !== 'LBP'">LBP</option><option v-else>USD</option></select><input v-model.number="tender.amount" type="number" min="0" step="any" :aria-label="text('Tender amount', 'قيمة الدفع')" /><button type="button" :aria-label="text('Remove payment', 'إزالة الدفعة')" @click="tenders.splice(index, 1)">×</button></div>
          <button class="register-add-tender" type="button" @click="addTender">+ {{ text('Add payment amount', 'إضافة مبلغ دفع') }}</button><p v-if="options?.fx_rate">1 USD = {{ options.fx_rate.lbp_per_usd }} LBP</p><button class="register-confirm-payment" type="button" :disabled="busy || !options?.opening_entry || !options?.pos_invoice_mode || !options?.cash_modes.length" @click="checkout">{{ text('Confirm cash payment', 'تأكيد الدفع النقدي') }}</button>
        </div></Transition>
        <p v-if="order?.pos_invoice" class="register-invoice">{{ text('Paid', 'تم الدفع') }} · {{ order.pos_invoice }}</p>
      </div>
    </aside>

    <main class="register-catalog" :class="{ 'register-flow-main': step !== 'catalog' }" :aria-busy="loading">
      <section v-if="step === 'type'" class="register-flow" :aria-label="text('Choose order type', 'اختر نوع الطلب')">
        <p class="register-flow-eyebrow">{{ text('REGISTER · STEP 1 OF 2', 'الصندوق · الخطوة ١ من ٢') }}</p>
        <h1>{{ text('What kind of order?', 'ما نوع الطلب؟') }}</h1>
        <p class="register-flow-copy">{{ text('Choose how this guest will be served.', 'اختر طريقة تقديم الطلب لهذا الضيف.') }}</p>
        <Transition name="feedback"><Feedback v-if="notice" class="register-flow-feedback" :kind="noticeKind" :message="notice" :language="language" dismissible @dismiss="notice = ''" /></Transition>
        <div class="register-type-grid"><button v-for="sale in availableSaleTypes" :key="sale.value" type="button" class="register-type-card" :disabled="loading || busy" @click="chooseType(sale.value)"><span class="register-type-icon"><Icon :name="sale.icon" /></span><strong>{{ text(sale.en, sale.ar) }}</strong><small>{{ text(sale.detail, sale.detailAr) }}</small><Icon name="arrow" /></button></div>
        <button v-if="selectedOutlet?.enable_tables" class="register-reservation-entry" type="button" :disabled="loading || busy" @click="openReservations">{{ text('Reservations · Book or seat a guest', 'الحجوزات · احجز أو أجلس ضيفاً') }} →</button>
      </section>
      <section v-else-if="step === 'tables'" class="register-flow register-table-flow" :aria-label="text('Choose a table', 'اختر طاولة')">
        <button class="register-flow-back" type="button" :disabled="loading || busy" @click="showTypes">← {{ text('Order types', 'أنواع الطلبات') }}</button>
        <div class="register-flow-heading"><div><p class="register-flow-eyebrow">{{ text('DINE IN · STEP 2 OF 2', 'داخل المطعم · الخطوة ٢ من ٢') }}</p><h1>{{ text('Choose a table', 'اختر طاولة') }}</h1><p class="register-flow-copy">{{ text('Occupied tables reopen their saved orders. Available tables start a new one.', 'الطاولات المشغولة تفتح طلباتها المحفوظة. الطاولات المتاحة تبدأ طلباً جديداً.') }}</p></div><div class="register-map-controls"><span>{{ tables.filter(table => table.orders.length).length }}/{{ tables.length }} {{ text('occupied', 'مشغولة') }}</span><button type="button" :disabled="busy || loading" @click="loadTables">{{ text('Refresh', 'تحديث') }}</button></div></div>
        <Transition name="feedback"><Feedback v-if="notice" class="register-flow-feedback" :kind="noticeKind" :message="notice" :language="language" dismissible @dismiss="notice = ''" /></Transition>
        <Feedback v-if="loading" class="register-flow-feedback" kind="busy" :message="text('Loading tables…', 'جارٍ تحميل الطاولات…')" :language="language" />
        <Feedback v-else-if="!tables.length" class="register-flow-feedback" kind="info" :message="text('No tables are configured for this outlet.', 'لم تُضف طاولات لهذا الفرع.')" :language="language" />
          <section v-for="area in tableAreas" :key="area.title" class="register-area"><h2>{{ area.title }}</h2><TransitionGroup name="table-card" tag="div" class="register-table-grid"><button v-for="table in area.tables" :key="table.name" type="button" class="register-table-card" :class="{ selected: selectedTable?.name === table.name, occupied: table.orders.length, 'runner-needed': runnerNeeded(table), reserved: !!table.next_reservation }" :disabled="busy || loading" @click="selectTable(table)"><span class="register-table-number">{{ table.title }}</span><span class="register-table-capacity">{{ table.guest_count || 0 }}/{{ table.seats || '—' }} {{ text('people', 'أشخاص') }}</span><span v-if="table.orders.length" class="register-table-orders">{{ text('Resume', 'استئناف') }} {{ (table.orders.find(ticket => ticket.line_count) || table.orders[0]).order_number }} · {{ table.orders.length }} {{ table.orders.length === 1 ? text('ticket', 'طلب') : text('tickets', 'طلبات') }}</span><span v-else class="register-table-orders available">{{ text('Available · Start order', 'متاحة · ابدأ طلباً') }}</span><span v-if="table.next_reservation" class="register-table-reservation">{{ text('Reserved', 'محجوزة') }} {{ table.next_reservation.time }} · {{ table.next_reservation.guest_name }}</span><span v-if="runnerNeeded(table)" class="register-table-runner">{{ text('Runner needed · Food ready', 'مطلوب نادل · الطعام جاهز') }}</span></button></TransitionGroup></section>
      </section>
      <section v-else-if="step === 'reservations'" class="register-flow register-reservations" :aria-label="text('Reservations', 'الحجوزات')">
        <button class="register-flow-back" type="button" :disabled="busy" @click="showTypes">← {{ text('Order types', 'أنواع الطلبات') }}</button>
        <div class="register-flow-heading"><div><p class="register-flow-eyebrow">{{ text('TABLE SERVICE', 'خدمة الطاولات') }}</p><h1>{{ text('Reservations', 'الحجوزات') }}</h1><p class="register-flow-copy">{{ text('Book a table, review arrivals, and seat guests into a new ticket.', 'احجز طاولة وراجع القادمين وأجلس الضيوف في طلب جديد.') }}</p></div><a class="register-reservation-link" :href="'/reservations?outlet=' + encodeURIComponent(outlet)" target="_blank" rel="noopener">{{ text('Open guest booking page ↗', 'افتح صفحة حجز الضيوف ↗') }}</a></div>
        <Transition name="feedback"><Feedback v-if="notice" class="register-flow-feedback" :kind="noticeKind" :message="notice" :language="language" dismissible @dismiss="notice = ''" /></Transition>
        <div class="register-reservation-layout">
          <form class="register-reservation-form" @submit.prevent="bookAtRegister">
            <h2>{{ text('New reservation', 'حجز جديد') }}</h2>
            <div class="register-reservation-fields"><label>{{ text('Date', 'التاريخ') }}<input v-model="reservationDate" type="date" :min="localDate()" required @change="refreshReservations" /></label><label>{{ text('Guests', 'الضيوف') }}<input v-model.number="reservationParty" type="number" min="1" max="30" required @change="refreshReservationSlots" /></label><label>{{ text('Table', 'الطاولة') }}<select v-model="reservationTable" @change="refreshReservationSlots"><option value="">{{ text('Assign automatically', 'تعيين تلقائي') }}</option><option v-for="table in tables.filter(row => row.seats >= reservationParty)" :key="table.name" :value="table.name">{{ table.title }} · {{ table.seats }} {{ text('seats', 'مقاعد') }}</option></select></label></div>
            <strong>{{ text('Available times', 'الأوقات المتاحة') }}</strong><div class="register-reservation-slots"><button v-for="slot in reservationSlots" :key="slot" type="button" :class="{ active: reservationTime === slot }" :aria-pressed="reservationTime === slot" @click="reservationTime = slot">{{ slot }}</button><span v-if="!reservationSlots.length">{{ text('No open times. Choose another date or table.', 'لا توجد أوقات متاحة. اختر تاريخاً أو طاولة أخرى.') }}</span></div>
            <div class="register-reservation-fields"><label>{{ text('Guest name', 'اسم الضيف') }}<input v-model="reservationGuest" type="text" maxlength="100" required /></label><label>{{ text('Phone', 'الهاتف') }}<input v-model="reservationPhone" type="tel" maxlength="25" /></label><label>{{ text('Email', 'البريد الإلكتروني') }}<input v-model="reservationEmail" type="email" maxlength="140" /></label></div>
            <label>{{ text('Special requests', 'طلبات خاصة') }}<textarea v-model="reservationNotes" maxlength="500" rows="2" /></label>
            <button class="register-reservation-primary" type="submit" :disabled="busy || !reservationTime || !reservationGuest.trim() || (!reservationPhone.trim() && !reservationEmail.trim())">{{ text('Confirm reservation', 'تأكيد الحجز') }}</button>
          </form>
        <div class="register-reservation-list"><div class="register-reservation-list-head"><h2>{{ text('Bookings for', 'حجوزات') }} {{ reservationDate }}</h2><button type="button" :disabled="reservationLoading || busy" @click="refreshReservations">{{ text('Refresh', 'تحديث') }}</button></div><p v-if="reservationLoading">{{ text('Loading reservations…', 'جارٍ تحميل الحجوزات…') }}</p><p v-else-if="!reservationRows.length">{{ text('No reservations on this date.', 'لا توجد حجوزات في هذا التاريخ.') }}</p><article v-for="row in reservationRows" :key="row.name" class="register-reservation-row"><div><strong>{{ row.time }} · {{ row.guest_name }}</strong><span>{{ row.reservation_number }} · {{ row.table_title }} · {{ row.party_size }} {{ text('guests', 'ضيوف') }}</span><small>{{ row.phone || row.email }}<template v-if="row.special_requests"> · {{ row.special_requests }}</template></small></div><b :class="'status-' + row.status.toLowerCase().replace(' ', '-')">{{ row.status }}</b><div class="register-reservation-actions"><button v-if="row.status === 'Confirmed'" type="button" :disabled="busy" @click="seatReservation(row)">{{ text('Seat', 'إجلاس') }}</button><button v-if="row.status === 'Confirmed'" type="button" :disabled="busy" @click="changeReservation(row, 'No Show')">{{ text('No show', 'لم يحضر') }}</button><button v-if="row.status === 'Confirmed'" type="button" :disabled="busy" @click="changeReservation(row, 'Cancelled')">{{ text('Cancel', 'إلغاء') }}</button><span v-if="row.order_number">{{ text('Order', 'طلب') }} {{ row.order_number }}</span></div></article></div>
        </div>
      </section>
      <template v-else>
      <Transition name="register-panel"><label v-if="showSearch" class="register-search"><Icon name="search" /><input v-model="search" type="search" :placeholder="text('Search items…', 'ابحث عن الأصناف…')" :aria-label="text('Search items', 'ابحث عن الأصناف')" /></label></Transition>
      <div v-if="loading" class="register-catalog-empty">{{ text('Loading menu…', 'جارٍ تحميل القائمة…') }}</div>
      <div v-else-if="!visibleItems.length" class="register-catalog-empty"><Icon :name="catalog.length ? 'search' : 'kitchen'" /><h1>{{ catalog.length ? text('No matching items', 'لا توجد أصناف مطابقة') : text('No menu items yet', 'لا توجد أصناف بعد') }}</h1><p>{{ catalog.length ? text('Try another category or search.', 'جرّب فئة أو بحثاً آخر.') : text('Add items to this outlet’s menu to start taking orders.', 'أضف أصنافاً إلى قائمة هذا الفرع لبدء استقبال الطلبات.') }}</p><button v-if="catalog.length" type="button" @click="category = ''; search = ''">{{ text('Show all items', 'عرض كل الأصناف') }}</button><a v-else href="/app/trt-menu">{{ text('Manage menu', 'إدارة القائمة') }}</a></div>
      <section v-for="group in itemGroups" v-else :key="group.name" class="register-group"><h2>{{ displayCategory(group.name) }}</h2><TransitionGroup name="register-item" tag="div" class="register-item-grid" :class="{ 'register-deal-grid': !!group.items[0]?.deal_kind }"><button v-for="item in group.items" :key="item.item" type="button" class="register-item" :class="[item.deal_kind ? 'register-deal-item' : 'tone-' + group.tone]" :disabled="busy || !editable" :title="`${rtl ? item.name_ar || item.name_en : item.name_en} · ${price(item.rate)}`" @click="choose(item)"><em v-if="item.deal_kind">{{ item.deal_kind === 'Combo' ? text('COMBO', 'وجبة') : text('OFFER', 'عرض') }}</em><span>{{ rtl ? item.name_ar || item.name_en : item.name_en }}</span><small v-if="item.deal_description" class="register-deal-description">{{ item.deal_description }}</small><small>{{ price(item.rate) }}</small></button></TransitionGroup></section>
      </template>
    </main>
    <Transition name="modifier"><ModifierPicker v-if="selectedItem" :item="selectedItem" :currency="selectedOutlet?.base_currency || 'USD'" :language="language" :busy="busy" variant="register" @confirm="addSelected" @cancel="selectedItem = null" /></Transition>
  </div>
</template>
