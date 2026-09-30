<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { eventId, get, post, type Outlet } from '../../ui/client';
import '../../ui/styles.css';
import '../../ui/theme.css';
import './kds.css';
import Icon from '../../ui/Icon.vue';
import Feedback from '../../ui/Feedback.vue';
import { groupOrders, type OrderCard, type OrderType, type Ticket } from './orderCards';

const query = new URLSearchParams(location.search);
const outlets = ref<Outlet[]>([]);
const outlet = ref(query.get('outlet') || '');
const tickets = ref<Ticket[]>([]);
const message = ref('');
const successMessage = ref('');
const language = ref<'en' | 'ar'>(query.get('lang') === 'ar' ? 'ar' : 'en');
const rtl = computed(() => language.value === 'ar');
const text = (en: string, ar: string) => rtl.value ? ar : en;
const lastUpdated = ref('');
const now = ref(Date.now());
const busyOrder = ref('');
let refreshTimer: ReturnType<typeof setInterval> | undefined;
let clockTimer: ReturnType<typeof setInterval> | undefined;
let successTimer: ReturnType<typeof setTimeout> | undefined;
function showSuccess(textValue: string) {
  if (successTimer) clearTimeout(successTimer);
  successMessage.value = textValue;
  successTimer = setTimeout(() => { successMessage.value = ''; }, 2200);
}

const orderTypeLabel = (type: OrderType) => ({
  'dine-in': text('Dine in', 'داخل المطعم'),
  'to-go': text('To go', 'للخارج'),
  kiosk: text('Kiosk', 'كشك'),
  counter: text('Counter', 'الصندوق'),
  other: text('Other', 'أخرى'),
})[type];
const orders = computed(() => groupOrders(tickets.value));
const types = computed(() => (['dine-in', 'to-go', 'kiosk', 'counter', 'other'] as OrderType[])
  .map(type => ({ type, count: orders.value.filter(card => card.type === type).length }))
  .filter(row => row.type !== 'other' || row.count > 0));
const outletTitle = computed(() => outlets.value.find(row => row.name === outlet.value)?.title || text('Kitchen', 'المطبخ'));
const totalItems = (card: OrderCard) => card.tickets.reduce(
  (sum, ticket) => sum + ticket.lines.reduce((lineSum, line) => lineSum + line.qty, 0), 0);
const cardLines = (card: OrderCard) => card.tickets.flatMap(ticket => ticket.lines);
const hasQueued = (card: OrderCard) => cardLines(card).some(line => line.status === 'Queued');
const hasUnready = (card: OrderCard) => cardLines(card).some(line => ['Queued', 'Preparing'].includes(line.status));
const allReady = (card: OrderCard) => cardLines(card).length > 0 &&
  cardLines(card).every(line => ['Ready', 'Served'].includes(line.status));
const orderStatus = (card: OrderCard) => {
  const statuses = card.tickets.map(ticket => ticket.status);
  if (statuses.every(status => ['Ready', 'Served'].includes(status))) return text('Ready to serve', 'جاهز للتقديم');
  if (statuses.some(status => status === 'Preparing')) return text('Preparing', 'قيد التحضير');
  return text('New order', 'طلب جديد');
};
const ticketTime = (value: string) => {
  const date = new Date(value.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(
    rtl.value ? 'ar-LB' : 'en-US', { hour: '2-digit', minute: '2-digit' });
};
const elapsed = (card: OrderCard) => {
  const sent = new Date(card.sentAt.replace(' ', 'T')).getTime();
  const seconds = Number.isNaN(sent) ? 0 : Math.max(0, Math.floor((now.value - sent) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
};

async function refresh(clearMessage = true) {
  if (!outlet.value || busyOrder.value) return;
  try {
    tickets.value = await get<Ticket[]>('kitchen_tickets', { outlet: outlet.value, status: 'All' });
    lastUpdated.value = new Date().toLocaleTimeString(
      rtl.value ? 'ar-LB' : 'en-US', { hour: '2-digit', minute: '2-digit' });
    if (clearMessage) message.value = '';
  } catch (error) { message.value = String(error); }
}
async function changeLine(card: OrderCard, ticket: Ticket, lineName: string, event: Event) {
  const status = (event.target as HTMLSelectElement).value;
  if (busyOrder.value) return;
  busyOrder.value = card.order;
  try {
    await post('set_kitchen_line_status', {
      ticket_name: ticket.name, line_name: lineName, status,
      expected_revision: ticket.revision, event_id: eventId(),
    });
    busyOrder.value = '';
    await refresh();
    showSuccess(text('Item status updated.', 'تم تحديث حالة الصنف.'));
  } catch (error) {
    busyOrder.value = '';
    await refresh(false);
    message.value = String(error);
  }
}
async function orderAction(card: OrderCard, action: 'start' | 'ready' | 'dispatch_runner' | 'served') {
  if (busyOrder.value) return;
  busyOrder.value = card.order;
  try {
    await post('kitchen_order_action', { order_name: card.order, action, event_id: eventId() });
    busyOrder.value = '';
    await refresh();
    showSuccess(({ start: text('Order started.', 'بدأ تحضير الطلب.'), ready: text('Order ready.', 'الطلب جاهز.'), dispatch_runner: text('Runner called.', 'تم استدعاء النادل.'), served: text('Order served.', 'تم تقديم الطلب.') })[action]);
  } catch (error) {
    busyOrder.value = '';
    await refresh(false);
    message.value = String(error);
  }
}
async function load() {
  try {
    const data = await get<{ outlets: Outlet[] }>('bootstrap');
    outlets.value = data.outlets;
    if (!outlets.value.some(row => row.name === outlet.value)) outlet.value = outlets.value[0]?.name || '';
    await refresh();
  } catch (error) { message.value = String(error); }
  refreshTimer = setInterval(() => { void refresh(); }, 5000);
  clockTimer = setInterval(() => { now.value = Date.now(); }, 1000);
}
onMounted(load);
onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer);
  if (clockTimer) clearInterval(clockTimer);
  if (successTimer) clearTimeout(successTimer);
});
</script>

<template>
  <div class="shell kitchen-shell kds-shell" :dir="rtl ? 'rtl' : 'ltr'" :lang="language">
    <main class="kds-screen">
      <div class="kds-intro">
        <div class="kds-title"><span class="kds-title-mark"><Icon name="kitchen" /></span><h1>{{ text('Orders', 'طلبات') }}</h1></div>
        <div class="kds-intro-actions"><button class="kds-refresh" type="button" :disabled="!!busyOrder" @click="refresh()">{{ text('Refresh', 'تحديث') }}</button><div class="kds-live" :class="{ offline: !!message }"><span class="kds-live-dot" />{{ outletTitle }} <span class="kds-live-separator">·</span> {{ message ? text('Connection issue', 'مشكلة اتصال') : text('Live', 'مباشر') }}</div></div>
      </div>
      <div class="kds-summary"><div class="kds-total"><strong>{{ orders.length }}</strong><span>{{ text('active orders', 'طلبات نشطة') }}</span></div><div v-for="row in types" :key="row.type" class="kds-type-count" :class="row.type"><span class="kds-type-dot" /><strong>{{ row.count }}</strong><span>{{ orderTypeLabel(row.type) }}</span></div><small>{{ lastUpdated ? text('Updated', 'آخر تحديث') + ' ' + lastUpdated : text('Waiting for orders', 'بانتظار الطلبات') }}</small></div>
      <Transition name="feedback"><Feedback v-if="message" class="kds-feedback" kind="error" :message="message" :language="language" /></Transition>
      <Transition name="feedback"><Feedback v-if="successMessage" class="kds-feedback" kind="success" :message="successMessage" :language="language" dismissible @dismiss="successMessage = ''" /></Transition>
      <Transition name="kds-board" mode="out-in">
        <section v-if="!orders.length" key="empty" class="kds-empty" aria-live="polite"><span class="kds-empty-icon"><Icon name="kitchen" /></span><h2>{{ text('Kitchen is all clear', 'المطبخ جاهز') }}</h2><p>{{ text('New orders appear here automatically.', 'ستظهر الطلبات الجديدة هنا تلقائياً.') }}</p></section>
        <TransitionGroup v-else key="orders" name="kds-card" tag="section" class="kds-grid" appear :aria-label="text('Active kitchen orders', 'طلبات المطبخ النشطة')">
        <article v-for="card in orders" :key="card.order" class="kds-card" :class="[card.type, { 'is-busy': busyOrder === card.order }]" :aria-busy="busyOrder === card.order">
          <span v-if="busyOrder === card.order" class="kds-working" role="status"><i />{{ text('Updating order…', 'جارٍ تحديث الطلب…') }}</span>
          <div class="kds-card-head"><div class="kds-card-primary"><strong class="kds-order-number">{{ card.orderNumber || text('Order', 'طلب') }}</strong><span class="kds-order-type">{{ orderTypeLabel(card.type) }}</span></div><p><span>{{ ticketTime(card.sentAt) }}</span><span class="kds-separator">·</span><span>{{ card.tableTitle || card.tabLabel || card.channel || text('Order', 'طلب') }}</span><span v-if="card.parentOrderNumber" class="kds-add-on">{{ text('Add-on to', 'إضافة إلى') }} {{ card.parentOrderNumber }}</span></p></div>
          <div class="kds-card-meta"><span class="kds-order-status">{{ orderStatus(card) }}<span v-if="card.runnerDispatchedAt" class="kds-runner-badge"> · {{ text('Runner called', 'تم استدعاء النادل') }}</span></span><span class="kds-age"><Icon name="clock" />{{ elapsed(card) }}</span></div>
          <div class="kds-card-lines"><section v-for="ticket in card.tickets" :key="ticket.name" class="kds-station-group"><h2>{{ ticket.station_title || text('Kitchen', 'المطبخ') }}</h2><div v-for="line in ticket.lines" :key="line.name" class="kds-line" :class="'status-' + line.status.toLowerCase()"><span class="kds-qty">{{ line.qty }}×</span><div class="kds-line-content"><strong>{{ line.item_name || text('Item', 'صنف') }}</strong><p v-if="line.note" class="kds-note">{{ line.note }}</p></div><select class="kds-line-status" :value="line.status" :disabled="!!busyOrder" :aria-label="text('Status for ', 'حالة ') + (line.item_name || line.item)" @change="changeLine(card, ticket, line.name, $event)"><option value="Queued">{{ text('Queued', 'جديد') }}</option><option value="Preparing">{{ text('Preparing', 'قيد التحضير') }}</option><option value="Ready">{{ text('Ready', 'جاهز') }}</option><option value="Served">{{ text('Served', 'تم التقديم') }}</option></select></div></section></div>
          <div class="kds-card-foot"><span>{{ totalItems(card) }} {{ text('items', 'أصناف') }}</span><span>{{ card.tickets.length }} {{ card.tickets.length === 1 ? text('station', 'محطة') : text('stations', 'محطات') }}</span></div>
          <div class="kds-card-actions"><button v-if="hasQueued(card)" type="button" :disabled="!!busyOrder" @click="orderAction(card, 'start')">{{ text('Start all', 'بدء الكل') }}</button><button v-if="hasUnready(card)" type="button" :disabled="!!busyOrder" @click="orderAction(card, 'ready')">{{ text('Ready all', 'تجهيز الكل') }}</button><button v-if="allReady(card) && !card.runnerDispatchedAt" class="runner" type="button" :disabled="!!busyOrder" @click="orderAction(card, 'dispatch_runner')">{{ text('Dispatch runner', 'استدعاء النادل') }}</button><button v-if="allReady(card)" class="served" type="button" :disabled="!!busyOrder" @click="orderAction(card, 'served')">{{ text('Mark served', 'تم التقديم') }}</button></div>
        </article>
        </TransitionGroup>
      </Transition>
    </main>
  </div>
</template>
