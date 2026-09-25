<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { eventId, get, post, type Outlet } from '../../ui/client';
import '../../ui/styles.css';

type Ticket = { name: string; order: string; station: string; status: string; revision: number; sent_at: string;
  lines: { item: string; qty: number; note?: string }[] };
const outlets = ref<Outlet[]>([]);
const outlet = ref('');
const tickets = ref<Ticket[]>([]);
const message = ref('');
const busy = ref(false);
const language = ref<'en' | 'ar'>('en');
const rtl = computed(() => language.value === 'ar');
const text = (en: string, ar: string) => rtl.value ? ar : en;
const columns = ['Queued', 'Preparing', 'Ready'];
let timer: ReturnType<typeof setInterval> | undefined;

async function refresh() {
  if (!outlet.value) return;
  try { tickets.value = (await get<Ticket[]>('kitchen_tickets', { outlet: outlet.value, status: 'All' }))
    .filter(ticket => columns.includes(ticket.status)); }
  catch (error) { message.value = String(error); }
}
async function setStatus(ticket: Ticket, status: string) {
  busy.value = true;
  try { await post('set_ticket_status', { ticket_name: ticket.name, status,
    event_id: eventId(), expected_revision: ticket.revision }); await refresh(); }
  catch (error) { message.value = String(error); }
  finally { busy.value = false; }
}
async function load() {
  try { const data = await get<{ outlets: Outlet[] }>('bootstrap');
    outlets.value = data.outlets; outlet.value = data.outlets[0]?.name || ''; }
  catch (error) { message.value = String(error); }
  timer = setInterval(refresh, 5000);
}
watch(outlet, refresh);
onMounted(load);
onUnmounted(() => timer && clearInterval(timer));
</script>

<template>
  <div class="shell" :dir="rtl ? 'rtl' : 'ltr'">
    <header class="topbar"><h1>{{ text('Kitchen display', 'شاشة المطبخ') }}</h1>
      <select v-model="outlet" :aria-label="text('Outlet', 'الفرع')">
        <option v-for="place in outlets" :key="place.name" :value="place.name">{{ place.title }}</option>
      </select><span class="spacer" />
      <button @click="refresh">{{ text('Refresh', 'تحديث') }}</button>
      <button @click="language = rtl ? 'en' : 'ar'">{{ rtl ? 'English' : 'العربية' }}</button>
    </header>
    <main style="padding:1rem;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem">
      <section v-for="status in columns" :key="status" class="panel">
        <h2>{{ status }} <small class="muted">({{ tickets.filter(t => t.status === status).length }})</small></h2>
        <p v-if="!tickets.some(t => t.status === status)" class="muted">{{ text('No tickets', 'لا توجد طلبات') }}</p>
        <article v-for="ticket in tickets.filter(t => t.status === status)" :key="ticket.name" class="panel" style="margin:.7rem 0;padding:.9rem">
          <div class="row"><strong>#{{ ticket.order.slice(0, 8) }}</strong><span class="spacer" /><small>{{ ticket.station }}</small></div>
          <p class="muted">{{ ticket.sent_at }}</p>
          <div v-for="(line, index) in ticket.lines" :key="index" class="line"><b>{{ line.qty }} × {{ line.item }}</b><small>{{ line.note }}</small></div>
          <button v-if="status !== 'Ready'" class="primary" :disabled="busy" style="margin-top:1rem;width:100%"
            @click="setStatus(ticket, status === 'Queued' ? 'Preparing' : 'Ready')">
            {{ status === 'Queued' ? text('Start', 'بدء') : text('Mark ready', 'جاهز') }}
          </button>
          <button v-else class="ghost" :disabled="busy" style="margin-top:1rem;width:100%" @click="setStatus(ticket, 'Served')">
            {{ text('Handed off', 'تم التسليم') }}
          </button>
        </article>
      </section>
    </main>
    <div v-if="message" class="status error" role="status">{{ message }}</div>
  </div>
</template>

<style scoped>@media(max-width:800px){main{grid-template-columns:1fr!important}}</style>
