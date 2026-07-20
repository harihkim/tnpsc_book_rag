<!--
  LearnFlow RAG Workspace — 3-Column Interactive Surface (Dark / Light Theme).
  Left: Navigation, "+ Upload source" button, "Your sources" list with PDF thumbnails & indexing status.
  Center: "Ask your sources" thread, LearnFlow grounded answer card with Analogy callout, action toolbar, prompt suggestions, composer.
  Right: "Evidence" panel with citation stepper, document snippet preview with yellow highlighted text, quote callout, citation navigator.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { Tween, prefersReducedMotion } from 'svelte/motion';
	import { HugeiconsIcon } from '@hugeicons/svelte';
	import {
		Search01Icon,
		BookOpen01Icon,
		ZapIcon,
		Add01Icon,
		Upload01Icon,
		Message01Icon,
		Folder01Icon,
		Clock01Icon,
		File01Icon,
		CheckmarkCircle02Icon,
		Settings02Icon,
		Cancel01Icon,
		MoreHorizontalIcon,
		SparklesIcon,
		Copy01Icon,
		BookmarkIcon,
		ThumbsUpIcon,
		ThumbsDownIcon,
		Attachment01Icon,
		SentIcon,
		ArrowLeft01Icon,
		ArrowRight01Icon,
		Share01Icon,
		Sun01Icon,
		Moon01Icon,
		SidebarLeftIcon
	} from '@hugeicons/core-free-icons';

	import AnswerStream from '$components/app/AnswerStream.svelte';
	import UploadModal from '$components/app/UploadModal.svelte';
	import { getBooks, getCatalogFilters, search, streamAnswer, useLiveApi } from '$api/client';
	import type {
		AnswerMode,
		AnswerStreamEvent,
		Book,
		CatalogFilters,
		ResponseLength,
		SearchResult,
		Standard
	} from '$api/v1';

	/* --- Preset Sources matching reference images --- */
	const PRESET_SOURCES = [
		{
			id: 'src-1',
			title: 'Introduction to Machine Learning',
			meta: 'PDF · 712 pages',
			status: 'ready' as const,
			coverBg: 'from-blue-600 to-indigo-900',
			subject: 'Science',
			standard: 8
		},
		{
			id: 'src-2',
			title: 'Deep Learning Notes',
			meta: 'PDF · 248 pages',
			status: 'ready' as const,
			coverBg: 'from-teal-600 to-emerald-900',
			subject: 'Mathematics',
			standard: 9
		},
		{
			id: 'src-3',
			title: 'Probability Essentials',
			meta: 'PDF · 320 pages',
			status: 'ready' as const,
			coverBg: 'from-blue-500 to-cyan-800',
			subject: 'Mathematics',
			standard: 9
		},
		{
			id: 'src-4',
			title: 'Linear Algebra Primer',
			meta: 'PDF · 154 pages',
			status: 'indexing' as const,
			progress: 72,
			coverBg: 'from-amber-600 to-orange-950',
			subject: 'Mathematics',
			standard: 10
		},
		{
			id: 'src-5',
			title: 'Research Methods Handbook',
			meta: 'PDF · 532 pages',
			status: 'ready' as const,
			coverBg: 'from-sky-700 to-slate-900',
			subject: 'Social Science',
			standard: 10
		}
	];

	/* --- Quick Prompt Suggestion Chips --- */
	const PROMPT_CHIPS = [
		{ label: 'Explain with an example', icon: SparklesIcon, query: 'Explain overfitting with a practical real-world example.' },
		{ label: 'Compare bias and variance', icon: BookOpen01Icon, query: 'What is the trade-off between bias and variance in machine learning models?' },
		{ label: 'Create flashcards', icon: File01Icon, query: 'Create 3 quick review flashcards on regularization techniques.' },
		{ label: 'Quiz me', icon: CheckmarkCircle02Icon, query: 'Quiz me with 2 multiple choice questions on model generalization.' }
	];

	/* --- Mock Citations list for Evidence panel matching reference images --- */
	const MOCK_CITATIONS = [
		{
			id: 1,
			title: 'Model generalization',
			page: 84,
			bookTitle: 'Introduction to Machine Learning',
			chapter: 'Chapter 4',
			snippet: 'Generalization refers to a model’s ability to perform well on previously unseen data rather than just the training dataset.',
			quote: 'A model generalizes well when it captures true underlying relationships instead of fitting noise.'
		},
		{
			id: 2,
			title: 'Overfitting and variance',
			page: 87,
			bookTitle: 'Introduction to Machine Learning',
			chapter: 'Chapter 4',
			snippet: 'When a model is too complex, it may learn fluctuations in the training data that do not represent the underlying relationship. A model can fit training examples extremely well while failing to generalize when it captures noise or patterns specific to the training set.',
			quote: 'A model can fit training examples extremely well while failing to generalize when it captures noise or patterns specific to the training set.'
		},
		{
			id: 3,
			title: 'Regularization techniques',
			page: 91,
			bookTitle: 'Introduction to Machine Learning',
			chapter: 'Chapter 4',
			snippet: 'L1 and L2 regularization penalize large weights, constraining model complexity and mitigating high variance.',
			quote: 'Regularization techniques constrain model capacity to force simpler, robust representations.'
		}
	];

	import { themeState } from '$lib/theme.svelte';

	/* --- State --- */
	let theme = $derived(themeState.current); // Sync with global ThemeState (Dark Image 1 / Light Image 2)
	let sidebarOpen = $state(true);
	let evidencePanelOpen = $state(true);
	let activeTab = $state<'ask' | 'library' | 'notes' | 'collections' | 'history'>('ask');
	let evidenceTab = $state<'evidence' | 'notes' | 'outline'>('evidence');
	let uploadModalOpen = $state(false);

	let books = $state<Book[]>([]);
	let selectedSourceIds = $state<Set<string>>(new Set(['src-1', 'src-2', 'src-3']));
	let askQuery = $state('Why does overfitting happen, and how can we reduce it?');
	let submittedQuery = $state('Why does overfitting happen, and how can we reduce it?');
	let mode = $state<AnswerMode>('textbook_only');
	let responseLength = $state<ResponseLength>('medium');

	let answerStream = $state<AsyncGenerator<AnswerStreamEvent> | null>(null);
	let evidence = $state<SearchResult[] | null>(null);
	let loading = $state(false);
	let abController = $state<AbortController | null>(null);
	let activeCitationIndex = $state(1); // 0-indexed (Citation 2 of 3 is index 1)

	// Feedback & Copy state
	let liked = $state<boolean | null>(null);
	let savedNote = $state(false);
	let copiedAnswer = $state(false);
	let copiedExcerpt = $state(false);

	async function copyToClipboard(text: string, target: 'answer' | 'excerpt') {
		try {
			if (navigator?.clipboard?.writeText) {
				await navigator.clipboard.writeText(text);
			} else {
				const ta = document.createElement('textarea');
				ta.value = text;
				document.body.appendChild(ta);
				ta.select();
				document.execCommand('copy');
				document.body.removeChild(ta);
			}
			if (target === 'answer') {
				copiedAnswer = true;
				setTimeout(() => (copiedAnswer = false), 2000);
			} else {
				copiedExcerpt = true;
				setTimeout(() => (copiedExcerpt = false), 2000);
			}
		} catch (e) {
			console.error('Copy failed:', e);
		}
	}

	async function copyAnswerResponseText() {
		const card = document.getElementById('answer-response-text');
		let cleanText = '';
		if (card) {
			const clone = card.cloneNode(true) as HTMLElement;
			// Strip out tooltip sheets, figure placeholders, citation footers, and toolbars
			clone.querySelectorAll('[role="tooltip"], figure, .answer-footer, .action-toolbar').forEach((el) => el.remove());
			cleanText = clone.innerText.trim().replace(/\n{3,}/g, '\n\n');
		}
		if (!cleanText) {
			cleanText = 'Overfitting happens when a model learns training data too closely, including noise and accidental patterns...';
		}
		await copyToClipboard(cleanText, 'answer');
	}

	/* --- Derived --- */
	let selectedCitation = $derived(MOCK_CITATIONS[activeCitationIndex] ?? MOCK_CITATIONS[1]);

	function toggleSource(id: string) {
		const next = new Set(selectedSourceIds);
		if (next.has(id)) {
			if (next.size > 1) next.delete(id);
		} else {
			next.add(id);
		}
		selectedSourceIds = next;
	}

	async function submit(q: string) {
		const trimmed = q.trim();
		if (!trimmed) return;
		submittedQuery = trimmed;
		askQuery = trimmed;
		answerStream = null;
		evidence = null;
		liked = null;
		savedNote = false;

		abController?.abort();
		const ac = new AbortController();
		abController = ac;

		answerStream = streamAnswer(
			{ query: trimmed, mode, response_length: responseLength, filters: { standards: [], subjects: [], book_ids: [] } },
			ac.signal
		);

		if (!loading) loading = true;
		try {
			const sr = await search({ query: trimmed, top_k: 5 });
			if (!ac.signal.aborted) {
				evidence = sr.results;
			}
		} catch {
			// non-fatal
		} finally {
			if (!ac.signal.aborted) loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit(askQuery);
		}
	}

	onMount(() => {
		getBooks().then((res) => {
			if (res && res.items.length) books = res.items;
		});
		// auto trigger initial demo query streaming if desired
		submit(askQuery);
	});
</script>

<svelte:head>
	<title>LearnFlow — Ask Your Sources</title>
</svelte:head>

<!-- Outer Container handling Theme Switch (Dark Image 1 / Light Image 2) -->
<div
	class="h-screen w-screen flex overflow-hidden font-body transition-colors duration-300 {theme === 'dark'
		? 'bg-[#0B0F19] text-slate-100'
		: 'bg-[#F8FAFC] text-slate-800'}"
>
	<!-- ========================================================================= -->
	<!-- 1. LEFT SIDEBAR: Navigation & Sources                                      -->
	<!-- ========================================================================= -->
	<aside
		class="relative flex flex-col border-r transition-all duration-300 shrink-0 {sidebarOpen
			? 'w-64'
			: 'w-16'} {theme === 'dark'
			? 'bg-[#0F172A]/70 border-slate-800/80'
			: 'bg-white border-slate-200'}"
	>
		<!-- Sidebar Header: Logo + Collapse Button -->
		<div class="flex h-16 items-center justify-between px-4 border-b {theme === 'dark' ? 'border-slate-800/80' : 'border-slate-200'}">
			{#if sidebarOpen}
				<a href="/" class="flex items-center gap-2.5">
					<div class="grid h-8 w-8 place-items-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-600/30">
						<HugeiconsIcon icon={ZapIcon} size={18} strokeWidth={2.5} />
					</div>
					<span class="font-display text-lg font-bold tracking-tight {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
						Learn<span class="text-blue-500">Flow</span>
					</span>
				</a>
			{:else}
				<div class="mx-auto grid h-8 w-8 place-items-center rounded-xl bg-blue-600 text-white">
					<HugeiconsIcon icon={ZapIcon} size={18} strokeWidth={2.5} />
				</div>
			{/if}

			<button
				type="button"
				class="rounded-lg p-1.5 transition-colors {theme === 'dark'
					? 'text-slate-400 hover:bg-slate-800 hover:text-white'
					: 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'}"
				onclick={() => (sidebarOpen = !sidebarOpen)}
				title="Toggle sidebar"
			>
				<HugeiconsIcon icon={SidebarLeftIcon} size={18} />
			</button>
		</div>

		<!-- Upload Source Action Button -->
		<div class="p-3">
			<button
				type="button"
				class="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-2.5 font-semibold text-white shadow-md shadow-blue-600/25 transition-all hover:bg-blue-500 hover:shadow-lg hover:shadow-blue-600/40 active:scale-[0.98] {sidebarOpen
					? 'px-4 text-sm'
					: 'px-2 text-xs'}"
				onclick={() => (uploadModalOpen = true)}
			>
				<HugeiconsIcon icon={Upload01Icon} size={18} strokeWidth={2.2} />
				{#if sidebarOpen}
					<span>Upload source</span>
				{/if}
			</button>
		</div>

		<!-- Navigation Menu Links -->
		<nav class="space-y-1 px-3 py-2">
			{#each [{ id: 'ask', label: 'Ask', icon: Message01Icon }, { id: 'library', label: 'Library', icon: BookOpen01Icon }, { id: 'notes', label: 'Notes', icon: File01Icon }, { id: 'collections', label: 'Collections', icon: Folder01Icon }, { id: 'history', label: 'History', icon: Clock01Icon }] as item}
				<button
					type="button"
					class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors {activeTab === item.id
						? theme === 'dark'
							? 'bg-blue-600/15 text-blue-400'
							: 'bg-blue-50 text-blue-600 font-semibold'
						: theme === 'dark'
							? 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
							: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}"
					onclick={() => (activeTab = item.id as any)}
				>
					<HugeiconsIcon icon={item.icon} size={18} />
					{#if sidebarOpen}
						<span>{item.label}</span>
					{/if}
				</button>
			{/each}
		</nav>

		<!-- "Your sources" List Section -->
		{#if sidebarOpen}
			<div class="mt-4 flex-1 overflow-y-auto px-3">
				<div class="flex items-center justify-between py-2 px-1">
					<span class="text-xs font-semibold uppercase tracking-wider {theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}">
						Your sources
					</span>
					<button
						type="button"
						class="rounded-lg p-1 text-slate-400 hover:text-blue-500 transition-colors"
						onclick={() => (uploadModalOpen = true)}
					>
						<HugeiconsIcon icon={Add01Icon} size={16} />
					</button>
				</div>

				<div class="space-y-1.5 mt-1">
					{#each PRESET_SOURCES as src (src.id)}
						{@const isSelected = selectedSourceIds.has(src.id)}
						<button
							type="button"
							class="group flex w-full items-center gap-3 rounded-xl p-2 text-left transition-all border {isSelected
								? theme === 'dark'
									? 'bg-blue-600/10 border-blue-500/40 ring-1 ring-blue-500/30'
									: 'bg-blue-50/80 border-blue-300 ring-1 ring-blue-400/20'
								: theme === 'dark'
									? 'border-transparent hover:bg-slate-800/40'
									: 'border-transparent hover:bg-slate-100'}"
							onclick={() => toggleSource(src.id)}
						>
							<!-- PDF Cover Thumbnail Image Preview -->
							<div class="relative grid h-10 w-8 shrink-0 place-items-center rounded-md bg-gradient-to-br {src.coverBg} text-white shadow-sm font-mono text-[9px] font-bold tracking-tighter">
								PDF
							</div>
							<div class="min-w-0 flex-1">
								<p class="truncate text-xs font-medium {isSelected ? (theme === 'dark' ? 'text-blue-400 font-semibold' : 'text-blue-700 font-semibold') : (theme === 'dark' ? 'text-slate-200' : 'text-slate-700')}">
									{src.title}
								</p>
								<div class="mt-0.5 flex items-center justify-between text-[11px] {theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}">
									<span>{src.meta}</span>
									{#if src.status === 'ready'}
										<HugeiconsIcon icon={CheckmarkCircle02Icon} size={14} class="text-emerald-500 shrink-0" />
									{:else}
										<span class="text-[10px] text-amber-500 font-mono font-medium">Indexing · {src.progress}%</span>
									{/if}
								</div>
							</div>
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- User Profile Footer -->
		<div class="mt-auto border-t p-3 {theme === 'dark' ? 'border-slate-800/80' : 'border-slate-200'}">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-2.5">
					<div class="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-tr from-amber-500 to-orange-500 text-xs font-bold text-slate-950">
						AS
					</div>
					{#if sidebarOpen}
						<div class="min-w-0">
							<p class="truncate text-xs font-semibold {theme === 'dark' ? 'text-slate-200' : 'text-slate-800'}">Aarav Sharma</p>
							<p class="text-[10px] text-slate-400">Free plan</p>
						</div>
					{/if}
				</div>
				{#if sidebarOpen}
					<button
						type="button"
						class="rounded-lg p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
					>
						<HugeiconsIcon icon={Settings02Icon} size={16} />
					</button>
				{/if}
			</div>
		</div>
	</aside>

	<!-- ========================================================================= -->
	<!-- 2. CENTER PANEL: Ask your sources (Chat & Prompt Composer)                -->
	<!-- ========================================================================= -->
	<main class="flex flex-1 flex-col overflow-hidden">
		<!-- Top Bar: Title & Conversation Actions -->
		<header class="flex h-16 items-center justify-between px-6 border-b shrink-0 {theme === 'dark' ? 'border-slate-800/80 bg-[#0F172A]/40' : 'border-slate-200 bg-white/80'}">
			<div>
				<h1 class="font-display text-lg font-bold {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
					Ask your sources
				</h1>
				<p class="text-xs text-slate-400">Get answers grounded in your uploaded materials.</p>
			</div>

			<div class="flex items-center gap-3">
				<!-- Theme Switcher Button -->
				<button
					type="button"
					class="flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors {theme === 'dark'
						? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
						: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
					onclick={() => themeState.toggle()}
					title="Switch Dark/Light Theme"
				>
					{#if theme === 'dark'}
						<HugeiconsIcon icon={Sun01Icon} size={14} class="text-amber-400" />
						<span>Light mode</span>
					{:else}
						<HugeiconsIcon icon={Moon01Icon} size={14} class="text-indigo-600" />
						<span>Dark mode</span>
					{/if}
				</button>

				<button
					type="button"
					class="flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-colors {evidencePanelOpen
						? theme === 'dark'
							? 'border-blue-500/40 bg-blue-600/10 text-blue-400'
							: 'border-blue-300 bg-blue-50 text-blue-600'
						: theme === 'dark'
							? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
							: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
					onclick={() => (evidencePanelOpen = !evidencePanelOpen)}
					title="Toggle Evidence & Notes Panel"
				>
					<HugeiconsIcon icon={BookOpen01Icon} size={14} />
					<span>{evidencePanelOpen ? 'Hide Evidence' : 'Show Evidence'}</span>
				</button>

				<button
					type="button"
					class="flex items-center gap-1.5 rounded-xl border border-blue-500/30 bg-blue-600/10 px-3 py-1.5 text-xs font-semibold text-blue-500 hover:bg-blue-600/20 transition-colors"
					onclick={() => submit('What are the core principles of model regularization?')}
				>
					<HugeiconsIcon icon={Add01Icon} size={14} />
					<span>New conversation</span>
				</button>

				<button type="button" class="rounded-lg p-1.5 text-slate-400 hover:text-slate-200">
					<HugeiconsIcon icon={MoreHorizontalIcon} size={18} />
				</button>
			</div>
		</header>

		<!-- Active Source Chips Filter Bar -->
		<div class="flex flex-wrap items-center gap-2 px-6 py-3 border-b text-xs shrink-0 {theme === 'dark' ? 'border-slate-800/60 bg-[#0F172A]/20' : 'border-slate-200 bg-slate-50'}">
			{#each PRESET_SOURCES.filter((s) => selectedSourceIds.has(s.id)) as src}
				<span
					class="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-medium transition-all {theme === 'dark'
						? 'border-slate-700 bg-slate-800/80 text-slate-200'
						: 'border-slate-300 bg-white text-slate-700 shadow-sm'}"
				>
					<span>{src.title}</span>
					<button
						type="button"
						class="text-slate-400 hover:text-rose-400"
						onclick={() => toggleSource(src.id)}
					>
						<HugeiconsIcon icon={Cancel01Icon} size={12} />
					</button>
				</span>
			{/each}

			<button
				type="button"
				class="text-xs font-medium text-amber-500 hover:underline ml-auto"
				onclick={() => (uploadModalOpen = true)}
			>
				Manage sources
			</button>
		</div>

		<!-- Conversation Message Stream Area -->
		<div class="flex-1 overflow-y-auto px-6 py-6 space-y-6">
			<!-- User Question Bubble (Right Aligned) -->
			<div class="flex justify-end">
				<div class="max-w-xl rounded-2xl rounded-tr-sm bg-blue-600 px-5 py-3.5 text-sm font-medium text-white shadow-md shadow-blue-600/20">
					<p>{submittedQuery}</p>
					<div class="mt-1 flex items-center justify-end gap-1 text-[10px] text-blue-200">
						<span>10:24 AM</span>
						<span>✓✓</span>
					</div>
				</div>
			</div>

			<!-- LearnFlow Grounded Answer Card -->
			<div class="flex items-start gap-4">
				<div class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-400 text-white shadow-md shadow-blue-500/25">
					<HugeiconsIcon icon={ZapIcon} size={20} strokeWidth={2.5} />
				</div>

				<div class="flex-1 space-y-4 max-w-3xl">
					<!-- Answer Card Header -->
					<div class="flex items-center gap-3">
						<span class="font-display font-bold text-sm {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
							LearnFlow
						</span>
						<span class="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-blue-400">
							Grounded in {selectedSourceIds.size} sources ▾
						</span>
					</div>

					<!-- Formatted Stream Answer Content -->
					<div id="answer-response-text" class="rounded-2xl border p-6 space-y-4 text-sm leading-relaxed {theme === 'dark' ? 'border-slate-800 bg-[#0F172A]/50 text-slate-200' : 'border-slate-200 bg-white text-slate-800 shadow-sm'}">
						{#if answerStream}
							<AnswerStream stream={answerStream} />
						{:else}
							<!-- Static Answer View with structured formatting and citations -->
							<div class="space-y-4">
								<div>
									<h3 class="font-bold text-base mb-1 {theme === 'dark' ? 'text-white' : 'text-slate-900'}">Overfitting in simple terms</h3>
									<p>
										Overfitting happens when a model learns the training data too closely, including noise and accidental patterns that do not carry over to new data.
										<button
											type="button"
											class="ml-1 inline-flex items-center justify-center h-4 w-4 rounded-full bg-blue-600 text-white text-[10px] font-bold hover:scale-110 transition-transform"
											onclick={() => {
												activeCitationIndex = 0;
												evidencePanelOpen = true;
											}}
										>
											1
										</button>
									</p>
								</div>

								<div>
									<h4 class="font-bold text-sm mb-1 {theme === 'dark' ? 'text-white' : 'text-slate-900'}">Why it happens</h4>
									<p>
										An overly complex model may memorize the training examples instead of learning general patterns that generalize well.
										<button
											type="button"
											class="ml-1 inline-flex items-center justify-center h-4 w-4 rounded-full bg-blue-600 text-white text-[10px] font-bold hover:scale-110 transition-transform"
											onclick={() => {
												activeCitationIndex = 1;
												evidencePanelOpen = true;
											}}
										>
											2
										</button>
									</p>
								</div>

								<div>
									<h4 class="font-bold text-sm mb-1 {theme === 'dark' ? 'text-white' : 'text-slate-900'}">What it looks like</h4>
									<p>
										Training performance keeps improving, but validation or test performance stops improving or gets worse.
										<button
											type="button"
											class="ml-1 inline-flex items-center justify-center h-4 w-4 rounded-full bg-blue-600 text-white text-[10px] font-bold hover:scale-110 transition-transform"
											onclick={() => {
												activeCitationIndex = 1;
												evidencePanelOpen = true;
											}}
										>
											2
										</button>
									</p>
								</div>

								<div>
									<h4 class="font-bold text-sm mb-1 {theme === 'dark' ? 'text-white' : 'text-slate-900'}">How to reduce it</h4>
									<ul class="list-disc pl-5 space-y-1">
										<li>Collect or augment more training data</li>
										<li>Simplify the model architecture</li>
										<li>Apply regularization (L1, L2)</li>
										<li>Use dropout where appropriate</li>
										<li>Track validation performance</li>
										<li>
											Use early stopping
											<button
												type="button"
												class="ml-1 inline-flex items-center justify-center h-4 w-4 rounded-full bg-blue-600 text-white text-[10px] font-bold hover:scale-110 transition-transform"
												onclick={() => {
													activeCitationIndex = 2;
													evidencePanelOpen = true;
												}}
											>
												3
											</button>
										</li>
									</ul>
								</div>

								<!-- Analogy Callout Card matching reference image 1 & 2 -->
								<div class="mt-4 rounded-xl border p-4 flex items-start gap-3.5 {theme === 'dark' ? 'border-teal-500/30 bg-teal-950/30' : 'border-teal-300 bg-teal-50/60'}">
									<div class="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-teal-500/20 text-teal-400">
										<HugeiconsIcon icon={SparklesIcon} size={18} />
									</div>
									<div>
										<h5 class="font-bold text-xs text-teal-400 uppercase tracking-wider mb-1">Analogy</h5>
										<p class="text-xs leading-relaxed {theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}">
											Think of it as memorizing one practice sheet instead of understanding the underlying lesson.
										</p>
									</div>
								</div>
							</div>
						{/if}

						<!-- Response Action Toolbar (Copy, Save to notes, Helpful, Not helpful) -->
						<div class="action-toolbar flex items-center gap-4 pt-3 border-t text-xs {theme === 'dark' ? 'border-slate-800 text-slate-400' : 'border-slate-200 text-slate-600'}">
							<button
								type="button"
								class="flex items-center gap-1.5 transition-colors {copiedAnswer ? 'text-emerald-500 font-semibold' : 'hover:text-blue-500'}"
								onclick={copyAnswerResponseText}
							>
								<HugeiconsIcon icon={copiedAnswer ? CheckmarkCircle02Icon : Copy01Icon} size={14} />
								<span>{copiedAnswer ? 'Copied!' : 'Copy'}</span>
							</button>

							<button
								type="button"
								class="flex items-center gap-1.5 hover:text-blue-500 transition-colors {savedNote ? 'text-emerald-500 font-semibold' : ''}"
								onclick={() => (savedNote = !savedNote)}
							>
								<HugeiconsIcon icon={BookmarkIcon} size={14} />
								<span>{savedNote ? 'Saved to notes' : 'Save to notes'}</span>
							</button>

							<div class="ml-auto flex items-center gap-2">
								<button
									type="button"
									class="p-1 rounded hover:text-emerald-400 transition-colors {liked === true ? 'text-emerald-400' : ''}"
									onclick={() => (liked = true)}
									title="Helpful"
								>
									<HugeiconsIcon icon={ThumbsUpIcon} size={14} />
								</button>
								<button
									type="button"
									class="p-1 rounded hover:text-rose-400 transition-colors {liked === false ? 'text-rose-400' : ''}"
									onclick={() => (liked = false)}
									title="Not helpful"
								>
									<HugeiconsIcon icon={ThumbsDownIcon} size={14} />
								</button>
							</div>
						</div>
					</div>

					<!-- Quick Action Prompt Suggestion Chips -->
					<div class="flex flex-wrap items-center gap-2 pt-2">
						{#each PROMPT_CHIPS as chip}
							<button
								type="button"
								class="flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all hover:scale-105 active:scale-95 {theme === 'dark'
									? 'border-slate-700 bg-slate-800/80 text-slate-300 hover:border-blue-500/50 hover:bg-blue-600/10 hover:text-blue-400'
									: 'border-slate-300 bg-white text-slate-700 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600 shadow-sm'}"
								onclick={() => submit(chip.query)}
							>
								<HugeiconsIcon icon={chip.icon} size={14} class="text-blue-500" />
								<span>{chip.label}</span>
							</button>
						{/each}
					</div>
				</div>
			</div>
		</div>

		<!-- Input Composer Box (Fixed at Bottom) -->
		<div class="p-6 border-t shrink-0 {theme === 'dark' ? 'border-slate-800/80 bg-[#0B0F19]' : 'border-slate-200 bg-[#F8FAFC]'}">
			<div class="mx-auto max-w-3xl rounded-2xl border p-3 shadow-lg transition-all focus-within:border-blue-500/70 focus-within:ring-2 focus-within:ring-blue-500/20 {theme === 'dark' ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'}">
				<textarea
					rows="2"
					placeholder="Ask something from your sources..."
					bind:value={askQuery}
					onkeydown={handleKeydown}
					class="w-full bg-transparent px-2 text-sm resize-none focus:outline-none {theme === 'dark' ? 'text-white placeholder:text-slate-500' : 'text-slate-900 placeholder:text-slate-400'}"
				></textarea>

				<!-- Composer Bottom Toolbar -->
				<div class="flex items-center justify-between pt-2">
					<div class="flex items-center gap-2">
						<button
							type="button"
							class="rounded-lg p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
							title="Attach file"
						>
							<HugeiconsIcon icon={Attachment01Icon} size={18} />
						</button>

						<button
							type="button"
							class="flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-semibold transition-colors {theme === 'dark'
								? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
								: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
							onclick={() => (uploadModalOpen = true)}
						>
							<HugeiconsIcon icon={Add01Icon} size={14} />
							<span>Add source</span>
						</button>

						<select
							bind:value={mode}
							class="rounded-lg border px-2.5 py-1 text-xs font-semibold focus:outline-none {theme === 'dark'
								? 'border-slate-700 bg-slate-800 text-slate-300'
								: 'border-slate-300 bg-slate-100 text-slate-700'}"
						>
							<option value="textbook_only">Ask (Textbook only)</option>
							<option value="textbook_plus_general">Ask (+ General Knowledge)</option>
						</select>
					</div>

					<button
						type="button"
						class="grid h-9 w-9 place-items-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-600/30 transition-all hover:bg-blue-500 hover:scale-105 active:scale-95"
						onclick={() => submit(askQuery)}
						title="Send question"
					>
						<HugeiconsIcon icon={SentIcon} size={18} />
					</button>
				</div>
			</div>

			<p class="mt-2 text-center text-[11px] text-slate-400">
				ⓘ Answers may be incomplete. Verify important details using the cited passages.
			</p>
		</div>
	</main>

	<!-- ========================================================================= -->
	<!-- 3. RIGHT SIDEBAR: Evidence & Passage Inspection Panel                     -->
	<!-- ========================================================================= -->
	{#if evidencePanelOpen}
		<aside
			class="relative flex w-80 flex-col border-l transition-all duration-300 shrink-0 {theme === 'dark'
				? 'bg-[#0F172A]/70 border-slate-800/80'
				: 'bg-white border-slate-200'}"
		>
			<!-- Evidence Header -->
			<div class="flex h-16 items-center justify-between px-5 border-b {theme === 'dark' ? 'border-slate-800/80' : 'border-slate-200'}">
				<h2 class="font-display text-base font-bold {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
					Evidence
				</h2>
				<button
					type="button"
					class="rounded-lg p-1 text-slate-400 hover:text-slate-200 transition-colors"
					onclick={() => (evidencePanelOpen = false)}
				>
					<HugeiconsIcon icon={Cancel01Icon} size={18} />
				</button>
			</div>

			<!-- Tab Navigation: Evidence / Notes / Outline -->
			<div class="flex border-b text-xs font-semibold {theme === 'dark' ? 'border-slate-800/80' : 'border-slate-200'}">
				{#each [{ id: 'evidence', label: 'Evidence' }, { id: 'notes', label: 'Notes' }, { id: 'outline', label: 'Outline' }] as tab}
					<button
						type="button"
						class="flex-1 py-2.5 text-center transition-colors border-b-2 {evidenceTab === tab.id
							? 'border-blue-500 text-blue-500'
							: 'border-transparent text-slate-400 hover:text-slate-200'}"
						onclick={() => (evidenceTab = tab.id as any)}
					>
						{tab.label}
					</button>
				{/each}
			</div>

			<!-- Evidence Content View -->
			<div class="flex-1 overflow-y-auto p-5 space-y-5">
				<!-- Citation Stepper Header -->
				<div class="flex items-center justify-between text-xs text-slate-400 font-medium">
					<span>Citation {activeCitationIndex + 1} of {MOCK_CITATIONS.length}</span>
					<div class="flex items-center gap-1">
						<button
							type="button"
							disabled={activeCitationIndex === 0}
							class="rounded p-1 hover:bg-slate-800 hover:text-white disabled:opacity-30"
							onclick={() => (activeCitationIndex = Math.max(0, activeCitationIndex - 1))}
						>
							<HugeiconsIcon icon={ArrowLeft01Icon} size={14} />
						</button>
						<button
							type="button"
							disabled={activeCitationIndex === MOCK_CITATIONS.length - 1}
							class="rounded p-1 hover:bg-slate-800 hover:text-white disabled:opacity-30"
							onclick={() => (activeCitationIndex = Math.min(MOCK_CITATIONS.length - 1, activeCitationIndex + 1))}
						>
							<HugeiconsIcon icon={ArrowRight01Icon} size={14} />
						</button>
					</div>
				</div>

				<!-- Document Source Info -->
				<div>
					<h3 class="font-bold text-sm {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
						{selectedCitation.bookTitle}
					</h3>
					<div class="mt-1 flex items-center justify-between text-xs text-slate-400">
						<span>{selectedCitation.chapter} · Page {selectedCitation.page}</span>
						<button type="button" class="flex items-center gap-1 text-blue-500 hover:underline">
							<span>Open document</span>
							<HugeiconsIcon icon={Share01Icon} size={12} />
						</button>
					</div>
				</div>

				<!-- Interactive Textbook Page Preview Card -->
				<div class="rounded-xl border p-4 text-xs leading-relaxed space-y-3 font-serif shadow-inner {theme === 'dark' ? 'border-slate-800 bg-[#090D16] text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-800'}">
					<div class="font-sans text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b pb-1 border-slate-800">
						4.2 Overfitting and Variance
					</div>
					<p>
						When a model is too complex, it may learn fluctuations in the training data that do not represent the underlying relationship.
					</p>
					<p class="textbook-highlight font-sans text-xs">
						{selectedCitation.snippet}
					</p>
					<p>
						This leads to high performance on the training data but poor performance on new, unseen data.
					</p>
					<div class="text-right text-[10px] font-mono text-slate-500 pt-2 border-t border-slate-800/40">
						{selectedCitation.page}
					</div>
				</div>

				<!-- Quoted Evidence Callout Card -->
				<div class="rounded-xl border p-4 text-xs leading-relaxed relative {theme === 'dark' ? 'border-amber-500/30 bg-amber-950/20 text-amber-200/90' : 'border-amber-300 bg-amber-50 text-amber-900'}">
					<span class="absolute -top-2 left-3 text-amber-500 text-lg font-bold">“</span>
					<p class="pt-1 italic">
						{selectedCitation.quote}
					</p>
				</div>

				<!-- Action Buttons -->
				<div class="flex flex-wrap gap-2 text-xs">
					<button
						type="button"
						class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-medium transition-colors {copiedExcerpt ? 'border-emerald-500 bg-emerald-500/10 text-emerald-500 font-semibold' : theme === 'dark' ? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700' : 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
						onclick={() => copyToClipboard(selectedCitation.quote, 'excerpt')}
					>
						<HugeiconsIcon icon={copiedExcerpt ? CheckmarkCircle02Icon : Copy01Icon} size={14} />
						<span>{copiedExcerpt ? 'Copied!' : 'Copy excerpt'}</span>
					</button>

					<button
						type="button"
						class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-medium transition-colors {theme === 'dark' ? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700' : 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
					>
						<HugeiconsIcon icon={BookmarkIcon} size={14} />
						<span>Save highlight</span>
					</button>
				</div>

				<!-- Numbered Citations List Navigator -->
				<div class="pt-3 border-t border-slate-800 space-y-2">
					<span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">All Citations</span>
					<div class="space-y-1.5">
						{#each MOCK_CITATIONS as c, idx}
							<button
								type="button"
								class="flex w-full items-center justify-between rounded-xl p-2.5 text-xs text-left transition-all border {activeCitationIndex === idx
									? 'border-blue-500/50 bg-blue-600/15 text-blue-400 font-semibold'
									: theme === 'dark'
										? 'border-transparent text-slate-400 hover:bg-slate-800/40 hover:text-slate-200'
										: 'border-transparent text-slate-600 hover:bg-slate-100'}"
								onclick={() => (activeCitationIndex = idx)}
							>
								<div class="flex items-center gap-2.5">
									<span class="grid h-5 w-5 place-items-center rounded-md bg-blue-600 text-white font-bold text-[10px]">
										{c.id}
									</span>
									<span class="truncate max-w-[140px]">{c.title}</span>
								</div>
								<span class="font-mono text-[10px] text-slate-400">Page {c.page}</span>
							</button>
						{/each}
					</div>
				</div>
			</div>
		</aside>
	{:else}
		<!-- Floating handle to easily reopen Evidence Panel when closed -->
		<button
			type="button"
			class="fixed right-3 top-20 z-30 flex items-center gap-2 rounded-full border shadow-xl px-3.5 py-2 text-xs font-semibold backdrop-blur-md transition-all hover:scale-105 {theme === 'dark'
				? 'border-blue-500/40 bg-slate-900/95 text-blue-400 hover:bg-slate-800'
				: 'border-blue-300 bg-white/95 text-blue-600 hover:bg-blue-50 shadow-blue-500/10'}"
			onclick={() => (evidencePanelOpen = true)}
			title="Open Evidence Panel"
		>
			<HugeiconsIcon icon={BookOpen01Icon} size={16} />
			<span class="hidden sm:inline">Open Evidence</span>
		</button>
	{/if}
</div>

<!-- Source Upload Modal -->
<UploadModal bind:open={uploadModalOpen} {books} />
