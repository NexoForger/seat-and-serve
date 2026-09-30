(() => {
  const base = '/api/method/table_remote_till.reservations.';
  const $ = (id) => document.getElementById(id);
  const form = $('reservation-form');
  const outlet = $('outlet');
  const date = $('date');
  const guests = $('party-size');
  const slots = $('slots');
  const message = $('message');
  const button = $('book-button');
  let selectedTime = '';
  let requestId = crypto.randomUUID();
  let availabilityRun = 0;

  async function call(method, args = {}, write = false) {
    const url = base + method + (write ? '' : '?' + new URLSearchParams(args));
    const response = await fetch(url, {
      method: write ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(write ? { 'Content-Type': 'application/json' } : {}),
        ...(window.csrf_token && !window.csrf_token.includes('{{') ? { 'X-Frappe-CSRF-Token': window.csrf_token } : {}) },
      body: write ? JSON.stringify(args) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.exc) {
      let detail = `Request failed (${response.status})`;
      if (data._server_messages) {
        try { detail = JSON.parse(data._server_messages).map((line) => JSON.parse(line).message).join('\n'); }
        catch { /* Keep the HTTP status. */ }
      }
      throw new Error(detail);
    }
    return data.message;
  }

  function feedback(text) {
    message.textContent = text;
    message.hidden = !text;
  }

  function showSlots(times, duration) {
    slots.replaceChildren();
    $('duration-label').textContent = duration ? `${duration} minute table` : '';
    if (!times.length) {
      const empty = document.createElement('span');
      empty.className = 'empty-slots';
      empty.textContent = 'No tables available for this selection. Try another date or party size.';
      slots.append(empty);
      return;
    }
    for (const time of times) {
      const choice = document.createElement('button');
      choice.type = 'button';
      choice.textContent = time;
      choice.setAttribute('aria-pressed', String(selectedTime === time));
      choice.classList.toggle('selected', selectedTime === time);
      choice.addEventListener('click', () => {
        selectedTime = time;
        for (const item of slots.querySelectorAll('button')) {
          item.classList.toggle('selected', item === choice);
          item.setAttribute('aria-pressed', String(item === choice));
        }
        feedback('');
      });
      slots.append(choice);
    }
  }

  async function refreshAvailability() {
    const run = ++availabilityRun;
    selectedTime = '';
    if (!outlet.value || !date.value || !guests.value) {
      showSlots([], 0);
      return;
    }
    slots.innerHTML = '<span class="empty-slots">Checking available tables…</span>';
    try {
      const data = await call('reservation_availability', { outlet: outlet.value,
        date: date.value, party_size: guests.value });
      if (run === availabilityRun) showSlots(data.slots, data.duration_minutes);
    } catch (error) {
      if (run === availabilityRun) { showSlots([], 0); feedback(error.message); }
    }
  }

  async function load() {
    const today = new Date();
    date.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    date.min = date.value;
    try {
      const places = await call('reservation_outlets');
      const requested = new URLSearchParams(location.search).get('outlet');
      for (const place of places) {
        const option = document.createElement('option');
        option.value = place.name;
        option.textContent = place.title;
        option.dataset.advanceDays = place.reservation_advance_days || 30;
        outlet.append(option);
      }
      if (!places.length) feedback('Online table reservations are not available yet.');
      else outlet.value = places.some((place) => place.name === requested) ? requested : places[0].name;
      updateDateLimit();
      await refreshAvailability();
    } catch (error) { feedback(error.message); }
  }

  function updateDateLimit() {
    const days = Number(outlet.selectedOptions[0]?.dataset.advanceDays || 30);
    const max = new Date(date.min + 'T12:00:00');
    max.setDate(max.getDate() + days);
    date.max = `${max.getFullYear()}-${String(max.getMonth() + 1).padStart(2, '0')}-${String(max.getDate()).padStart(2, '0')}`;
    if (date.value > date.max) date.value = date.max;
  }

  outlet.addEventListener('change', () => { updateDateLimit(); refreshAvailability(); });
  date.addEventListener('change', refreshAvailability);
  guests.addEventListener('change', refreshAvailability);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    feedback('');
    if (!selectedTime) return feedback('Choose an available time.');
    if (!$('phone').value.trim() && !$('email').value.trim()) return feedback('Add a phone number or email address.');
    button.disabled = true;
    try {
      const result = await call('book_reservation', { request_id: requestId,
        payload: { outlet: outlet.value, date: date.value, time: selectedTime,
          party_size: Number(guests.value), guest_name: $('guest-name').value.trim(),
          phone: $('phone').value.trim(), email: $('email').value.trim(),
          special_requests: $('special-requests').value.trim() } }, true);
      $('booking-view').hidden = true;
      $('confirmation').hidden = false;
      $('confirmation-details').textContent = `${result.outlet_title} · ${result.date} at ${result.time} · ${result.party_size} ${result.party_size === 1 ? 'guest' : 'guests'}`;
      $('confirmation-number').textContent = result.reservation_number;
    } catch (error) { feedback(error.message); await refreshAvailability(); }
    finally { button.disabled = false; }
  });
  $('another-button').addEventListener('click', () => {
    requestId = crypto.randomUUID();
    form.reset();
    $('booking-view').hidden = false;
    $('confirmation').hidden = true;
    feedback('');
    load();
  });
  load();
})();
