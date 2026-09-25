import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import proxyOptions from './proxyOptions.ts';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [vue()],
	server: {
		port: 8081,
		host: '0.0.0.0',
		proxy: proxyOptions
	},
	resolve: {
		alias: {
			'@': new URL('./src', import.meta.url).pathname
		}
	},
	build: {
		outDir: '../table_remote_till/public/kitchen',
		emptyOutDir: true,
		target: 'es2015',
	},
});
