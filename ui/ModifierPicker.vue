<script setup lang="ts">
import { computed, ref } from 'vue';
import type { CatalogItem } from './client';
import { money } from './format';

const props = defineProps<{
  item: CatalogItem; currency: string; language: 'en' | 'ar'; busy?: boolean; variant?: 'register' | 'guest';
}>();
const emit = defineEmits<{ confirm: [modifiers: string[], note: string]; cancel: [] }>();
const selected = ref<string[]>([]);
const note = ref('');
const group = computed(() => props.item.modifier_group);
const rtl = computed(() => props.language === 'ar');
const label = (en: string, ar: string) => rtl.value ? ar : en;
const total = computed(() => props.item.rate + (group.value?.options || [])
  .filter(option => selected.value.includes(option.item))
  .reduce((sum, option) => sum + option.price_delta, 0));
const valid = computed(() => selected.value.length >= (group.value?.minimum || 0));

function toggle(code: string) {
  if (selected.value.includes(code)) {
    selected.value = selected.value.filter(value => value !== code);
  } else {
    selected.value = [...selected.value, code];
  }
}
</script>

<template>
  <div class="modifier-backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <section class="modifier-panel" :class="variant || 'guest'" :dir="rtl ? 'rtl' : 'ltr'" role="dialog" aria-modal="true" :aria-label="label('Customize item', 'تخصيص الصنف')">
      <header><div><small>{{ label('CUSTOMIZE', 'تخصيص') }}</small><h2>{{ rtl ? item.name_ar || item.name_en : item.name_en }}</h2></div><button type="button" class="modifier-close" :aria-label="label('Close', 'إغلاق')" @click="emit('cancel')">×</button></header>
      <p class="modifier-help">{{ group?.title }} · {{ group?.minimum ? label('Choose at least', 'اختر على الأقل') + ' ' + group.minimum : label('Choose any options you like', 'اختر ما تشاء من الإضافات') }}</p>
      <div class="modifier-options">
        <button v-for="option in group?.options || []" :key="option.item" type="button" :aria-pressed="selected.includes(option.item)" :class="{ selected: selected.includes(option.item) }" :disabled="busy" @click="toggle(option.item)">
          <span class="modifier-check">{{ selected.includes(option.item) ? '✓' : '+' }}</span><span>{{ rtl ? option.name_ar || option.name_en : option.name_en }}</span><strong>{{ option.price_delta ? '+' + money(option.price_delta, currency, language) : label('Free', 'مجاني') }}</strong>
        </button>
      </div>
      <label class="modifier-note"><span>{{ label('Special instructions', 'تعليمات خاصة') }}</span><textarea v-model="note" maxlength="200" rows="2" :placeholder="label('Optional note for the kitchen', 'ملاحظة اختيارية للمطبخ')" /></label>
      <footer><button type="button" class="modifier-cancel" @click="emit('cancel')">{{ label('Cancel', 'إلغاء') }}</button><button type="button" class="modifier-confirm" :disabled="busy || !valid" @click="emit('confirm', selected, note.trim())">{{ label('Add to order', 'أضف إلى الطلب') }} · {{ money(total, currency, language) }}</button></footer>
    </section>
  </div>
</template>

<style scoped>
.modifier-backdrop { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 16px; background: #10130ed1; }
.modifier-panel { width: min(440px, 100%); max-height: min(720px, 90vh); display: flex; flex-direction: column; gap: 14px; padding: 20px; border-radius: 18px; background: #fff; color: #1b2119; box-shadow: 0 22px 70px #0008; overflow-y: auto; }
.modifier-panel.register { background: #252b22; color: #f7f8f3; border: 1px solid #61704e; }
.modifier-panel header { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.modifier-panel header small { color: #839d31; font-weight: 800; letter-spacing: .14em; }
.modifier-panel h2 { margin: 3px 0 0; color: inherit; font-size: 21px; line-height: 1.2; }
.modifier-close { width: 40px; height: 40px; flex: 0 0 40px; border: 0; border-radius: 8px; color: inherit; background: #ced6c532; font-size: 25px; }
.modifier-help { margin: 0; font-size: 13px; opacity: .7; }
.modifier-options { display: grid; gap: 8px; }
.modifier-options button { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 8px 11px; border: 1px solid #cdd5c5; border-radius: 10px; color: inherit; background: transparent; text-align: start; font-size: 14px; }
.modifier-panel.register .modifier-options button { border-color: #586651; }
.modifier-panel.guest { color: var(--guest-text, #1b2119); font-family: var(--guest-body-font, inherit); border-radius: var(--guest-card-radius, 18px); }
.modifier-panel.guest header small { color: var(--guest-primary, #839d31); }
.modifier-panel.guest .modifier-close { background: color-mix(in srgb, var(--guest-muted, #ced6c5), transparent 82%); }
.modifier-panel.guest .modifier-options button { border-color: color-mix(in srgb, var(--guest-muted, #cdd5c5), transparent 35%); }
.modifier-panel.guest .modifier-options button.selected { border-color: var(--guest-accent, #9db331); background: color-mix(in srgb, var(--guest-accent, #e8f574), transparent 76%); }
.modifier-panel.guest .modifier-check, .modifier-panel.guest .modifier-confirm { color: var(--guest-primary, #1b2119); background: var(--guest-accent, #e8f574); }
.modifier-options button.selected { border-color: #9db331; background: #e8f57435; }
.modifier-options button > span:nth-child(2) { flex: 1; }
.modifier-options button strong { font-size: 12px; white-space: nowrap; }
.modifier-check { width: 23px; height: 23px; display: grid; place-items: center; border-radius: 6px; background: #e8f574; color: #1c2313; font-weight: 800; }
.modifier-note { display: grid; gap: 7px; font-size: 12px; font-weight: 700; }
.modifier-note textarea { width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #b6c0ad; border-radius: 9px; color: #1b2119; background: #fff; font: inherit; resize: vertical; }
.modifier-panel footer { display: grid; grid-template-columns: 1fr 2fr; gap: 8px; }
.modifier-panel footer button { min-height: 46px; border: 0; border-radius: 9px; font-weight: 750; }
.modifier-cancel { color: inherit; background: #ced6c532; }
.modifier-confirm { color: #1b2119; background: #e8f574; }
.modifier-confirm:disabled { opacity: .5; }
</style>
