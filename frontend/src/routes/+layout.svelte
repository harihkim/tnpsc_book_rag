<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { themeState } from '$lib/theme.svelte';
	import { HugeiconsIcon } from '@hugeicons/svelte';
	import { ZapIcon, Sun01Icon, Moon01Icon } from '@hugeicons/core-free-icons';

	let { children } = $props();
	let isAppPage = $derived(page.url.pathname.startsWith('/app'));
</script>

{#if isAppPage}
	<!-- Full screen workspace renders its own dedicated LearnFlow sidebar & topbar -->
	<div class="h-screen w-screen overflow-hidden font-body antialiased {themeState.current === 'dark' ? 'bg-[#0B0F19] text-slate-100' : 'bg-[#F8FAFC] text-slate-900'}">
		{@render children()}
	</div>
{:else}
	<div class="min-h-screen font-body selection:bg-blue-600 selection:text-white transition-colors duration-300 {themeState.current === 'dark' ? 'bg-[#090D16] text-slate-100' : 'bg-slate-50 text-slate-900'}">
		<header
			class="fixed inset-x-0 top-0 z-40 border-b backdrop-blur-xl transition-colors duration-300 {themeState.current === 'dark' ? 'border-slate-800/80 bg-[#090D16]/80' : 'border-slate-200/80 bg-white/80'}"
		>
			<nav class="mx-auto flex h-16 max-w-6xl items-center justify-between px-6 lg:px-10">
				<a href="/" class="group flex items-center gap-3">
					<div
						class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-400 text-white shadow-md shadow-blue-500/25 transition-transform duration-200 group-hover:scale-105"
					>
						<HugeiconsIcon icon={ZapIcon} size={20} strokeWidth={2.5} />
					</div>
					<span class="font-display text-xl font-bold tracking-tight {themeState.current === 'dark' ? 'text-white' : 'text-slate-900'}">
						Learn<span class="text-blue-500">Flow</span>
					</span>
				</a>

				<div class="hidden items-center gap-8 text-sm font-medium md:flex {themeState.current === 'dark' ? 'text-slate-300' : 'text-slate-600'}">
					<a href="/#features" class="transition-colors hover:text-blue-500">Features</a>
					<a href="/#how" class="transition-colors hover:text-blue-500">How Aspirants Study</a>
					<a href="/#grounded" class="transition-colors hover:text-blue-500">Page Provenance</a>
					<a href="/#subjects" class="transition-colors hover:text-blue-500">TNPSC Textbooks</a>
				</div>

				<div class="flex items-center gap-3">
					<!-- Theme Toggle Button on Landing Page -->
					<button
						type="button"
						class="flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-colors {themeState.current === 'dark'
							? 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
							: 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200'}"
						onclick={() => themeState.toggle()}
						title="Switch Theme"
					>
						{#if themeState.current === 'dark'}
							<HugeiconsIcon icon={Sun01Icon} size={14} class="text-amber-400" />
							<span>Light mode</span>
						{:else}
							<HugeiconsIcon icon={Moon01Icon} size={14} class="text-indigo-600" />
							<span>Dark mode</span>
						{/if}
					</button>

					<a
						href="/app"
						class="rounded-full bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow-md shadow-blue-600/30 transition-all duration-200 hover:-translate-y-0.5 hover:bg-blue-500 hover:shadow-lg hover:shadow-blue-600/50"
					>
						Open Workspace
					</a>
				</div>
			</nav>
		</header>

		<main class="pt-16">{@render children()}</main>

		<footer class="border-t transition-colors duration-300 {themeState.current === 'dark' ? 'border-slate-800/80 bg-[#060911]' : 'border-slate-200 bg-slate-100'}">
			<div
				class="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 text-xs sm:flex-row sm:items-center sm:justify-between lg:px-10 font-mono {themeState.current === 'dark' ? 'text-slate-400' : 'text-slate-600'}"
			>
				<p>
					LearnFlow · AI Study Platform for TNPSC Exams · Tamil Nadu State Board Textbooks (Std 6–10)
				</p>
				<p class="flex gap-5">
					<a href="/#features" class="transition-colors hover:text-blue-500">features</a>
					<a href="/app" class="transition-colors hover:text-blue-500">workspace</a>
				</p>
			</div>
		</footer>
	</div>
{/if}

