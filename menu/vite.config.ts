import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import proxyOptions from './proxyOptions.ts';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [vue()],
	server: {
		port: 8083,
		host: '0.0.0.0',
		proxy: proxyOptions
	},
	resolve: {
		alias: {
			'@': new URL('./src', import.meta.url).pathname
		}
	},
	build: {
		outDir: '../table_remote_till/public/menu',
		emptyOutDir: true,
		target: 'es2015',
	},
});
