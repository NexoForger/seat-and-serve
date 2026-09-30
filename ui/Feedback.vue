<script setup lang="ts">
import Icon from './Icon.vue';

const props = withDefaults(defineProps<{
  kind: 'success' | 'info' | 'warning' | 'error' | 'busy';
  message: string;
  language?: 'en' | 'ar';
  dismissible?: boolean;
}>(), { language: 'en', dismissible: false });
const emit = defineEmits<{ dismiss: [] }>();
const icons = { success: 'check', info: 'info', warning: 'warning', error: 'error', busy: 'refresh' } as const;
</script>

<template>
  <div class="trt-feedback" :class="[`is-${kind}`, { 'is-rtl': language === 'ar' }]" :role="kind === 'error' ? 'alert' : 'status'" :aria-live="kind === 'error' ? 'assertive' : 'polite'">
    <span class="trt-feedback-icon" :class="{ 'is-spinning': kind === 'busy' }"><Icon :name="icons[kind]" /></span>
    <span class="trt-feedback-message">{{ message }}</span>
    <button v-if="dismissible" type="button" class="trt-feedback-dismiss" :aria-label="language === 'ar' ? 'إغلاق' : 'Dismiss'" @click="emit('dismiss')">×</button>
  </div>
</template>
