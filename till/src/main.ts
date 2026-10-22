import { createApp } from 'vue';
import App from './App.vue';

if (new URLSearchParams(location.search).get('scanner') === 'phone') {
  import('./PhoneScanner.vue').then(({default: PhoneScanner}) => createApp(PhoneScanner).mount('#app'));
} else createApp(App).mount('#app');
