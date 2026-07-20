import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		// Tailwind CSS v4 — CSS-first config, no tailwind.config.js / postcss.config.js needed.
		tailwindcss(),
		sveltekit()
	],
	server: {
		fs: {
			// Allow serving the repo-root openapi.v1.yaml during dev if referenced.
			allow: ['..']
		}
	}
});
