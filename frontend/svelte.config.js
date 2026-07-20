import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Static SPA output: every route is client-rendered (3D + SSE are browser-only),
		// so we emit a single fallback shell and let the client router take over.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: false
		}),
		alias: {
			$api: 'src/lib/api',
			$components: 'src/lib/components'
		}
	}
};

export default config;
