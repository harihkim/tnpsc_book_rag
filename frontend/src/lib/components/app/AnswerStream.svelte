<!--
  Blueprint #1 — The Fluid Stream Reveal.
  Consumes the answer SSE stream. Provisional deltas arrive as chunks; each chunk is a
  ChunkReveal (svelte/motion Tween) that eases in, so the text flows rather than pops.
  On `answer.completed` the provisional preview is REPLACED by the canonical structured
  blocks (spec §11) — paragraphs & bullet lists with spring-loaded T1/T2 citations and
  aspect-ratio figure placeholders — revealed by a one-shot Tween.
-->
<script lang="ts">
	import { Tween, prefersReducedMotion } from "svelte/motion";
	import type {
		Answer,
		AnswerStreamEvent,
		Block,
		Citation,
		InlineNode,
	} from "$api/v1";
	import { themeState } from "$lib/theme.svelte";
	import ChunkReveal from "./ChunkReveal.svelte";
	import CitationBadge from "./CitationBadge.svelte";
	import FigurePlaceholder from "./FigurePlaceholder.svelte";

	let { stream }: { stream: AsyncGenerator<AnswerStreamEvent> | null } =
		$props();

	let stage = $state<string | null>(null);
	let chunks = $state<string[]>([]);
	let answer = $state<Answer | null>(null);
	let error = $state<string | null>(null);
	let running = $state(false);

	// One-shot reveal for the canonical structured answer.
	const answerReveal = new Tween(0, {
		duration: prefersReducedMotion.current ? 1 : 420,
		easing: (t) => 1 - Math.pow(1 - t, 3),
	});
	$effect(() => {
		if (answer) answerReveal.set(1);
	});

	const STAGE_LABELS: Record<string, string> = {
		retrieval: "Searching your textbooks",
		augmentation: "Assembling cited context",
		generation: "Writing a grounded answer",
		validation: "Checking every citation",
	};

	function handle(ev: AnswerStreamEvent) {
		switch (ev.type) {
			case "started":
				running = true;
				break;
			case "progress":
				stage = STAGE_LABELS[ev.stage] ?? ev.stage;
				break;
			case "delta":
				if (ev.section === "textbook") chunks = [...chunks, ev.content];
				break;
			case "reset":
				chunks = []; // spec §11 — clear all provisional preview text
				break;
			case "completed":
				answer = ev.answer;
				stage = null;
				running = false;
				break;
			case "failed":
				error = ev.detail;
				stage = null;
				running = false;
				break;
		}
	}

	$effect(() => {
		if (!stream) return;
		let active = true;
		(async () => {
			try {
				for await (const ev of stream) {
					if (!active) break;
					handle(ev);
				}
			} catch (e) {
				if (active) {
					error =
						e instanceof Error ? e.message : "stream interrupted";
					running = false;
					stage = null;
				}
			}
		})();
		return () => {
			active = false;
		};
	});

	function citationById(id: string): Citation | undefined {
		return answer?.textbook.citations.find((c) => c.citation_id === id);
	}

	/** All cited figures, deduped, for the placeholder grid. */
	let figures = $derived(
		answer
			? answer.textbook.citations
					.flatMap((c) => c.assets)
					.filter(
						(a, i, arr) =>
							arr.findIndex((x) => x.asset_id === a.asset_id) ===
							i,
					)
			: [],
	);
</script>

{#snippet inline(nodes: InlineNode[])}
	{#each nodes as node}
		{#if node.type === "text"}
			{node.content}
		{:else}
			{@const cite = citationById(node.citation_id)}
			{#if cite}
				<CitationBadge citation={cite} />
			{:else}
				<span class="font-mono text-[11px] opacity-60"
					>{node.fallback_text}</span
				>
			{/if}
		{/if}
	{/each}
{/snippet}

{#snippet blocks(list: Block[])}
	{#each list as block}
		{#if block.type === "paragraph"}
			<p
				class="text-[15px] leading-7 font-normal {themeState.current ===
				'dark'
					? 'text-slate-100'
					: 'text-slate-900'}"
			>
				{@render inline(block.nodes)}
			</p>
		{:else}
			<ul class="space-y-2">
				{#each block.items as item}
					<li
						class="flex gap-2.5 text-[15px] leading-7 font-normal {themeState.current ===
						'dark'
							? 'text-slate-100'
							: 'text-slate-900'}"
					>
						<span
							class="mt-[11px] h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500"
							aria-hidden="true"
						></span>
						<span>{@render inline(item)}</span>
					</li>
				{/each}
			</ul>
		{/if}
	{/each}
{/snippet}

<div class="space-y-4">
	<!-- Live stage indicator -->
	{#if running && stage}
		<div class="flex items-center gap-2.5 font-mono text-xs text-teal">
			<span class="relative flex h-2 w-2">
				<span
					class="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal opacity-60"
				></span>
				<span class="relative inline-flex h-2 w-2 rounded-full bg-teal"
				></span>
			</span>
			<span>{stage}...</span>
		</div>
	{/if}

	<!-- Provisional fluid preview (one Tween-in span per streamed chunk) -->
	{#if !answer && chunks.length}
		<p
			class="text-[15px] leading-7 font-normal {themeState.current ===
			'dark'
				? 'text-slate-100'
				: 'text-slate-900'}"
		>
			{#each chunks as chunk, i (i)}
				<ChunkReveal text={chunk} />
			{/each}
			<span
				class="ml-0.5 inline-block h-4 w-[7px] animate-pulse rounded-sm bg-blue-500 align-middle"
				aria-hidden="true"
			></span>
		</p>
	{/if}

	<!-- Canonical structured answer (replaces the preview) -->
	{#if answer}
		{#if answer.textbook.status === "insufficient_evidence"}
			<div
				class="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-slate-800 dark:text-slate-200"
			>
				{@render blocks(answer.textbook.blocks)}
			</div>
		{:else}
			<div
				style:opacity={answerReveal.current}
				style:translate={`0 ${(1 - answerReveal.current) * 12}px`}
				class="space-y-4"
			>
				{@render blocks(answer.textbook.blocks)}
			</div>

			{#if figures.length}
				<div class="grid gap-3 sm:grid-cols-2">
					{#each figures as asset (asset.asset_id)}
						<FigurePlaceholder {asset} />
					{/each}
				</div>
			{/if}

			{#if answer.supplementary}
				<div
					class="rounded-xl border border-sky-500/30 bg-sky-500/10 p-4"
				>
					<p class="overline mb-2 text-sky-500 font-bold">
						Beyond the textbook · general knowledge
					</p>
					<div class="space-y-3">
						{@render blocks(answer.supplementary.blocks)}
					</div>
				</div>
			{/if}

			<p
				class="answer-footer font-mono text-[10px] tracking-widest text-slate-500 font-medium"
			>
				{answer.textbook.citations.length} citation{answer.textbook
					.citations.length === 1
					? ""
					: "s"} · request
				{answer.request_id.slice(0, 8)}
			</p>
		{/if}
	{/if}

	{#if error}
		<div
			class="rounded-xl border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-500 font-medium"
		>
			{error}
		</div>
	{/if}
</div>
