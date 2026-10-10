<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { eventId, get, post, type CatalogItem } from '../../ui/client';
import { money } from '../../ui/format';
import Feedback from '../../ui/Feedback.vue';

const props = defineProps<{ outlet: string; outletTitle: string; language: 'en' | 'ar' }>();
const emit = defineEmits<{ saved: [] }>();
const text = (en: string, ar: string) => props.language === 'ar' ? ar : en;
type Options = {
  currency: string; groups: string[]; uoms: string[];
  menus: { name: string; title: string }[]; stations: { name: string; title: string }[];
  ingredients: { name: string; item_name: string; stock_uom: string }[];
};
const options = ref<Options | null>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref('');
const success = ref('');
const name = ref('');
const nameAr = ref('');
const price = ref<number | ''>('');
const group = ref('');
const uom = ref('Nos');
const menu = ref('');
const station = ref('');
const ingredients = ref([{ item: '', qty: 1 }]);
const requestId = ref(eventId());
const items = ref<CatalogItem[]>([]);
const search = ref('');
const visibleItems = computed(() => items.value.filter(item =>
  [item.name_en, item.name_ar || '', item.item].some(value => value.toLowerCase().includes(search.value.toLowerCase()))));
const ingredientUnit = (item: string) => options.value?.ingredients.find(row => row.name === item)?.stock_uom || '';
let catalogDirty = false;

async function refreshItems() {
  const data = await get<{ items: CatalogItem[] }>('catalog', { outlet: props.outlet, channel: 'Till' });
  items.value = data.items;
}
async function load() {
  loading.value = true; error.value = '';
  try {
    options.value = await get<Options>('items.item_options', { outlet: props.outlet });
    group.value ||= options.value.groups[0] || '';
    if (!options.value.uoms.includes(uom.value)) uom.value = options.value.uoms[0] || '';
    menu.value ||= options.value.menus[0]?.name || '';
    await refreshItems();
  } catch (cause) { error.value = String(cause); }
  finally { loading.value = false; }
}
async function save() {
  if (saving.value || !options.value) return;
  saving.value = true; error.value = ''; success.value = '';
  try {
    const result = await post<{ item: string; name: string; menu: string }>('items.create_item', {
      outlet: props.outlet, request_id: requestId.value,
      details: { name: name.value.trim(), name_ar: nameAr.value.trim(), price: price.value,
        group: group.value, uom: uom.value, menu: menu.value, station: station.value, ingredients: ingredients.value },
    });
    success.value = text(`${result.name} is ready to sell.`, `${result.name} جاهز للبيع.`);
    requestId.value = eventId();
    name.value = ''; nameAr.value = ''; price.value = ''; ingredients.value = [{ item: '', qty: 1 }];
    if (!options.value.menus.some(row => row.name === result.menu)) options.value.menus.push({ name: result.menu, title: text('Till menu', 'قائمة الصندوق') });
    menu.value = result.menu;
    catalogDirty = true;
    emit('saved');
    await refreshItems();
  } catch (cause) { error.value = String(cause); }
  finally { saving.value = false; }
}
function back() {
  if (saving.value) return;
  if (name.value.trim() && !window.confirm(text('Leave without saving this item?', 'مغادرة دون حفظ الصنف؟'))) return;
  if (catalogDirty) emit('saved');
  window.location.hash = '';
}
onMounted(load);
</script>

<template>
  <main class="item-manager" :dir="language === 'ar' ? 'rtl' : 'ltr'">
    <header class="item-manager-header"><button type="button" :disabled="saving" @click="back">← {{ text('Back to till', 'العودة للصندوق') }}</button><span>{{ outletTitle }}</span></header>
    <div class="item-manager-title"><div><p>{{ text('MENU MANAGEMENT', 'إدارة القائمة') }}</p><h1>{{ text('Add items', 'إضافة أصناف') }}</h1><span>{{ text('Create an item, set its price, and put it on the till menu in one step.', 'أنشئ صنفاً وحدد سعره وأضفه إلى قائمة الصندوق بخطوة واحدة.') }}</span></div></div>
    <Feedback v-if="error" kind="error" :message="error" :language="language" />
    <Feedback v-if="success" kind="success" :message="success" :language="language" />
    <Feedback v-if="loading" kind="busy" :message="text('Loading your menu…', 'جارٍ تحميل القائمة…')" :language="language" />
    <button v-if="!loading && !options" type="button" @click="load">{{ text('Try again', 'حاول مجدداً') }}</button>
    <div v-if="options && !loading" class="item-manager-layout">
      <form class="item-manager-card" @submit.prevent="save">
        <fieldset :disabled="saving">
          <h2>{{ text('New item', 'صنف جديد') }}</h2>
          <label>{{ text('Item name', 'اسم الصنف') }}<input v-model="name" required maxlength="140" :placeholder="text('e.g. Chicken sandwich', 'مثلاً: سندويش دجاج')" /></label>
          <label>{{ text('Arabic name (optional)', 'الاسم بالعربية (اختياري)') }}<input v-model="nameAr" maxlength="140" dir="rtl" /></label>
          <div class="item-manager-pair"><label>{{ text('Selling price', 'سعر البيع') }} · {{ options.currency }}<input v-model="price" type="number" inputmode="decimal" min="0" step="any" required placeholder="0.00" /></label><label>{{ text('Category', 'الفئة') }}<select v-model="group" required><option disabled value="">{{ text('Choose category', 'اختر فئة') }}</option><option v-for="value in options.groups" :key="value">{{ value }}</option></select></label></div>
          <div class="item-manager-pair"><label>{{ text('Sale unit', 'وحدة البيع') }}<select v-model="uom" required><option v-for="value in options.uoms" :key="value">{{ value }}</option></select></label><label>{{ text('Kitchen station', 'محطة المطبخ') }}<select v-model="station"><option value="">{{ text('No kitchen preparation', 'لا يحتاج تحضيراً بالمطبخ') }}</option><option v-for="row in options.stations" :key="row.name" :value="row.name">{{ row.title }}</option></select></label></div>
          <label>{{ text('Menu', 'القائمة') }}<select v-model="menu"><option v-if="!options.menus.length" value="">{{ text('Create a till menu automatically', 'إنشاء قائمة للصندوق تلقائياً') }}</option><option v-for="row in options.menus" :key="row.name" :value="row.name">{{ row.title }}</option></select></label>
          <section class="item-manager-recipe"><h3>{{ text('Ingredients for one sale unit', 'مكونات وحدة بيع واحدة') }}</h3><p>{{ text('For a packaged product, choose its stock item and enter 1. For prepared food, add each ingredient and its quantity.', 'للمنتج المعبأ اختر مادة المخزون وأدخل ١. للطعام المحضر أضف كل مكون وكميته.') }}</p>
            <p v-if="!options.ingredients.length">{{ text('Create your raw materials first, then refresh this page.', 'أنشئ المواد الأولية أولاً ثم حدّث الصفحة.') }} <a href="/app/item" target="_blank" rel="noopener">{{ text('Manage ingredients', 'إدارة المكونات') }}</a></p>
            <div v-for="(row, index) in ingredients" :key="index" class="item-manager-ingredient"><label>{{ text('Ingredient', 'المكون') }}<select v-model="row.item" required><option disabled value="">{{ text('Choose ingredient', 'اختر مكوناً') }}</option><option v-for="raw in options.ingredients" :key="raw.name" :value="raw.name">{{ raw.item_name }} · {{ raw.name }}</option></select></label><label>{{ text('Quantity', 'الكمية') }} {{ ingredientUnit(row.item) }}<input v-model.number="row.qty" type="number" min="0.000001" step="any" required /></label><button type="button" :disabled="ingredients.length === 1" :aria-label="text('Remove ingredient', 'حذف المكون')" @click="ingredients.splice(index, 1)">×</button></div>
            <button type="button" :disabled="ingredients.length >= 100" @click="ingredients.push({ item: '', qty: 1 })">+ {{ text('Add ingredient', 'إضافة مكون') }}</button>
          </section>
          <button class="item-manager-save" type="submit" :disabled="!options.ingredients.length">{{ saving ? text('Saving…', 'جارٍ الحفظ…') : text('Save & add to menu', 'حفظ وإضافة إلى القائمة') }}</button>
        </fieldset>
      </form>
      <section class="item-manager-card item-manager-list"><h2>{{ text('On your till menu', 'على قائمة الصندوق') }} <small>{{ items.length }}</small></h2><input v-model="search" type="search" :aria-label="text('Search menu items', 'بحث في أصناف القائمة')" :placeholder="text('Search items…', 'ابحث عن صنف…')" /><p v-if="!visibleItems.length">{{ text('No matching items.', 'لا توجد أصناف مطابقة.') }}</p><article v-for="item in visibleItems" :key="item.item + item.category"><div><strong>{{ language === 'ar' ? item.name_ar || item.name_en : item.name_en }}</strong><small>{{ item.category }}</small></div><span>{{ money(item.rate, options.currency, language) }}</span></article></section>
    </div>
  </main>
</template>

<style scoped>
.item-manager { min-height: 100vh; padding: 24px max(20px, calc((100vw - 1200px) / 2)); background: #f5f6ef; color: #20261e; font-family: inherit; }
.item-manager-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.item-manager button { cursor: pointer; border: 1px solid #c8cdbe; border-radius: 10px; padding: 11px 16px; background: white; color: inherit; font: inherit; }
.item-manager button:disabled { opacity: .5; cursor: default; }
.item-manager-title { margin: 40px 0 28px; }
.item-manager-title p { font-size: 11px; letter-spacing: .12em; font-weight: 800; }
.item-manager h1 { font-size: clamp(30px, 4vw, 44px); margin: 8px 0 12px; }
.item-manager h2 { margin: 0 0 24px; font-size: 21px; }
.item-manager-layout { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 24px; margin-top: 24px; align-items: start; }
.item-manager-card { padding: 28px; border: 1px solid #dce0d2; border-radius: 18px; background: white; }
.item-manager fieldset { min-width: 0; border: 0; margin: 0; padding: 0; }
.item-manager label { display: grid; gap: 8px; margin: 0 0 18px; font-size: 13px; font-weight: 600; min-width: 0; }
.item-manager input, .item-manager select { width: 100%; min-width: 0; min-height: 44px; box-sizing: border-box; padding: 10px 12px; border: 1px solid #c8cdbe; border-radius: 8px; background: #fff; color: #20261e; font: inherit; }
.item-manager-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.item-manager-recipe { margin: 10px 0 24px; border-top: 1px solid #e1e4d9; padding-top: 8px; }
.item-manager-recipe p { font-size: 13px; line-height: 1.6; color: #5b6355; }
.item-manager-ingredient { display: grid; grid-template-columns: minmax(0, 1fr) 100px 40px; align-items: center; gap: 10px; }
.item-manager-ingredient button { padding: 8px; }
.item-manager .item-manager-save { width: 100%; background: #e8f574; border-color: #c4d14e; font-weight: 800; }
.item-manager-list h2 { display: flex; justify-content: space-between; }
.item-manager-list article { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; border-bottom: 1px solid #eceee6; }
.item-manager-list article small { display: block; color: #6a7262; margin-top: 6px; }
.item-manager-list article span { white-space: nowrap; }
@media (max-width: 850px) { .item-manager-layout { grid-template-columns: 1fr; } }
@media (max-width: 480px) { .item-manager-card { padding: 18px; } .item-manager-pair { grid-template-columns: 1fr; gap: 0; } .item-manager-ingredient { grid-template-columns: minmax(0, 1fr) 75px 32px; gap: 6px; } }
</style>
