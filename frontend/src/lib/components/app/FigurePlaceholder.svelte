<!--
  Blueprint #3 — Aspect-Ratio Placeholders for textbook figures.
  Reserves the exact pixel_width × pixel_height box (no layout shift) with a skeleton/diagram,
  then snaps the image in when it arrives. If the asset isn't reachable (running on mocks),
  a graceful labelled figure card holds the space without 404 image errors.
-->
<script lang="ts">
	import type { Asset } from '$api/v1';

	let { asset, class: className = '' }: { asset: Asset; class?: string } = $props();

	let loaded = $state(false);
	let isMockAsset = $derived(asset.thumbnail_url?.startsWith('/v1/') ?? true);
	let loadError = $state(false);
	let failed = $derived(isMockAsset || loadError);
</script>

<figure
	class="relative overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/90 text-slate-100 dark:border-slate-800 dark:bg-slate-900 {className}"
	style="aspect-ratio: {asset.pixel_width} / {asset.pixel_height};"
>
	{#if !failed}
		<img
			src={asset.thumbnail_url}
			alt={asset.alt_text ?? 'Textbook figure'}
			loading="lazy"
			class="absolute inset-0 h-full w-full object-cover transition-opacity duration-700 {loaded
				? 'opacity-100'
				: 'opacity-0'}"
			onload={() => (loaded = true)}
			onerror={() => (failed = true)}
		/>
	{/if}

	{#if !loaded || failed}
		<div
			class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6 text-center text-slate-200"
		>
			<svg
				class="h-8 w-8 text-blue-400"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.6"
				aria-hidden="true"
			>
				<rect x="3" y="4" width="18" height="16" rx="2" />
				<circle cx="9" cy="10" r="1.6" />
				<path d="M3 17l5-4 3 2 4-4 6 5" stroke-linecap="round" stroke-linejoin="round" />
			</svg>
			<p class="max-w-[26ch] text-xs font-medium leading-snug text-slate-200">
				{asset.alt_text ?? 'Textbook figure'}
			</p>
			<span class="font-mono text-[10px] tracking-widest text-slate-400">
				Figure · {asset.pixel_width} × {asset.pixel_height}
			</span>
		</div>
	{/if}
</figure>
