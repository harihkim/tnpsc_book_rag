<!--
  Blueprint #2 — Spring-Loaded Citation Badges, on Svelte's built-in svelte/motion.
  The badge uses a Spring for organic hover/tap scale physics (≈ whileHover scale 1.08).
  Hovering or focusing slides out a glassmorphism source sheet (backdrop-blur) driven by
  a second Spring, presenting the textbook snippet immediately without disrupting the
  reading flow. A short close delay lets the pointer travel from badge to sheet.
-->
<script lang="ts">
	import { Spring, prefersReducedMotion } from 'svelte/motion';
	import type { Citation } from '$api/v1';

	let { citation }: { citation: Citation } = $props();
	let open = $state(false);

	// api_spec.md §3.3 — zero-based index, fall back when no printed label exists.
	let pageLabel = $derived(citation.printed_page_label ?? `PDF page ${citation.pdf_page_index + 1}`);
	let sheetId = $derived(`cite-sheet-${citation.citation_id}`);

	// Organic scale physics for the badge.
	const scale = new Spring(1, { stiffness: 420, damping: 17 });
	// Sheet reveal spring: 0 = hidden, 1 = fully shown.
	const sheet = new Spring(0, { stiffness: 380, damping: 26 });

	let closeTimer: ReturnType<typeof setTimeout> | undefined;

	function setOpen(next: boolean) {
		open = next;
		sheet.set(next ? 1 : 0, { instant: prefersReducedMotion.current });
	}
	function requestOpen() {
		clearTimeout(closeTimer);
		scale.set(1.08);
		setOpen(true);
	}
	function requestClose() {
		clearTimeout(closeTimer);
		scale.set(1);
		closeTimer = setTimeout(() => setOpen(false), 140);
	}
</script>

<span class="relative inline-block align-baseline">
	<button
		type="button"
		style:scale={scale.current}
		class="inline-flex cursor-pointer items-center rounded-md border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 font-mono text-[11px] font-bold text-amber-600 dark:text-amber-400 transition-colors hover:bg-amber-500/25 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-500"
		onpointerenter={requestOpen}
		onpointerleave={requestClose}
		onpointerdown={() => scale.set(0.94)}
		onpointerup={() => scale.set(1.08)}
		onfocus={requestOpen}
		onblur={requestClose}
		onclick={() => (open ? requestClose() : requestOpen())}
		aria-expanded={open}
		aria-describedby={sheetId}
	>{citation.citation_id}</button>

	<!-- Static centering wrapper; the inner sheet owns the animated transform -->
	<div class="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2.5 w-80 -translate-x-1/2">
		<div
			id={sheetId}
			role="tooltip"
			style:opacity={sheet.current}
			style:transform={`translateY(${(1 - sheet.current) * 8}px) scale(${0.96 + sheet.current * 0.04})`}
			class:pointer-events-none={!open}
			class="rounded-xl border border-slate-700 bg-slate-900/95 p-4 text-left shadow-2xl backdrop-blur-xl text-slate-100"
			onpointerenter={requestOpen}
			onpointerleave={requestClose}
		>
			<p class="font-semibold text-white">{citation.book_title}</p>
			<p class="mt-0.5 font-mono text-[11px] text-slate-400">
				{citation.subject} · Standard {citation.standard}
				{#if citation.edition} · {citation.edition}{/if}
			</p>
			{#if citation.section_path.length}
				<p class="mt-2 font-mono text-[11px] leading-relaxed text-cyan-400">
					{citation.section_path.join(' › ')}
				</p>
			{/if}
			<p class="mt-2 border-l-2 border-amber-400 pl-3 text-[13px] leading-relaxed text-slate-200">
				{citation.text}
			</p>
			<p
				class="mt-2.5 inline-flex rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] tracking-wider text-amber-400"
			>
				p. {pageLabel}
			</p>
		</div>
	</div>
</span>
