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
		Sun01Icon,
		Moon01Icon,
		SidebarLeftIcon
	} from '@hugeicons/core-free-icons';

	import AnswerStream from '$components/app/AnswerStream.svelte';
	import UploadModal from '$components/app/UploadModal.svelte';
	import { getBooks, getCapabilities, getCatalogFilters, getLibrary, search, streamAnswer } from '$api/client';
	import type {
		AnswerMode,
		AnswerStreamEvent,
		Book,
		CatalogFilters,
		DocumentUploadAccepted,
		LibraryItem,
		ResponseLength,
		SearchResult,
		Standard
	} from '$api/v1';
	
	/* --- Quick Prompt Suggestion Chips --- */
	const PROMPT_CHIPS = [
		{ label: 'Explain with an example', icon: SparklesIcon, query: 'Explain the solar system with an example.' },
		{ label: 'What is pressure?', icon: BookOpen01Icon, query: 'What is pressure and how does it work?' },
		{ label: 'Tell me about Earth', icon: File01Icon, query: 'Tell me about the Earth and its structure.' },
		{ label: 'Quiz me', icon: CheckmarkCircle02Icon, query: 'Quiz me with 2 multiple choice questions on the solar system.' }
	];

	import { themeState } from '$lib/theme.svelte';

	/* --- Cover background colors for books (cycled by index) --- */
	const COVER_COLORS = [
		'from-blue-600 to-indigo-900',
		'from-teal-600 to-emerald-900',
		'from-blue-500 to-cyan-800',
		'from-amber-600 to-orange-950',
		'from-sky-700 to-slate-900',
		'from-purple-600 to-violet-900',
		'from-rose-600 to-pink-900'
	];

	/* --- State --- */
	let theme = $derived(themeState.current); // Sync with global ThemeState (Dark Image 1 / Light Image 2)
	let sidebarOpen = $state(false);
	let evidencePanelOpen = $state(false);
	let activeTab = $state<'ask' | 'library' | 'notes'>('ask');
	let evidenceTab = $state<'evidence' | 'notes' | 'outline'>('evidence');
	let uploadModalOpen = $state(false);
	let maxUploadBytes = $state(52_428_800);

	let books = $state<Book[]>([]);
	let selectedBookIds = $state<Set<string>>(new Set());
	let libraryItems = $state<LibraryItem[]>([]);
	let libraryLoading = $state(false);
	let librarySearchQuery = $state('');
	let selectedLibraryStandard = $state<number | null>(null);
	let selectedLibrarySubject = $state<string | null>(null);
	let askQuery = $state('');
	let submittedQuery = $state('');
	let mode = $state<AnswerMode>('textbook_only');
	let responseLength = $state<ResponseLength>('medium');

	let answerStream = $state<AsyncGenerator<AnswerStreamEvent> | null>(null);
	let evidence = $state<SearchResult[] | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let abController = $state<AbortController | null>(null);
	let activeCitationIndex = $state(0);

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
	let selectedCitation = $derived(evidence?.[activeCitationIndex]?.evidence ?? null);
	let selectedBooks = $derived(books.filter((b) => selectedBookIds.has(b.id)));

	let filteredLibraryItems = $derived(
		libraryItems.filter((item) => {
			if (selectedLibraryStandard !== null && item.standard !== selectedLibraryStandard) return false;
			if (selectedLibrarySubject !== null && item.subject.toLowerCase() !== selectedLibrarySubject.toLowerCase()) return false;
			if (librarySearchQuery.trim()) {
				const q = librarySearchQuery.trim().toLowerCase();
				return (
					item.title.toLowerCase().includes(q) ||
					item.subject.toLowerCase().includes(q) ||
					item.source_filename.toLowerCase().includes(q)
				);
			}
			return true;
		})
	);

	let libraryStandards = $derived(Array.from(new Set(libraryItems.map((i) => i.standard))).sort((a, b) => a - b));
	let librarySubjects = $derived(Array.from(new Set(libraryItems.map((i) => i.subject))).sort());

	async function fetchLibrary() {
		libraryLoading = true;
		try {
			libraryItems = await getLibrary();
		} catch (e) {
			console.error('Failed to load library:', e);
		} finally {
			libraryLoading = false;
		}
	}

	async function handleUploadAccepted(_accepted: DocumentUploadAccepted): Promise<void> {
		await fetchLibrary();
		activeTab = 'library';
	}

	function getCoverColor(index: number): string {
		return COVER_COLORS[index % COVER_COLORS.length];
	}

	function toggleBook(id: string) {
		const next = new Set(selectedBookIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedBookIds = next;
	}

	async function submit(q: string) {
		const trimmed = q.trim();
		if (!trimmed) return;
		submittedQuery = trimmed;
		askQuery = trimmed;
		answerStream = null;
		evidence = null;
		error = null;
		liked = null;
		savedNote = false;
		activeCitationIndex = 0;

		abController?.abort();
		const ac = new AbortController();
		abController = ac;

		loading = true;

		// Build filters from selected books
		const bookIds = Array.from(selectedBookIds);
		const filters = bookIds.length > 0 ? { book_ids: bookIds } : undefined;

		answerStream = streamAnswer(
			{ query: trimmed, mode, response_length: responseLength, filters },
			ac.signal
		);

		try {
			const sr = await search({ query: trimmed, top_k: 5, filters });
			if (!ac.signal.aborted) {
				evidence = sr.results;
			}
		} catch (e) {
			if (!ac.signal.aborted) {
				error = e instanceof Error ? e.message : 'Search failed';
			}
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

	onMount(async () => {
		// Responsive defaults
		if (window.innerWidth >= 768) {
			sidebarOpen = true;
			evidencePanelOpen = true;
		}

		const [booksResult, libraryResult, capabilitiesResult] = await Promise.allSettled([
			getBooks(),
			getLibrary(),
			getCapabilities()
		]);

		if (booksResult.status === 'fulfilled') {
			const res = booksResult.value;
			if (res?.items?.length) {
				books = res.items;
				// Select all books by default
				selectedBookIds = new Set(res.items.map((b) => b.id));
			}
		} else {
			error = booksResult.reason instanceof Error ? booksResult.reason.message : 'Failed to load books';
		}

		if (libraryResult.status === 'fulfilled') {
			libraryItems = libraryResult.value;
		} else {
			console.error('Failed to load library:', libraryResult.reason);
		}

		if (capabilitiesResult.status === 'fulfilled') {
			maxUploadBytes = capabilitiesResult.value.limits.max_upload_bytes;
		} else {
			console.warn('Using the default upload limit because capabilities could not be loaded.');
		}
	});
</script>

<svelte:head>
	<title>LearnFlow — Ask Your Sources</title>
</svelte:head>

<!-- Outer Container handling Theme Switch (Dark Image 1 / Light Image 2) -->
<div
	class="relative h-screen w-screen flex overflow-hidden font-body transition-colors duration-300 {theme === 'dark'
		? 'bg-[#0B0F19] text-slate-100'
		: 'bg-[#F8FAFC] text-slate-800'}"
>
	<!-- Mobile backdrop for left sidebar -->
	{#if sidebarOpen}
		<div
			class="absolute inset-0 z-40 bg-black/50 md:hidden backdrop-blur-sm transition-opacity"
			onclick={() => (sidebarOpen = false)}
			aria-hidden="true"
		></div>
	{/if}

	<!-- ========================================================================= -->
	<!-- 1. LEFT SIDEBAR: Navigation & Sources                                      -->
	<!-- ========================================================================= -->
	<aside
		class="absolute inset-y-0 left-0 z-50 flex flex-col border-r transition-all duration-300 shrink-0 md:relative {sidebarOpen
			? 'w-64 translate-x-0'
			: 'w-64 -translate-x-full md:w-16 md:translate-x-0'} {theme === 'dark'
			? 'bg-[#0F172A]/95 border-slate-800/80 md:bg-[#0F172A]/70'
			: 'bg-white border-slate-200 shadow-xl md:shadow-none'}"
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
					: 'px-2 text-xs md:flex hidden'}"
				onclick={() => (uploadModalOpen = true)}
			>
				<HugeiconsIcon icon={Upload01Icon} size={18} strokeWidth={2.2} />
				<span class:hidden={!sidebarOpen}>Upload source</span>
			</button>
		</div>

		<!-- Navigation Menu Links -->
		<nav class="space-y-1 px-3 py-2">
			{#each [{ id: 'ask', label: 'Ask', icon: Message01Icon }, { id: 'library', label: 'Library', icon: BookOpen01Icon }, { id: 'notes', label: 'Notes', icon: File01Icon }] as item}
				<button
					type="button"
					class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors {activeTab === item.id
						? theme === 'dark'
							? 'bg-blue-600/15 text-blue-400'
							: 'bg-blue-50 text-blue-600 font-semibold'
						: theme === 'dark'
							? 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
							: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}"
					onclick={() => {
						activeTab = item.id as any;
						if (window.innerWidth < 768) sidebarOpen = false;
					}}
				>
					<HugeiconsIcon icon={item.icon} size={18} />
					<span class:hidden={!sidebarOpen} class="md:inline">{item.label}</span>
				</button>
			{/each}
		</nav>

		<!-- "Your sources" List Section -->
		<div class="mt-4 flex-1 overflow-y-auto px-3" class:hidden={!sidebarOpen}>
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
					{#if books.length === 0}
						<p class="px-2 py-4 text-xs text-slate-400 text-center">No books available. Upload a textbook to get started.</p>
					{:else}
						{#each books as book, idx (book.id)}
							{@const isSelected = selectedBookIds.has(book.id)}
							<button
								type="button"
								class="group flex w-full items-center gap-3 rounded-xl p-2 text-left transition-all border {isSelected
									? theme === 'dark'
										? 'bg-blue-600/10 border-blue-500/40 ring-1 ring-blue-500/30'
										: 'bg-blue-50/80 border-blue-300 ring-1 ring-blue-400/20'
									: theme === 'dark'
										? 'border-transparent hover:bg-slate-800/40'
										: 'border-transparent hover:bg-slate-100'}"
								onclick={() => toggleBook(book.id)}
							>
								<!-- PDF Cover Thumbnail -->
								<div class="relative grid h-10 w-8 shrink-0 place-items-center rounded-md bg-gradient-to-br {getCoverColor(idx)} text-white shadow-sm font-mono text-[9px] font-bold tracking-tighter">
									PDF
								</div>
								<div class="min-w-0 flex-1">
									<p class="truncate text-xs font-medium {isSelected ? (theme === 'dark' ? 'text-blue-400 font-semibold' : 'text-blue-700 font-semibold') : (theme === 'dark' ? 'text-slate-200' : 'text-slate-700')}">
										{book.title}
									</p>
									<div class="mt-0.5 flex items-center justify-between text-[11px] {theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}">
										<span>Std {book.standard} · {book.subject}</span>
										<HugeiconsIcon icon={CheckmarkCircle02Icon} size={14} class="text-emerald-500 shrink-0" />
									</div>
								</div>
							</button>
						{/each}
					{/if}
				</div>
			</div>
		</div>

	</aside>

	<!-- ========================================================================= -->
	<!-- 2. CENTER PANEL: Ask your sources (Chat & Prompt Composer)                -->
	<!-- ========================================================================= -->
	<main class="flex flex-1 flex-col overflow-hidden w-full max-w-full">
		<!-- Top Bar: Title & Conversation Actions -->
		<header class="flex h-16 items-center justify-between px-4 sm:px-6 border-b shrink-0 {theme === 'dark' ? 'border-slate-800/80 bg-[#0F172A]/40' : 'border-slate-200 bg-white/80'}">
			<div class="flex items-center gap-3">
				<!-- Hamburger for mobile -->
				<button
					type="button"
					class="md:hidden rounded-lg p-1.5 transition-colors {theme === 'dark'
						? 'text-slate-400 hover:bg-slate-800 hover:text-white'
						: 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'}"
					onclick={() => (sidebarOpen = true)}
					title="Open menu"
				>
					<HugeiconsIcon icon={SidebarLeftIcon} size={20} />
				</button>
				<div>
					<h1 class="font-display text-base sm:text-lg font-bold {theme === 'dark' ? 'text-white' : 'text-slate-900'} truncate max-w-[120px] sm:max-w-none">
						Ask your sources
					</h1>
					<p class="hidden sm:block text-xs text-slate-400">Get answers grounded in your uploaded materials.</p>
				</div>
			</div>

			<div class="flex items-center gap-2 sm:gap-3">
				<!-- Theme Switcher Button -->
				<button
					type="button"
					class="flex items-center gap-1.5 rounded-xl border px-2 sm:px-3 py-1.5 text-xs font-medium transition-colors {theme === 'dark'
						? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
						: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
					onclick={() => themeState.toggle()}
					title="Switch Dark/Light Theme"
				>
					{#if theme === 'dark'}
						<HugeiconsIcon icon={Sun01Icon} size={14} class="text-amber-400" />
						<span class="hidden sm:inline">Light</span>
					{:else}
						<HugeiconsIcon icon={Moon01Icon} size={14} class="text-indigo-600" />
						<span class="hidden sm:inline">Dark</span>
					{/if}
				</button>

				{#if activeTab === 'ask'}
					<button
						type="button"
						class="flex items-center gap-1.5 rounded-xl border px-2 sm:px-3 py-1.5 text-xs font-semibold transition-colors {evidencePanelOpen
							? theme === 'dark'
								? 'border-blue-500/40 bg-blue-600/10 text-blue-400'
								: 'border-blue-300 bg-blue-50 text-blue-600'
							: theme === 'dark'
								? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
								: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
						onclick={() => (evidencePanelOpen = !evidencePanelOpen)}
						title="Toggle Evidence Panel"
					>
						<HugeiconsIcon icon={BookOpen01Icon} size={14} />
						<span class="hidden sm:inline">{evidencePanelOpen ? 'Hide Evidence' : 'Evidence'}</span>
					</button>

					<button
						type="button"
						class="flex items-center gap-1.5 rounded-xl border border-blue-500/30 bg-blue-600/10 px-2 sm:px-3 py-1.5 text-xs font-semibold text-blue-500 hover:bg-blue-600/20 transition-colors"
						onclick={() => { askQuery = ''; submittedQuery = ''; answerStream = null; evidence = null; error = null; }}
						title="New conversation"
					>
						<HugeiconsIcon icon={Add01Icon} size={14} />
						<span class="hidden sm:inline">New</span>
					</button>
				{/if}

				<button type="button" class="hidden sm:block rounded-lg p-1.5 text-slate-400 hover:text-slate-200">
					<HugeiconsIcon icon={MoreHorizontalIcon} size={18} />
				</button>
			</div>
		</header>
		{#if activeTab === 'ask'}
			<!-- Active Source Chips Filter Bar -->
			<div class="flex flex-wrap items-center gap-2 px-4 sm:px-6 py-3 border-b text-xs shrink-0 {theme === 'dark' ? 'border-slate-800/60 bg-[#0F172A]/20' : 'border-slate-200 bg-slate-50'}">
				{#each selectedBooks as book}
					<span
						class="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-medium transition-all {theme === 'dark'
							? 'border-slate-700 bg-slate-800/80 text-slate-200'
							: 'border-slate-300 bg-white text-slate-700 shadow-sm'}"
					>
						<span>{book.title}</span>
						<button
							type="button"
							class="text-slate-400 hover:text-rose-400"
							onclick={() => toggleBook(book.id)}
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
			<div class="flex-1 overflow-y-auto px-4 sm:px-6 py-4 sm:py-6 space-y-6">
				{#if !submittedQuery}
					<!-- Welcome / Empty State -->
					<div class="flex flex-col items-center justify-center h-full text-center">
						<div class="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-tr from-blue-600 to-cyan-400 text-white shadow-lg shadow-blue-500/25 mb-6">
							<HugeiconsIcon icon={ZapIcon} size={32} strokeWidth={2.5} />
						</div>
						<h2 class="font-display text-xl font-bold {theme === 'dark' ? 'text-white' : 'text-slate-900'} mb-2">
							Ask your textbooks
						</h2>
						<p class="text-sm text-slate-400 max-w-md mb-6">
							Get answers grounded in Tamil Nadu State Board textbooks. Select sources from the sidebar and ask a question below.
						</p>
						{#if error}
							<div class="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
								{error}
							</div>
						{/if}
					</div>
				{:else}
					<!-- User Question Bubble (Right Aligned) -->
					<div class="flex justify-end">
						<div class="max-w-xl rounded-2xl rounded-tr-sm bg-blue-600 px-5 py-3.5 text-sm font-medium text-white shadow-md shadow-blue-600/20">
							<p>{submittedQuery}</p>
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
									Grounded in {selectedBookIds.size} sources ▾
								</span>
							</div>

							<!-- Formatted Stream Answer Content -->
							<div id="answer-response-text" class="rounded-2xl border p-6 space-y-4 text-sm leading-relaxed {theme === 'dark' ? 'border-slate-800 bg-[#0F172A]/50 text-slate-200' : 'border-slate-200 bg-white text-slate-800 shadow-sm'}">
								{#if error}
									<div class="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
										{error}
									</div>
								{:else if answerStream}
									<AnswerStream stream={answerStream} />
								{:else if loading}
									<div class="flex items-center gap-3 text-slate-400">
										<div class="h-5 w-5 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
										<span>Searching textbooks...</span>
									</div>
								{:else}
									<p class="text-slate-400">No answer available. Try a different question.</p>
								{/if}
							</div>

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
				{/if}
			</div>

			<!-- Input Composer Box (Fixed at Bottom) -->
			<div class="p-4 sm:p-6 border-t shrink-0 {theme === 'dark' ? 'border-slate-800/80 bg-[#0B0F19]' : 'border-slate-200 bg-[#F8FAFC]'}">
				<div class="mx-auto max-w-3xl rounded-2xl border p-2 sm:p-3 shadow-lg transition-all focus-within:border-blue-500/70 focus-within:ring-2 focus-within:ring-blue-500/20 {theme === 'dark' ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'}">
					<textarea
						rows="2"
						placeholder="Ask something from your sources..."
						bind:value={askQuery}
						onkeydown={handleKeydown}
						class="w-full bg-transparent px-2 text-sm resize-none focus:outline-none {theme === 'dark' ? 'text-white placeholder:text-slate-500' : 'text-slate-900 placeholder:text-slate-400'}"
					></textarea>

					<!-- Composer Bottom Toolbar -->
					<div class="flex items-center justify-between pt-2">
						<div class="flex items-center gap-1 sm:gap-2">
							<button
								type="button"
								class="hidden sm:block rounded-lg p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
								title="Attach file"
							>
								<HugeiconsIcon icon={Attachment01Icon} size={18} />
							</button>

							<button
								type="button"
								class="flex items-center gap-1 rounded-lg border px-2 sm:px-2.5 py-1 text-[10px] sm:text-xs font-semibold transition-colors {theme === 'dark'
									? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
									: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
								onclick={() => (mode = mode === 'textbook_only' ? 'textbook_plus_general' : 'textbook_only')}
							>
								<HugeiconsIcon icon={BookOpen01Icon} size={14} class="text-blue-500" />
								<span class="hidden sm:inline">Mode: {mode === 'textbook_only' ? 'Textbook Only (Strict)' : 'Textbook + General GK'}</span>
								<span class="sm:hidden">{mode === 'textbook_only' ? 'Strict' : 'General'}</span>
							</button>

							<button
								type="button"
								class="flex items-center gap-1 rounded-lg border px-2 sm:px-2.5 py-1 text-[10px] sm:text-xs font-semibold transition-colors {theme === 'dark'
									? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
									: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
								onclick={() => (responseLength = responseLength === 'medium' ? 'long' : responseLength === 'long' ? 'short' : 'medium')}
							>
								<span class="hidden sm:inline">Length: {responseLength}</span>
								<span class="sm:hidden capitalize">{responseLength}</span>
							</button>
						</div>

						<button
							type="button"
							class="flex items-center gap-1.5 rounded-xl bg-blue-600 px-3 sm:px-4 py-1.5 sm:py-2 text-xs font-semibold text-white shadow-md shadow-blue-600/30 hover:bg-blue-500 transition-colors disabled:opacity-50"
							disabled={loading || !askQuery.trim()}
							onclick={() => submit(askQuery)}
						>
							<HugeiconsIcon icon={SentIcon} size={14} />
							<span class="hidden sm:inline">Send</span>
						</button>
					</div>
				</div>

				<p class="hidden sm:block mt-2 text-center text-[11px] text-slate-400">
					ⓘ Answers may be incomplete. Verify important details using the cited passages.
				</p>
			</div>
		{:else if activeTab === 'library'}
			<!-- ========================================================================= -->
			<!-- LIBRARY VIEW                                                              -->
			<!-- ========================================================================= -->
			<div class="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
				<!-- Search & Filter Controls Bar -->
				<div class="flex flex-wrap items-center justify-between gap-4">
					<!-- Search Input -->
					<div class="relative flex-1 min-w-[260px]">
						<HugeiconsIcon icon={Search01Icon} size={16} class="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
						<input
							type="text"
							bind:value={librarySearchQuery}
							placeholder="Search library by title, subject, filename..."
							class="w-full rounded-xl border pl-10 pr-4 py-2 text-sm transition-all focus:outline-none focus:ring-2 focus:ring-blue-500/50 {theme === 'dark' ? 'bg-slate-800/70 border-slate-700 text-slate-100 placeholder-slate-400' : 'bg-white border-slate-300 text-slate-800 placeholder-slate-400 shadow-sm'}"
						/>
					</div>

					<!-- Filter Pills -->
					<div class="flex items-center gap-2 flex-wrap text-xs">
						<span class="text-slate-400 font-medium mr-1">Standard:</span>
						<button
							type="button"
							class="rounded-lg px-2.5 py-1 font-medium transition-colors {selectedLibraryStandard === null ? 'bg-blue-600 text-white' : (theme === 'dark' ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300')}"
							onclick={() => (selectedLibraryStandard = null)}
						>
							All
						</button>
						{#each libraryStandards as std}
							<button
								type="button"
								class="rounded-lg px-2.5 py-1 font-medium transition-colors {selectedLibraryStandard === std ? 'bg-blue-600 text-white' : (theme === 'dark' ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300')}"
								onclick={() => (selectedLibraryStandard = std)}
							>
								Std {std}
							</button>
						{/each}

						<span class="text-slate-400 font-medium ml-2 mr-1">Subject:</span>
						<button
							type="button"
							class="rounded-lg px-2.5 py-1 font-medium transition-colors {selectedLibrarySubject === null ? 'bg-blue-600 text-white' : (theme === 'dark' ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300')}"
							onclick={() => (selectedLibrarySubject = null)}
						>
							All
						</button>
						{#each librarySubjects as subj}
							<button
								type="button"
								class="rounded-lg px-2.5 py-1 font-medium transition-colors {selectedLibrarySubject === subj ? 'bg-blue-600 text-white' : (theme === 'dark' ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300')}"
								onclick={() => (selectedLibrarySubject = subj)}
							>
								{subj}
							</button>
						{/each}
					</div>
				</div>

				<!-- Stats summary -->
				<div class="flex items-center justify-between text-xs text-slate-400 px-1">
					<span>Showing <strong>{filteredLibraryItems.length}</strong> of <strong>{libraryItems.length}</strong> textbook PDF documents</span>
				</div>

				<!-- PDF Cards Grid -->
				{#if libraryLoading}
					<div class="grid place-items-center py-16 text-slate-400">
						<div class="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
						<p class="mt-3 text-sm">Loading library documents...</p>
					</div>
				{:else if filteredLibraryItems.length === 0}
					<div class="rounded-2xl border p-12 text-center {theme === 'dark' ? 'border-slate-800 bg-slate-900/40' : 'border-slate-200 bg-white'}">
						<HugeiconsIcon icon={BookOpen01Icon} size={40} class="mx-auto text-slate-400" />
						<h3 class="mt-3 text-base font-semibold {theme === 'dark' ? 'text-slate-200' : 'text-slate-800'}">No matching textbooks found</h3>
						<p class="mt-1 text-xs text-slate-400">Try clearing your search filters or upload a new source PDF.</p>
					</div>
				{:else}
					<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
						{#each filteredLibraryItems as item, idx (item.document_id)}
							<div class="flex flex-col rounded-2xl border p-5 transition-all hover:shadow-lg {theme === 'dark' ? 'border-slate-800/80 bg-slate-900/60 hover:border-slate-700' : 'border-slate-200 bg-white hover:border-slate-300 shadow-sm'}">
								<!-- Card Header -->
								<div class="flex items-start justify-between gap-3">
									<div class="grid h-12 w-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br {getCoverColor(idx)} text-white shadow-md font-mono text-[10px] font-bold">
										PDF
									</div>
									<div class="flex flex-col items-end gap-1">
										<span class="rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase {item.state === 'ready' ? (theme === 'dark' ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border border-emerald-200') : (theme === 'dark' ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' : 'bg-amber-50 text-amber-700 border border-amber-200')}">
											{item.state}
										</span>
										<span class="text-[11px] font-medium text-slate-400">Std {item.standard}</span>
									</div>
								</div>

								<!-- Card Content -->
								<div class="mt-4 flex-1">
									<h3 class="font-display text-sm font-bold leading-snug {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
										{item.title}
									</h3>
									<div class="mt-3 space-y-1.5 text-xs {theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}">
										<p class="flex items-center justify-between">
											<span class="text-slate-400">Subject:</span>
											<span class="font-medium">{item.subject}</span>
										</p>
										<p class="flex items-center justify-between">
											<span class="text-slate-400">Edition:</span>
											<span class="font-medium">{item.edition}</span>
										</p>
										<p class="flex items-center justify-between">
											<span class="text-slate-400">File:</span>
											<span class="font-mono text-[11px] truncate max-w-[170px]">{item.source_filename}</span>
										</p>
										<p class="flex items-center justify-between">
											<span class="text-slate-400">Pages / Size:</span>
											<span class="font-medium">{item.page_count ?? '—'} pages · {(item.file_size_bytes / (1024 * 1024)).toFixed(1)} MB</span>
										</p>
									</div>
								</div>

								<!-- Card Footer Action -->
								<div class="mt-5 pt-3 border-t {theme === 'dark' ? 'border-slate-800' : 'border-slate-100'}">
									<button
										type="button"
										class="flex w-full items-center justify-center gap-2 rounded-xl border border-blue-500/30 bg-blue-600/10 py-2 text-xs font-semibold text-blue-500 hover:bg-blue-600/20 transition-colors"
										onclick={() => {
											selectedBookIds = new Set([item.book_id]);
											activeTab = 'ask';
										}}
									>
										<HugeiconsIcon icon={Message01Icon} size={14} />
										<span>Ask about this book</span>
									</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{:else if activeTab === 'notes'}
			<!-- ========================================================================= -->
			<!-- NOTES VIEW                                                                -->
			<!-- ========================================================================= -->
			<div class="flex flex-1 flex-col items-center justify-center p-8 text-center">
				<div class="grid h-16 w-16 place-items-center rounded-2xl bg-blue-600/10 text-blue-500 mb-4">
					<HugeiconsIcon icon={File01Icon} size={32} />
				</div>
				<h2 class="font-display text-xl font-bold {theme === 'dark' ? 'text-white' : 'text-slate-900'}">Notes & Saved Highlights</h2>
				<p class="mt-2 text-sm text-slate-400 max-w-md">Notes persistence feature is coming in an upcoming update. Your saved evidence citations and key answer notes will be stored here.</p>
				<button
					type="button"
					class="mt-6 rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-semibold text-white hover:bg-blue-500 transition-colors shadow-md shadow-blue-600/20"
					onclick={() => (activeTab = 'ask')}
				>
					Return to Ask
				</button>
			</div>
		{/if}
	</main>

	<!-- Mobile backdrop for evidence panel -->
	{#if evidencePanelOpen}
		<div
			class="absolute inset-0 z-40 bg-black/50 lg:hidden backdrop-blur-sm transition-opacity"
			onclick={() => (evidencePanelOpen = false)}
			aria-hidden="true"
		></div>
	{/if}

	<!-- ========================================================================= -->
	<!-- 3. RIGHT SIDEBAR: Evidence & Passage Inspection Panel                     -->
	<!-- ========================================================================= -->
	<aside
		class="absolute inset-y-0 right-0 z-50 flex w-[85vw] sm:w-80 flex-col border-l transition-all duration-300 shrink-0 lg:relative {evidencePanelOpen
			? 'translate-x-0'
			: 'translate-x-full lg:translate-x-0 lg:w-0 lg:border-l-0 overflow-hidden hidden lg:flex'} {theme === 'dark'
			? 'bg-[#0F172A]/95 border-slate-800/80 lg:bg-[#0F172A]/70'
			: 'bg-white border-slate-200 shadow-xl lg:shadow-none'}"
	>
		{#if evidencePanelOpen || (typeof window !== 'undefined' && window.innerWidth >= 1024)}
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
			<div class="flex-1 overflow-y-auto p-4 sm:p-5 space-y-5">
				{#if !evidence || evidence.length === 0}
					<!-- Empty state -->
					<div class="flex flex-col items-center justify-center h-full text-center py-12">
						<div class="grid h-12 w-12 place-items-center rounded-xl bg-slate-800 text-slate-400 mb-4">
							<HugeiconsIcon icon={BookOpen01Icon} size={24} />
						</div>
						<p class="text-sm text-slate-400">Ask a question to see evidence from your textbooks.</p>
					</div>
				{:else}
					<!-- Citation Stepper Header -->
					<div class="flex items-center justify-between text-xs text-slate-400 font-medium">
						<span>Citation {activeCitationIndex + 1} of {evidence.length}</span>
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
								disabled={activeCitationIndex === (evidence?.length ?? 0) - 1}
								class="rounded p-1 hover:bg-slate-800 hover:text-white disabled:opacity-30"
								onclick={() => (activeCitationIndex = Math.min((evidence?.length ?? 1) - 1, activeCitationIndex + 1))}
							>
								<HugeiconsIcon icon={ArrowRight01Icon} size={14} />
							</button>
						</div>
					</div>
			
					<!-- Document Source Info -->
					<div>
						<h3 class="font-bold text-sm {theme === 'dark' ? 'text-white' : 'text-slate-900'}">
							{selectedCitation?.book_title ?? 'Unknown'}
						</h3>
						<div class="mt-1 flex items-center justify-between text-xs text-slate-400">
							<span>
								{selectedCitation?.section_path?.join(' › ') ?? ''}
								{#if selectedCitation?.printed_page_label}
									· Page {selectedCitation.printed_page_label}
								{/if}
							</span>
							<span class="text-blue-500">Score: {evidence?.[activeCitationIndex]?.score?.toFixed(2) ?? '—'}</span>
						</div>
					</div>
			
					<!-- Textbook Page Preview Card -->
					<div class="rounded-xl border p-4 text-xs leading-relaxed space-y-3 font-serif shadow-inner {theme === 'dark' ? 'border-slate-800 bg-[#090D16] text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-800'}">
						<div class="font-sans text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b pb-1 border-slate-800">
							{selectedCitation?.section_path?.[selectedCitation.section_path.length - 1] ?? 'Excerpt'}
						</div>
						<p class="textbook-highlight font-sans text-xs whitespace-pre-wrap">
							{selectedCitation?.text ?? ''}
						</p>
						<div class="text-right text-[10px] font-mono text-slate-500 pt-2 border-t border-slate-800/40">
							{selectedCitation?.printed_page_label ?? selectedCitation?.pdf_page_index ?? ''}
						</div>
					</div>
			
					<!-- Action Buttons -->
					<div class="flex flex-wrap gap-2 text-xs">
						<button
							type="button"
							class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-medium transition-colors {copiedExcerpt ? 'border-emerald-500 bg-emerald-500/10 text-emerald-500 font-semibold' : theme === 'dark' ? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700' : 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
							onclick={() => copyToClipboard(selectedCitation?.text ?? '', 'excerpt')}
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
							{#each evidence as c, idx}
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
											{idx + 1}
										</span>
										<span class="truncate max-w-[140px]">{c.evidence.book_title}</span>
									</div>
									<span class="font-mono text-[10px] text-slate-400">p.{c.evidence.printed_page_label ?? c.evidence.pdf_page_index}</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</aside>

	<!-- Floating handle to easily reopen Evidence Panel when closed -->
	{#if !evidencePanelOpen}
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
<UploadModal bind:open={uploadModalOpen} {books} {maxUploadBytes} onUploaded={handleUploadAccepted} />
