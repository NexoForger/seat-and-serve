import { createApp } from 'vue';
import App from './App.vue';

if (['phone', 'usb'].includes(new URLSearchParams(location.search).get('scanner') || '')) {
  import('./PhoneScanner.vue').then(({default: PhoneScanner}) => createApp(PhoneScanner).mount('#app'));
} else createApp(App).mount('#app');
