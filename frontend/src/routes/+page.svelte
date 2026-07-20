<!--
  Landing page — LearnFlow TNPSC Exam Study Assistant.
  GSAP + Lenis orchestrate smooth scroll; Threlte renders the 3D textbook hero.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Lenis from 'lenis';
	import { gsap } from 'gsap';
	import { ScrollTrigger } from 'gsap/ScrollTrigger';
	import { themeState } from '$lib/theme.svelte';
	import { HugeiconsIcon } from '@hugeicons/svelte';
	import { ArrowRight01Icon, BookOpen01Icon, ZapIcon, SparklesIcon, CheckmarkCircle02Icon, Target02Icon, Search01Icon } from '@hugeicons/core-free-icons';

	import HeroBooks from '$components/landing/HeroBooks.svelte';
	import CitationBadge from '$components/app/CitationBadge.svelte';
	import FigurePlaceholder from '$components/app/FigurePlaceholder.svelte';
	import { mockAnswer } from '$api/mocks';
	import type { Block, InlineNode } from '$api/v1';

	const demo = mockAnswer({ query: 'Why does a sharp knife cut more easily?', mode: 'textbook_only' });
	const demoCitations = demo.textbook.citations;
	const demoFigure = demoCitations.flatMap((c) => c.assets)[0];
	const cite = (id: string) => demoCitations.find((c) => c.citation_id === id)!;

	const MARQUEE = [
		'Tamil Nadu State Board Textbooks',
		'TNPSC Group 1, 2 & 4 Syllabus',
		'Standards 6–10 & 11–12',
		'Page-Verified Citations',
		'Active Recall Flashcards',
		'Smart Concept Comparisons',
		'Zero-Hallucination Answers'
	];

	const FEATURES = [
		{
			title: 'Page-Verified Provenance',
			desc: 'Every answer claim links directly to the exact Standard, Chapter, and Page of official Tamil Nadu textbooks so you study authentic facts.',
			icon: CheckmarkCircle02Icon
		},
		{
			title: 'Smart Syllabus Search',
			desc: 'Filter search across Science, Social Science, History, Polity, Geography, and Math by Standard (Std 6 to 10).',
			icon: Search01Icon
		},
		{
			title: 'Active Recall & Practice Cards',
			desc: 'Generate flashcards, practice quizzes, and intuitive analogies instantly from your textbook chapters for retention.',
			icon: SparklesIcon
		},
		{
			title: 'Original Diagram & Figure Evidence',
			desc: 'Inspect original textbook maps, diagrams, and historical timelines right alongside your answer.',
			icon: Target02Icon
		}
	];

	const STEPS = [
		{
			title: '1. Select Your TNPSC Study Sources',
			body: 'Choose official Tamil Nadu State Board textbooks by Standard (Std 6th to 10th) or upload custom PDF syllabus notes.'
		},
		{
			title: '2. Ask Any Syllabus Question',
			body: 'Ask complex exam questions in plain English or Tamil. LearnFlow retrieves the exact relevant textbook passages.'
		},
		{
			title: '3. Verify & Master Concepts',
			body: 'Click inline page badges (1, 2, 3) to view original textbook pages with yellow-highlighted evidence and practice flashcards.'
		}
	];

	onMount(() => {
		gsap.registerPlugin(ScrollTrigger);

		const lenis = new Lenis({ lerp: 0.09 });
		lenis.on('scroll', ScrollTrigger.update);
		const tick = (time: number) => lenis.raf(time * 1000);
		gsap.ticker.add(tick);
		gsap.ticker.lagSmoothing(0);

		gsap.utils.toArray<HTMLElement>('[data-reveal]').forEach((el) => {
			gsap.from(el, {
				opacity: 0,
				y: 40,
				duration: 0.85,
				ease: 'power3.out',
				scrollTrigger: { trigger: el, start: 'top 86%', once: true }
			});
		});

		return () => {
			gsap.ticker.remove(tick);
			lenis.destroy();
			ScrollTrigger.getAll().forEach((st) => st.kill());
		};
	});
</script>

<svelte:head>
	<title>LearnFlow — Smart AI Workspace for TNPSC Exam Preparation</title>
</svelte:head>

{#snippet inline(nodes: InlineNode[])}
	{#each nodes as node}
		{#if node.type === 'text'}
			{node.content}
		{:else}
			<CitationBadge citation={cite(node.citation_id)} />
		{/if}
	{/each}
{/snippet}

{#snippet renderBlocks(blocks: Block[])}
	{#each blocks as block}
		{#if block.type === 'paragraph'}
			<p class="text-[15px] leading-7 {themeState.current === 'dark' ? 'text-slate-200' : 'text-slate-800'}">{@render inline(block.nodes)}</p>
		{:else}
			<ul class="space-y-2">
				{#each block.items as item}
					<li class="flex gap-2.5 text-[15px] leading-7 {themeState.current === 'dark' ? 'text-slate-200' : 'text-slate-800'}">
						<span class="mt-[11px] h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500"></span>
						<span>{@render inline(item)}</span>
					</li>
				{/each}
			</ul>
		{/if}
	{/each}
{/snippet}

<!-- ============================ HERO ============================ -->
<section class="relative -mt-16 min-h-[100svh] overflow-hidden transition-colors duration-300 {themeState.current === 'dark' ? 'bg-[#090D16]' : 'bg-[#F8FAFC]'}">
	<div
		class="absolute inset-0 transition-opacity duration-300 {themeState.current === 'dark'
			? 'bg-[radial-gradient(1200px_700px_at_75%_35%,rgba(37,99,235,0.18)_0%,rgba(15,23,42,0.6)_50%,#090D16_100%)]'
			: 'bg-[radial-gradient(1200px_700px_at_75%_35%,rgba(59,130,246,0.15)_0%,rgba(241,245,249,0.8)_50%,#F8FAFC_100%)]'}"
	></div>
	<HeroBooks />
	<div
		class="pointer-events-none absolute inset-0 transition-colors duration-300 {themeState.current === 'dark'
			? 'bg-gradient-to-r from-[#090D16] via-[#090D16]/70 to-transparent'
			: 'bg-gradient-to-r from-[#F8FAFC] via-[#F8FAFC]/80 to-transparent'}"
	></div>

	<div class="relative z-10 mx-auto flex min-h-[100svh] max-w-6xl items-center px-6 lg:px-10">
		<div class="max-w-xl pb-24 pt-28">
			<div
				class="inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-semibold backdrop-blur-md transition-colors {themeState.current === 'dark'
					? 'border-blue-500/30 bg-blue-500/10 text-blue-400'
					: 'border-blue-300 bg-blue-50 text-blue-600'}"
				data-reveal
			>
				<HugeiconsIcon icon={ZapIcon} size={14} />
				<span>TNPSC Group 1, 2 & 4 Exam Prep</span>
			</div>

			<h1 class="display mt-6 text-[2.75rem] leading-[1.02] sm:text-6xl lg:text-7xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}" data-reveal>
				Master TNPSC.<br />
				Grounded in
				<span class="relative inline-block text-blue-500">
					textbooks.
					<svg class="absolute -bottom-2 left-0 w-full" viewBox="0 0 120 10" fill="none" aria-hidden="true">
						<path d="M2 8C30 3 60 2 118 6" stroke="#3b82f6" stroke-width="3.5" stroke-linecap="round" />
					</svg>
				</span>
			</h1>

			<p class="mt-7 max-w-md text-lg leading-relaxed {themeState.current === 'dark' ? 'text-slate-300' : 'text-slate-600'}" data-reveal>
				LearnFlow turns official Tamil Nadu State Board textbooks into your personal interactive study assistant. Get page-verified answers, concept analogies, practice quizzes, and instant flashcards.
			</p>

			<div class="mt-10 flex flex-wrap items-center gap-4" data-reveal>
				<a href="/app" class="btn-primary">
					Launch Workspace
					<HugeiconsIcon icon={ArrowRight01Icon} size={18} strokeWidth={2.2} />
				</a>
				<a href="#how" class="btn-ghost {themeState.current === 'light' ? 'border-slate-300 text-slate-700 hover:bg-slate-100 hover:border-blue-500' : ''}">How Aspirants Study</a>
			</div>

			<div class="mt-12 flex flex-wrap gap-x-8 gap-y-3 font-mono text-xs {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-500'}" data-reveal>
				<span><b class="font-semibold {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">Std 6–10</b> Textbooks</span>
				<span><b class="font-semibold {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">Page-Exact</b> Citations</span>
				<span><b class="font-semibold {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">100%</b> Grounded</span>
			</div>
		</div>
	</div>

	<a
		href="#features"
		class="absolute bottom-7 left-1/2 z-10 -translate-x-1/2 font-mono text-[10px] tracking-[0.3em] transition-colors {themeState.current === 'dark' ? 'text-slate-400 hover:text-blue-400' : 'text-slate-500 hover:text-blue-600'}"
	>
		EXPLORE ↓
	</a>
</section>

<!-- =========================== MARQUEE ========================== -->
<section class="overflow-hidden border-y bg-blue-600 py-3.5 {themeState.current === 'dark' ? 'border-slate-800/80' : 'border-slate-200'}" aria-hidden="true">
	<div class="animate-marquee flex w-max items-center gap-10 whitespace-nowrap">
		{#each [...MARQUEE, ...MARQUEE] as item}
			<span class="display text-lg font-bold text-white tracking-wide">{item}</span>
			<span class="text-white/60">✦</span>
		{/each}
	</div>
</section>

<!-- ========================= FEATURES GRID ======================= -->
<section id="features" class="mx-auto max-w-6xl scroll-mt-24 px-6 py-28 lg:px-10">
	<p class="overline text-blue-500 font-semibold" data-reveal>Designed for Aspirants</p>
	<h2 class="display mt-4 text-4xl sm:text-5xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}" data-reveal>
		Built for TNPSC Exam Excellence.
	</h2>
	<p class="mt-4 max-w-lg leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}" data-reveal>
		Stop wasting hours guessing where information comes from. LearnFlow provides bulletproof, page-verified evidence directly from your standard Tamil Nadu State Board textbooks.
	</p>

	<div class="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
		{#each FEATURES as feat}
			<div
				data-reveal
				class="group relative rounded-2xl border p-6 transition-all duration-300 hover:-translate-y-1 {themeState.current === 'dark'
					? 'border-slate-800 bg-slate-900/60 hover:border-blue-500/50 hover:bg-slate-900/90'
					: 'border-slate-200 bg-white hover:border-blue-400 hover:shadow-lg shadow-sm'}"
			>
				<div class="mb-5 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600/15 text-blue-500 group-hover:bg-blue-600 group-hover:text-white transition-colors duration-300">
					<HugeiconsIcon icon={feat.icon} size={24} />
				</div>
				<h3 class="font-display text-xl font-bold {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">{feat.title}</h3>
				<p class="mt-3 text-sm leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}">{feat.desc}</p>
			</div>
		{/each}
	</div>
</section>

<!-- ========================= HOW ASPIRANTS STUDY ======================= -->
<section id="how" class="border-t py-28 transition-colors duration-300 {themeState.current === 'dark' ? 'border-slate-800/80 bg-slate-950/60' : 'border-slate-200 bg-slate-100/70'}">
	<div class="mx-auto max-w-6xl px-6 lg:px-10">
		<p class="overline text-blue-500 font-semibold" data-reveal>Study Workflow</p>
		<h2 class="display mt-4 text-4xl sm:text-5xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}" data-reveal>
			How LearnFlow powers your revision.
		</h2>
		<p class="mt-4 max-w-lg leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}" data-reveal>
			From asking textbook concepts to generating practice flashcards in seconds.
		</p>

		<ol class="mt-16">
			{#each STEPS as step, i}
				<li
					data-reveal
					class="group grid gap-5 border-t py-10 transition-colors duration-300 sm:grid-cols-[120px_1fr] sm:gap-8 {themeState.current === 'dark'
						? 'border-slate-800/80 hover:bg-slate-900/40'
						: 'border-slate-300/80 hover:bg-white/60'}"
				>
					<span
						class="display text-5xl leading-none transition-colors duration-300 group-hover:text-blue-500 {themeState.current === 'dark' ? 'text-slate-700' : 'text-slate-300'}"
					>
						{String(i + 1).padStart(2, '0')}
					</span>
					<div>
						<h3 class="display text-2xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">{step.title}</h3>
						<p class="mt-3 max-w-xl leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}">{step.body}</p>
					</div>
				</li>
			{/each}
		</ol>
	</div>
</section>

<!-- ====================== LIVE PROVENANCE DEMO =================== -->
<section id="grounded" class="scroll-mt-24 border-y py-28 transition-colors duration-300 {themeState.current === 'dark' ? 'border-slate-800/80 bg-[#090D16]' : 'border-slate-200 bg-[#F8FAFC]'}">
	<div class="mx-auto max-w-6xl px-6 lg:px-10">
		<p class="overline text-blue-500 font-semibold" data-reveal>Live Evidence Demo</p>
		<h2 class="display mt-4 text-4xl sm:text-5xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}" data-reveal>
			Hover any citation.<br />See the exact page.
		</h2>
		<p class="mt-5 max-w-lg leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}" data-reveal>
			Try out LearnFlow's real interaction — grounded textbook responses where every claim links directly to its source.
		</p>

		<div class="mt-14 grid gap-8 lg:grid-cols-[1fr_360px]">
			<div class="rounded-2xl border p-7 sm:p-9 transition-colors {themeState.current === 'dark' ? 'border-slate-800 bg-slate-900/80' : 'border-slate-200 bg-white shadow-lg text-slate-800'}" data-reveal>
				<p class="mb-6 font-mono text-xs font-bold text-blue-500">
					Q — Why does a sharp knife cut more easily?
				</p>
				<div class="space-y-4">{@render renderBlocks(demo.textbook.blocks)}</div>

				<!-- Analogy callout card demo -->
				<div class="mt-6 rounded-xl border p-4 transition-colors {themeState.current === 'dark' ? 'border-blue-500/30 bg-blue-950/40' : 'border-blue-300 bg-blue-50/80'}">
					<div class="flex items-center gap-2 font-semibold text-blue-500 text-xs">
						<HugeiconsIcon icon={SparklesIcon} size={16} />
						<span>Analogy</span>
					</div>
					<p class="mt-2 text-xs leading-relaxed {themeState.current === 'dark' ? 'text-slate-300' : 'text-slate-700'}">
						Think of it as memorizing one practice sheet instead of understanding the underlying lesson.
					</p>
				</div>

				<p class="mt-6 font-mono text-[10px] tracking-widest {themeState.current === 'dark' ? 'text-slate-500' : 'text-slate-400'}">
					{demoCitations.length} citations · Science — Standard 8
				</p>
			</div>

			<div data-reveal>
				{#if demoFigure}
					<FigurePlaceholder asset={demoFigure} />
				{/if}
				<p class="mt-4 text-xs leading-relaxed {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}">
					Textbook figures reserve their aspect ratio and carry page provenance too — guaranteeing visual accuracy for science and geography diagrams.
				</p>
			</div>
		</div>
	</div>
</section>

<!-- ============================ CTA ============================= -->
<section class="relative overflow-hidden border-t transition-colors duration-300 {themeState.current === 'dark' ? 'border-slate-800/80 bg-[#060911]' : 'border-slate-200 bg-white'}">
	<div
		class="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_420px_at_50%_50%,rgba(37,99,235,0.15),transparent_70%)]"
	></div>
	<div class="relative mx-auto flex max-w-6xl flex-col items-center text-center px-6 py-32 lg:px-10">
		<div class="max-w-2xl" data-reveal>
			<h2 class="display text-4xl leading-[1.05] sm:text-6xl {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">
				Ready to elevate your <span class="text-blue-500">TNPSC prep?</span>
			</h2>
			<p class="mt-6 leading-relaxed {themeState.current === 'dark' ? 'text-slate-300' : 'text-slate-600'}">
				Start querying your Tamil Nadu State Board textbooks with LearnFlow's intelligent workspace today.
			</p>
		</div>
		<a href="/app" class="btn-primary mt-10 px-8 py-4 text-lg" data-reveal>
			Open LearnFlow Workspace
			<HugeiconsIcon icon={ArrowRight01Icon} size={20} strokeWidth={2.2} />
		</a>
	</div>
</section>

