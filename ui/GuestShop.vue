<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { eventId, get, post, type CatalogItem, type Order, type Outlet } from './client';
import './styles.css';

const props = defineProps<{ mode: 'Kiosk' | 'Menu' }>();
const query = new URLSearchParams(location.search);
const channel = props.mode === 'Kiosk' ? 'Kiosk' : query.has('table') ? 'QR' : 'Pickup';
const language = ref<'en' | 'ar'>(query.get('lang') === 'ar' ? 'ar' : 'en');
const rtl = computed(() => language.value === 'ar');
const label = (en: string, ar: string) => rtl.value ? ar : en;
const outlets = ref<Outlet[]>([]);
const outlet = ref(query.get('outlet') || '');
const items = ref<CatalogItem[]>([]);
const order = ref<Order | null>(null);
const token = ref('');
const busy = ref(false);
const notice = ref('');
const selectedOutlet = computed(() => outlets.value.find(row => row.name === outlet.value));

async function loadOutlets() {
  try {
    outlets.value = await get<Outlet[]>('public_outlets', { channel });
    if (!outlet.value) outlet.value = outlets.value[0]?.name || '';
    if (!outlets.value.some(row => row.name === outlet.value)) {
      outlet.value = '';
      notice.value = label('This outlet is unavailable.', 'هذا الفرع غير متاح.');
    }
  } catch (error) { notice.value = String(error); }
}

async function loadCatalog() {
  if (!outlet.value) return;
  order.value = null;
  token.value = '';
  try {
    const catalog = await get<{ items: CatalogItem[] }>('catalog', { outlet: outlet.value, channel });
    items.value = catalog.items;
  } catch (error) { notice.value = String(error); }
}

async function ensureOrder() {
  if (order.value) return;
  const link = await post<{ token: string }>('guest_link', {
    outlet: outlet.value, channel,
    ...(channel === 'QR' ? { table: query.get('table'), qr_secret: query.get('key') } : {}),
  });
  token.value = link.token;
  order.value = await post<Order>('order_command', {
    command: { action: 'create', outlet: outlet.value, channel,
      ...(channel === 'QR' ? { table: query.get('table') } : {}) },
    event_id: eventId(), expected_revision: 0, guest_token: token.value,
  });
}

async function add(item: CatalogItem) {
  busy.value = true; notice.value = '';
  try {
    await ensureOrder();
    if (!order.value) return;
    order.value = await post<Order>('order_command', {
      command: { action: 'add_line', item: item.item, qty: 1 },
      event_id: eventId(), order_name: order.value.name,
      expected_revision: order.value.revision, guest_token: token.value,
    });
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

async function changeQty(line: Order['lines'][number], qty: number) {
  if (!order.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'set_qty', line: line.name, qty },
      event_id: eventId(), order_name: order.value.name,
      expected_revision: order.value.revision, guest_token: token.value,
    });
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

async function demoCheckout() {
  if (!order.value) return;
  busy.value = true; notice.value = '';
  try {
    const payment = await post<{ attempt: string; provider: string }>('payment_intent', {
      order_name: order.value.name, idempotency_key: eventId(),
      expected_revision: order.value.revision, guest_token: token.value,
    });
    if (payment.provider !== 'Sandbox') throw new Error('Provider checkout is not available yet.');
    await post('sandbox_capture', { attempt_name: payment.attempt,
      expected_revision: order.value.revision, guest_token: token.value });
    notice.value = label('Demo order sent. No money was charged.', 'أُرسل الطلب التجريبي. لم تُحصّل أي أموال.');
    order.value = null;
    token.value = '';
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

watch(outlet, loadCatalog);
onMounted(loadOutlets);
</script>

<template>
  <div class="shell" :dir="rtl ? 'rtl' : 'ltr'">
    <header class="topbar">
      <h1>{{ props.mode === 'Kiosk' ? label('Self-service kiosk', 'جهاز الطلب الذاتي') : label('Menu & ordering', 'القائمة والطلب') }}</h1>
      <select v-if="channel !== 'QR'" v-model="outlet" :aria-label="label('Outlet', 'الفرع')">
        <option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option>
      </select>
      <span v-else>{{ selectedOutlet?.title }}</span>
      <span class="spacer" />
      <button @click="language = rtl ? 'en' : 'ar'">{{ rtl ? 'English' : 'العربية' }}</button>
    </header>
    <main class="content">
      <section class="panel">
        <h2>{{ channel === 'QR' ? label('Table menu', 'قائمة الطاولة') : label('Choose items', 'اختر الأصناف') }}</h2>
        <p v-if="!items.length" class="muted">{{ label('No items are available for this outlet.', 'لا توجد أصناف متاحة لهذا الفرع.') }}</p>
        <div class="grid">
          <button v-for="item in items" :key="item.item" class="item" :disabled="busy" @click="add(item)">
            <strong>{{ rtl ? item.name_ar || item.name_en : item.name_en }}</strong>
            <small>{{ item.category }}</small>
            <b>{{ item.rate }} {{ selectedOutlet?.base_currency }}</b>
          </button>
        </div>
      </section>
      <aside class="panel stack">
        <h2>{{ label('Your order', 'طلبك') }}</h2>
        <div v-if="notice" class="status" role="status">{{ notice }}</div>
        <p v-if="!order?.lines.length" class="muted">{{ label('Tap an item to start.', 'اضغط على صنف للبدء.') }}</p>
        <div v-for="line in order?.lines || []" :key="line.name" class="line">
          <div><strong>{{ line.item_name }}</strong><div class="row">
            <button class="ghost" :disabled="busy" @click="changeQty(line, line.qty - 1)">−</button>
            <span>{{ line.qty }}</span>
            <button class="ghost" :disabled="busy" @click="changeQty(line, line.qty + 1)">+</button>
          </div></div>
          <strong>{{ line.amount }}</strong>
        </div>
        <div v-if="order" class="totals">
          <div><span>{{ label('Subtotal', 'المجموع') }}</span><span>{{ order.net_total }} {{ order.currency }}</span></div>
          <div><span>{{ label('Tax', 'الضريبة') }}</span><span>{{ order.tax_total }} {{ order.currency }}</span></div>
          <div><strong>{{ label('Total', 'الإجمالي') }}</strong><strong>{{ order.grand_total }} {{ order.currency }}</strong></div>
        </div>
        <button class="primary" :disabled="busy || !order?.lines.length" @click="demoCheckout">
          {{ label('Place demo order', 'إرسال طلب تجريبي') }}
        </button>
        <p class="muted">{{ label('Demo checkout is available only on a developer site with sandbox payments enabled. No live payment is collected.', 'الدفع التجريبي متاح فقط على موقع تطوير مفعّل له الدفع التجريبي. لا تُحصّل أي دفعة حقيقية.') }}</p>
      </aside>
    </main>
  </div>
</template>
