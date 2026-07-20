// The app is a client-rendered SPA: three.js/WebGL, SSE streaming and Lenis are
// browser-only, so we disable SSR and let adapter-static emit a fallback shell.
export const ssr = false;
export const prerender = false;
