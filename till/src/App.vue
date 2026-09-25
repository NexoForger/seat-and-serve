<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { eventId, get, post, type CatalogItem, type Order, type Outlet } from '../../ui/client';
import '../../ui/styles.css';

const outlets = ref<Outlet[]>([]);
const outlet = ref('');
const channel = ref('Till');
const catalog = ref<CatalogItem[]>([]);
const order = ref<Order | null>(null);
const search = ref('');
const tabLabel = ref('');
const notice = ref('');
const busy = ref(false);
const options = ref<{ cash_modes: string[]; base_currency: string; fx_rate?: { lbp_per_usd: number };
  opening_entry?: string; pos_invoice_mode: boolean } | null>(null);
const tenders = ref<{ mode_of_payment: string; currency: string; amount: number }[]>([]);
const language = ref<'en' | 'ar'>('en');
const rtl = computed(() => language.value === 'ar');
const text = (en: string, ar: string) => rtl.value ? ar : en;
const visibleItems = computed(() => catalog.value.filter(item =>
  [item.item, item.name_en, item.name_ar || ''].some(value =>
    value.toLowerCase().includes(search.value.toLowerCase()))));

async function load() {
  try {
    const data = await get<{ outlets: Outlet[] }>('bootstrap');
    outlets.value = data.outlets;
    outlet.value ||= data.outlets[0]?.name || '';
    if (!outlet.value) notice.value = text('Configure an outlet in Frappe Desk to begin.', 'أضف فرعاً في فرابي للبدء.');
  } catch (error) { notice.value = String(error); }
}

async function loadCatalog() {
  if (!outlet.value) return;
  order.value = null;
  tenders.value = [];
  try {
    const data = await get<{ items: CatalogItem[] }>('catalog', { outlet: outlet.value, channel: channel.value });
    catalog.value = data.items;
    options.value = await get('checkout_options', { outlet: outlet.value });
  } catch (error) { notice.value = String(error); }
}

async function createOrder() {
  if (!outlet.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'create', outlet: outlet.value, channel: channel.value, tab_label: tabLabel.value || undefined },
      event_id: eventId(), expected_revision: 0,
    });
    tenders.value = [];
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

async function add(item: CatalogItem) {
  if (!order.value) await createOrder();
  if (!order.value) return;
  busy.value = true; notice.value = '';
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'add_line', item: item.item, qty: 1 }, event_id: eventId(),
      order_name: order.value.name, expected_revision: order.value.revision,
    });
    if (tenders.value.length === 1 && tenders.value[0].currency === order.value.currency)
      tenders.value[0].amount = order.value.grand_total;
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

function addTender() {
  tenders.value.push({ mode_of_payment: options.value?.cash_modes[0] || 'Cash',
    currency: order.value?.currency || 'USD', amount: tenders.value.length ? 0 : order.value?.grand_total || 0 });
}

async function checkout() {
  if (!order.value) return;
  busy.value = true; notice.value = '';
  try {
    const chosen = tenders.value.length ? tenders.value : [{
      mode_of_payment: options.value?.cash_modes[0] || 'Cash',
      currency: order.value.currency, amount: order.value.grand_total,
    }];
    order.value = await post<Order>('cash_checkout', { order_name: order.value.name,
      tenders: chosen, event_id: eventId(), expected_revision: order.value.revision });
    notice.value = text(`Paid · POS Invoice ${order.value.pos_invoice}`, 'تم الدفع وتسجيل فاتورة نقطة البيع');
    options.value = await get('checkout_options', { outlet: outlet.value });
  } catch (error) { notice.value = String(error); }
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
    notice.value = text('Sent to kitchen.', 'أُرسل الطلب إلى المطبخ.');
  } catch (error) { notice.value = String(error); }
  finally { busy.value = false; }
}

watch([outlet, channel], loadCatalog);
onMounted(load);
</script>

<template>
  <div class="shell" :dir="rtl ? 'rtl' : 'ltr'">
    <header class="topbar">
      <h1>Table Remote Till</h1>
      <select v-model="outlet" :aria-label="text('Outlet', 'الفرع')">
        <option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option>
      </select>
      <select v-model="channel" :aria-label="text('Sale type', 'نوع البيع')">
        <option value="Till">{{ text('Counter', 'الصندوق') }}</option>
        <option value="Table">{{ text('Table', 'طاولة') }}</option>
        <option value="Tab">{{ text('Tab', 'حساب مفتوح') }}</option>
        <option value="Takeaway">{{ text('Takeaway', 'سفري') }}</option>
        <option value="Retail">{{ text('Retail', 'تجزئة') }}</option>
      </select>
      <span class="spacer" />
      <button @click="language = rtl ? 'en' : 'ar'">{{ rtl ? 'English' : 'العربية' }}</button>
      <a href="/app" style="color:white">{{ text('Manager Desk', 'لوحة الإدارة') }}</a>
      <a href="/app/pos-opening-entry" style="color:white">{{ text('Open shift', 'فتح الوردية') }}</a>
      <a href="/app/pos-closing-entry" style="color:white">{{ text('Close shift', 'إغلاق الوردية') }}</a>
    </header>
    <main class="content">
      <section class="panel">
        <h2>{{ text('Catalog', 'المنتجات') }}</h2>
        <label class="field"><span>{{ text('Search item or barcode', 'ابحث عن صنف أو باركود') }}</span>
          <input v-model="search" autofocus :placeholder="text('Search…', 'بحث…')" />
        </label>
        <p v-if="!visibleItems.length" class="muted">{{ text('No items available for this outlet and channel.', 'لا توجد أصناف متاحة لهذا الفرع.') }}</p>
        <div class="grid" style="margin-top:1rem">
          <button v-for="item in visibleItems" :key="item.item" class="item" :disabled="busy || order?.status === 'Sent' || order?.status === 'Settled'" @click="add(item)">
            <strong>{{ rtl ? item.name_ar || item.name_en : item.name_en }}</strong>
            <small>{{ item.item }}</small>
            <b>{{ item.rate }} {{ order?.currency || outlets.find(x => x.name === outlet)?.base_currency }}</b>
          </button>
        </div>
      </section>
      <aside class="panel stack">
        <h2>{{ text('Current order', 'الطلب الحالي') }}</h2>
        <label v-if="channel === 'Tab'" class="field"><span>{{ text('Tab name', 'اسم الحساب') }}</span><input v-model="tabLabel" /></label>
        <div class="row"><button class="ghost" :disabled="busy || !outlet" @click="createOrder">{{ text('New order', 'طلب جديد') }}</button>
          <span v-if="order" class="muted">{{ order.name.slice(0, 8) }} · {{ order.status }}</span></div>
        <div v-if="notice" class="status" :class="{ error: notice.startsWith('Error') }" role="status">{{ notice }}</div>
        <p v-if="!order?.lines.length" class="muted">{{ text('Choose an item to start.', 'اختر صنفاً للبدء.') }}</p>
        <div v-for="line in order?.lines || []" :key="line.name" class="line">
          <span>{{ line.qty }} × {{ line.item_name }}</span><strong>{{ line.amount }}</strong>
        </div>
        <div v-if="order" class="totals">
          <div><span>{{ text('Subtotal', 'المجموع') }}</span><span>{{ order.net_total }} {{ order.currency }}</span></div>
          <div><span>{{ text('Tax', 'الضريبة') }}</span><span>{{ order.tax_total }} {{ order.currency }}</span></div>
          <div><strong>{{ text('Total', 'الإجمالي') }}</strong><strong>{{ order.grand_total }} {{ order.currency }}</strong></div>
        </div>
        <button class="primary" :disabled="busy || !order?.lines.length || order?.status !== 'Draft'" @click="send">
          {{ text('Send to kitchen', 'إرسال إلى المطبخ') }}
        </button>
        <div v-if="order?.lines.length && order?.status !== 'Settled'" class="stack">
          <h2>{{ text('Cash tender', 'الدفع النقدي') }}</h2>
          <p v-if="!options?.opening_entry" class="status error">{{ text('Open today’s POS session in ERPNext before checkout.', 'افتح جلسة نقطة البيع لليوم قبل الدفع.') }}</p>
          <p v-if="options && !options.pos_invoice_mode" class="status error">{{ text('Set POS Settings to POS Invoice mode.', 'اضبط إعدادات نقطة البيع على فاتورة نقطة البيع.') }}</p>
          <div v-for="(tender, index) in tenders" :key="index" class="row">
            <select v-model="tender.mode_of_payment"><option v-for="mode in options?.cash_modes || []" :key="mode">{{ mode }}</option></select>
            <select v-model="tender.currency"><option>{{ order.currency }}</option><option v-if="order.currency !== 'LBP'">LBP</option><option v-else>USD</option></select>
            <input v-model.number="tender.amount" type="number" min="0" step="any" style="width:7rem" :aria-label="text('Tender amount', 'قيمة الدفع')" />
            <button class="ghost" @click="tenders.splice(index, 1)">×</button>
          </div>
          <button class="ghost" @click="addTender">{{ text('Add tender', 'إضافة دفعة') }}</button>
          <p v-if="options?.fx_rate" class="muted">1 USD = {{ options.fx_rate.lbp_per_usd }} LBP</p>
          <button class="primary" :disabled="busy || !options?.opening_entry || !options?.pos_invoice_mode || !options?.cash_modes.length" @click="checkout">
            {{ text('Settle cash in ERPNext', 'تسجيل النقد في فرابي') }}
          </button>
        </div>
        <p v-if="order?.pos_invoice" class="muted">{{ order.pos_invoice }}</p>
      </aside>
    </main>
  </div>
</template>
