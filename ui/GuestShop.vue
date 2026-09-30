<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { eventId, get, post, type CatalogItem, type GuestAppearance, type Order, type Outlet } from './client';
import './styles.css';
import './theme.css';
import Icon from './Icon.vue';
import Feedback from './Feedback.vue';
import ModifierPicker from './ModifierPicker.vue';
import { money } from './format';

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
const tableTitle = ref('');
const busy = ref(false);
const notice = ref('');
const search = ref('');
const category = ref('');
const loadingPending = ref(false);
const loading = ref(false);
const selectedItem = ref<CatalogItem | null>(null);
const categories = computed(() => [...new Set(items.value.map(item => item.category).filter(Boolean))] as string[]);
const visibleItems = computed(() => items.value.filter(item => (!category.value || item.category === category.value) && [item.name_en, item.name_ar || ''].some(name => name.toLowerCase().includes(search.value.trim().toLowerCase()))));
const itemCount = computed(() => order.value?.lines.reduce((sum, line) => sum + line.qty, 0) || 0);
const price = (value: number) => money(value, order.value?.currency || selectedOutlet.value?.base_currency || 'USD', language.value);
const selectedOutlet = computed(() => outlets.value.find(row => row.name === outlet.value));
const defaultAppearance: GuestAppearance = {
  brand_logo: '', primary_color: '#171917', accent_color: '#e8f574', page_color: '#f7f8f3',
  surface_color: '#ffffff', text_color: '#171917', muted_color: '#686d67', heading_font: 'Manrope',
  body_font: 'DM Sans', brand_title_en: '', brand_title_ar: '', brand_tagline_en: '', brand_tagline_ar: '', hero_title_en: '', hero_title_ar: '',
  hero_subtitle_en: '', hero_subtitle_ar: '', hero_image: '', layout_style: 'Cards', card_style: 'Rounded',
  loading_message_en: '', loading_message_ar: '', loading_style: 'Food', empty_style: 'Illustrated',
  success_style: 'Sparkle', motion_style: 'Playful',
};
const appearance = computed(() => selectedOutlet.value?.appearance || defaultAppearance);
const appearanceVars = computed(() => ({
  '--guest-primary': appearance.value.primary_color,
  '--guest-accent': appearance.value.accent_color,
  '--guest-page': appearance.value.page_color,
  '--guest-surface': appearance.value.surface_color,
  '--guest-text': appearance.value.text_color,
  '--guest-muted': appearance.value.muted_color,
  '--guest-heading-font': `'${appearance.value.heading_font}', system-ui, sans-serif`,
  '--guest-body-font': `'${appearance.value.body_font}', system-ui, sans-serif`,
}));
const guestBrand = computed(() => rtl.value ? appearance.value.brand_title_ar || appearance.value.brand_title_en || selectedOutlet.value?.title || 'S&S (Seat & Serve)' : appearance.value.brand_title_en || selectedOutlet.value?.title || 'S&S (Seat & Serve)');
const guestTagline = computed(() => rtl.value ? appearance.value.brand_tagline_ar || appearance.value.brand_tagline_en || label('Made for a good time.', 'لأوقات طيبة.') : appearance.value.brand_tagline_en || label('Made for a good time.', 'لأوقات طيبة.'));
const defaultHeroTitle = computed(() => props.mode === 'Kiosk'
  ? label('Your order starts here.', 'ابدأ طلبك من هنا.')
  : label('What sounds good?', 'ماذا تشتهي اليوم؟'));
const defaultHeroSubtitle = computed(() => props.mode === 'Kiosk'
  ? label('Browse the menu, add your favorites, and review your order.', 'تصفح القائمة، واختر ما تحب، ثم راجع طلبك.')
  : label('Find something you love. We’ll take it from here.', 'اختر ما تحب ودع الباقي علينا.'));
const heroTitle = computed(() => (rtl.value ? appearance.value.hero_title_ar : appearance.value.hero_title_en) || defaultHeroTitle.value);
const heroSubtitle = computed(() => (rtl.value ? appearance.value.hero_subtitle_ar : appearance.value.hero_subtitle_en) || defaultHeroSubtitle.value);
const successClass = computed(() => `success-${appearance.value.success_style.toLowerCase()}`);
const motionClass = computed(() => `motion-${appearance.value.motion_style.toLowerCase()}`);
const noticeKind = ref<'success' | 'info' | 'warning' | 'error' | 'busy'>('info');
const catalogHasError = computed(() => noticeKind.value === 'error' && !!notice.value && !items.value.length);
const recentlyAdded = ref('');
const cartPulse = ref(false);
let feedbackTimer: ReturnType<typeof setTimeout> | undefined;
let addedTimer: ReturnType<typeof setTimeout> | undefined;
let cartTimer: ReturnType<typeof setTimeout> | undefined;
let loadingTimer: ReturnType<typeof setTimeout> | undefined;
function beginLoading() {
  loadingPending.value = true;
  loading.value = false;
  if (loadingTimer) clearTimeout(loadingTimer);
  loadingTimer = setTimeout(() => { loading.value = true; }, 140);
}
function finishLoading() {
  if (loadingTimer) clearTimeout(loadingTimer);
  loading.value = false;
  loadingPending.value = false;
}
function setFeedback(kind: typeof noticeKind.value, message: string, duration = 0) {
  if (feedbackTimer) clearTimeout(feedbackTimer);
  noticeKind.value = kind;
  notice.value = message;
  if (duration) feedbackTimer = setTimeout(() => { notice.value = ''; }, duration);
}
function clearFeedback() {
  if (feedbackTimer) clearTimeout(feedbackTimer);
  notice.value = '';
}
watch(itemCount, (next, previous) => {
  if (next === previous) return;
  cartPulse.value = true;
  if (cartTimer) clearTimeout(cartTimer);
  cartTimer = setTimeout(() => { cartPulse.value = false; }, 500);
});

async function loadOutlets() {
  const presetOutlet = Boolean(outlet.value);
  beginLoading();
  try {
    outlets.value = await get<Outlet[]>('public_outlets', { channel });
    if (!outlet.value) outlet.value = outlets.value[0]?.name || '';
    if (!outlets.value.some(row => row.name === outlet.value)) {
      outlet.value = '';
      setFeedback('error', label('This outlet is unavailable.', 'هذا الفرع غير متاح.'));
    }
    if (presetOutlet && outlet.value) await loadCatalog();
  } catch (error) { setFeedback('error', String(error)); finishLoading(); }
  finally { if (!outlet.value) finishLoading(); }
}

async function loadCatalog() {
  if (!outlet.value) return;
  order.value = null;
  selectedItem.value = null;
  token.value = ''; tableTitle.value = ''; items.value = []; category.value = ''; search.value = '';
  beginLoading(); clearFeedback();
  try {
    const catalog = await get<{ items: CatalogItem[] }>('catalog', { outlet: outlet.value, channel });
    items.value = catalog.items;
    if (channel === 'QR') {
      const link = await post<{ token: string; table_title?: string }>('guest_link', {
        outlet: outlet.value, channel, table: query.get('table'), qr_secret: query.get('key'),
      });
      token.value = link.token;
      tableTitle.value = link.table_title || '';
    }
  } catch (error) { setFeedback('error', String(error)); }
  finally { finishLoading(); }
}

async function ensureOrder() {
  if (order.value) return;
  if (!token.value) {
    const link = await post<{ token: string; table_title?: string }>('guest_link', {
      outlet: outlet.value, channel,
      ...(channel === 'QR' ? { table: query.get('table'), qr_secret: query.get('key') } : {}),
    });
    token.value = link.token;
    tableTitle.value = link.table_title || tableTitle.value;
  }
  order.value = await post<Order>('order_command', {
    command: { action: 'create', outlet: outlet.value, channel,
      ...(channel === 'QR' ? { table: query.get('table') } : {}) },
    event_id: eventId(), expected_revision: 0, guest_token: token.value,
  });
}

function choose(item: CatalogItem) {
  if (item.modifier_group) selectedItem.value = item;
  else void add(item);
}

async function addSelected(modifiers: string[], note: string) {
  if (selectedItem.value) await add(selectedItem.value, modifiers, note);
}

async function add(item: CatalogItem, modifiers: string[] = [], note = '') {
  busy.value = true; clearFeedback();
  try {
    await ensureOrder();
    if (!order.value) return;
    order.value = await post<Order>('order_command', {
      command: { action: 'add_line', item: item.item, qty: 1, modifiers, note },
      event_id: eventId(), order_name: order.value.name,
      expected_revision: order.value.revision, guest_token: token.value,
    });
    selectedItem.value = null;
    recentlyAdded.value = item.item;
    if (addedTimer) clearTimeout(addedTimer);
    addedTimer = setTimeout(() => { recentlyAdded.value = ''; }, 1100);
    setFeedback('success', label(`${item.name_en} added to your order`, `تمت إضافة ${item.name_ar || item.name_en} إلى طلبك`), 1800);
  } catch (error) { setFeedback('error', String(error)); }
  finally { busy.value = false; }
}

async function changeQty(line: Order['lines'][number], qty: number) {
  if (!order.value) return;
  busy.value = true; clearFeedback();
  try {
    order.value = await post<Order>('order_command', {
      command: { action: 'set_qty', line: line.name, qty },
      event_id: eventId(), order_name: order.value.name,
      expected_revision: order.value.revision, guest_token: token.value,
    });
  } catch (error) { setFeedback('error', String(error)); }
  finally { busy.value = false; }
}

async function demoCheckout() {
  if (!order.value) return;
  busy.value = true; clearFeedback();
  try {
    const payment = await post<{ attempt: string; provider: string }>('payment_intent', {
      order_name: order.value.name, idempotency_key: eventId(),
      expected_revision: order.value.revision, guest_token: token.value,
    });
    if (payment.provider !== 'Sandbox') throw new Error('Provider checkout is not available yet.');
    await post('sandbox_capture', { attempt_name: payment.attempt,
      expected_revision: order.value.revision, guest_token: token.value });
    setFeedback('success', `${label('Demo order sent. No money was charged.', 'أُرسل الطلب التجريبي. لم تُحصّل أي أموال.')} ${order.value.order_number}`);
    order.value = null;
    token.value = '';
  } catch (error) { setFeedback('error', String(error)); }
  finally { busy.value = false; }
}

watch(outlet, loadCatalog);
onMounted(loadOutlets);
onUnmounted(() => {
  if (feedbackTimer) clearTimeout(feedbackTimer);
  if (addedTimer) clearTimeout(addedTimer);
  if (cartTimer) clearTimeout(cartTimer);
  if (loadingTimer) clearTimeout(loadingTimer);
});
</script>

<template>
  <div class="shell guest-shell" :class="[props.mode === 'Kiosk' ? 'kiosk-mode' : 'menu-mode', `card-${appearance.card_style.toLowerCase()}`, `layout-${appearance.layout_style === 'Compact list' ? 'compact' : 'cards'}`, motionClass]" :style="appearanceVars" :dir="rtl ? 'rtl' : 'ltr'" :lang="language">
    <header v-if="props.mode !== 'Kiosk'" class="topbar"><div class="brand"><span class="brand-mark"><img v-if="appearance.brand_logo" :src="appearance.brand_logo" alt="" /><Icon v-else name="leaf" /></span><span>{{ guestBrand }}<small>{{ guestTagline }}</small></span></div><div class="header-tools"><select v-if="channel !== 'QR'" v-model="outlet" :disabled="busy || loadingPending" :aria-label="label('Outlet', 'الفرع')"><option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option></select><span v-else class="badge">{{ tableTitle ? `${label('Table', 'طاولة')} ${tableTitle}` : label('Dine in', 'داخل المطعم') }}</span><button class="language" @click="language = rtl ? 'en' : 'ar'">{{ rtl ? 'English' : 'العربية' }}</button></div></header>
    <div class="workspace-heading guest-heading" :class="{ 'has-hero-image': appearance.hero_image }"><img v-if="appearance.hero_image" class="guest-hero-image" :src="appearance.hero_image" alt="" /><div v-if="props.mode === 'Kiosk'" class="kiosk-utility-row"><span class="kiosk-outlet-name"><img v-if="appearance.brand_logo" :src="appearance.brand_logo" alt="" /><Icon v-else name="leaf" />{{ guestBrand }}</span><div><select v-model="outlet" :disabled="busy || loadingPending" :aria-label="label('Outlet', 'الفرع')"><option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option></select><button class="language" @click="language = rtl ? 'en' : 'ar'">{{ rtl ? 'English' : 'العربية' }}</button></div></div><div class="guest-hero-copy"><p class="eyebrow">{{ props.mode === 'Kiosk' ? label('ORDER HERE', 'اطلب من هنا') : label('WELCOME TO THE TABLE', 'أهلاً بكم') }}</p><h1>{{ heroTitle }}</h1><p class="muted">{{ heroSubtitle }}</p></div><span class="badge">{{ channel === 'QR' ? label('Dine in', 'داخل المطعم') : props.mode === 'Kiosk' ? label('Self service', 'خدمة ذاتية') : label('Order & collect', 'اطلب واستلم') }}</span></div>
    <main class="content">
      <section class="catalog-area" :aria-label="label('Menu', 'القائمة')" :aria-busy="loadingPending">
        <label class="search-field"><Icon name="search" /><input v-model="search" type="search" :placeholder="label('Find your favorite…', 'ابحث عن طبقك المفضل…')" :aria-label="label('Search menu', 'البحث في القائمة')" /></label>
        <div class="category-tabs"><button :class="{ active: !category }" :aria-pressed="!category" @click="category = ''"><Icon name="grid" />{{ label('All items', 'كل الأصناف') }}</button><button v-for="name in categories" :key="name" :class="{ active: category === name }" :aria-pressed="category === name" @click="category = name">{{ name }}</button></div>
        <Transition name="guest-state" mode="out-in">
        <div v-if="loading" key="loading" class="guest-loading" :class="[`loading-${appearance.loading_style.toLowerCase()}`]" role="status" aria-live="polite">
            <div class="loading-mark"><span class="loading-orbit">{{ appearance.loading_style === 'Food' ? '✦' : appearance.loading_style === 'Sparkle' ? '✧' : '●' }}</span><span class="loading-orbit-secondary">✧</span></div>
            <h2>{{ rtl ? appearance.loading_message_ar || 'نحضّر القائمة الشهية…' : appearance.loading_message_en || 'Getting the good stuff ready…' }}</h2>
            <div class="loading-skeletons" aria-hidden="true"><span v-for="n in 4" :key="n" class="loading-skeleton"><i></i><b></b><small></small></span></div>
          </div>
          <div v-else-if="loadingPending" key="pending" class="guest-loading-placeholder" aria-hidden="true"></div>
          <div v-else-if="catalogHasError" key="error" class="guest-load-error"><Feedback kind="error" :message="notice" :language="language" /><button class="ghost" type="button" @click="outlet ? loadCatalog() : loadOutlets()">{{ label('Try again', 'حاول مجدداً') }}</button></div>
          <div v-else-if="!visibleItems.length" key="empty" class="empty-state" :class="`empty-${appearance.empty_style.toLowerCase()}`"><span class="empty-icon"><Icon :name="items.length ? 'search' : 'kitchen'" /></span><h2>{{ items.length ? label('Nothing found just yet', 'لا توجد نتائج') : label('The menu isn’t available yet', 'القائمة غير متاحة حالياً') }}</h2><p>{{ items.length ? label('Try another search or browse all items.', 'جرّب بحثاً آخر أو تصفح كل الأصناف.') : label('Please ask a member of our team for help.', 'يرجى طلب المساعدة من أحد أعضاء فريقنا.') }}</p><button v-if="items.length" class="ghost" @click="search = ''; category = ''">{{ label('Show all items', 'عرض كل الأصناف') }}</button></div>
          <TransitionGroup v-else key="menu" name="guest-item" tag="div" class="grid product-grid"><button v-for="(item, index) in visibleItems" :key="item.item" class="item" :class="{ 'item-added': recentlyAdded === item.item }" :disabled="busy" @click="choose(item)"><span class="product-symbol" :class="'tone-' + (index % 4)"><Icon :name="recentlyAdded === item.item ? 'check' : 'kitchen'" /></span><small>{{ item.category || label('From our menu', 'من قائمتنا') }}</small><strong>{{ rtl ? item.name_ar || item.name_en : item.name_en }}</strong><span class="product-bottom"><b>{{ price(item.rate) }}</b><span class="add-item"><Icon :name="recentlyAdded === item.item ? 'check' : 'plus'" /></span></span></button></TransitionGroup>
        </Transition>
      </section>
      <aside id="guest-order" class="panel order-panel stack"><div class="panel-title"><div><p class="eyebrow">{{ label('SOMETHING GOOD', 'اختيار شهي') }}</p><h2>{{ label('Your order', 'طلبك') }} <span class="count-badge" :class="{ 'cart-pulse': cartPulse }">{{ itemCount }}</span></h2><small v-if="order?.order_number" class="guest-order-number">{{ order.order_number }}</small></div><Icon name="bag" /></div>
        <Transition name="feedback"><Feedback v-if="busy" kind="busy" :message="label('Updating your order…', 'جارٍ تحديث طلبك…')" :language="language" /></Transition>
        <Transition name="feedback"><Feedback v-if="notice && !busy && !catalogHasError" :kind="noticeKind" :message="notice" :language="language" :class="{ [successClass]: noticeKind === 'success' }" dismissible @dismiss="notice = ''" /></Transition>
        <div v-if="!order?.lines.length" class="empty-order"><Icon name="bag" /><h3>{{ label('A little hungry?', 'هل تشعر بالجوع؟') }}</h3><p>{{ label('Tap something you like to start your order.', 'اختر ما يعجبك لبدء طلبك.') }}</p></div>
        <TransitionGroup v-else name="order-line" tag="div" class="order-lines"><div v-for="line in order.lines" :key="line.name" class="line"><div><strong>{{ line.item_name }}</strong><small v-if="line.modifiers?.length" class="order-line-modifiers">{{ line.modifiers.map(option => rtl ? option.name_ar || option.name_en : option.name_en).join(', ') }}</small><small v-if="line.note" class="order-line-modifiers">{{ line.note }}</small><div class="quantity-control"><button :disabled="busy" :aria-label="label('Decrease quantity of ', 'تقليل كمية ') + line.item_name" @click="changeQty(line, line.qty - 1)">−</button><span>{{ line.qty }}</span><button :disabled="busy" :aria-label="label('Increase quantity of ', 'زيادة كمية ') + line.item_name" @click="changeQty(line, line.qty + 1)">+</button></div></div><strong>{{ price(line.amount) }}</strong></div></TransitionGroup>
        <div class="totals"><div><span>{{ label('Subtotal', 'المجموع') }}</span><span>{{ price(order?.net_total || 0) }}</span></div><div><span>{{ label('Tax', 'الضريبة') }}</span><span>{{ price(order?.tax_total || 0) }}</span></div><div class="grand-total"><strong>{{ label('Total', 'الإجمالي') }}</strong><strong>{{ price(order?.grand_total || 0) }}</strong></div></div>
        <button class="primary" :class="{ 'is-busy': busy }" :disabled="busy || !order?.lines.length" @click="demoCheckout">{{ busy ? label('Please wait…', 'يرجى الانتظار…') : label('Place demo order', 'إرسال طلب تجريبي') }}<Icon :name="busy ? 'refresh' : 'arrow'" :class="{ 'feedback-spin': busy }" /></button><p class="demo-note">{{ label('Demo checkout · No money is charged. Available when sandbox payments are enabled.', 'طلب تجريبي · لن يتم تحصيل أموال. متاح عند تفعيل الدفع التجريبي.') }}</p>
      </aside>
    </main><a v-if="itemCount" href="#guest-order" class="mobile-order-link"><Icon name="bag" />{{ label('View your order', 'عرض طلبك') }} · {{ itemCount }}<strong>{{ price(order?.grand_total || 0) }}</strong></a>
    <Transition name="modifier"><ModifierPicker v-if="selectedItem" :item="selectedItem" :currency="selectedOutlet?.base_currency || 'USD'" :language="language" :busy="busy" variant="guest" @confirm="addSelected" @cancel="selectedItem = null" /></Transition>
  </div>
</template>
