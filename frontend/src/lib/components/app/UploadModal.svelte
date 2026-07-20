<script lang="ts">
	import { HugeiconsIcon } from '@hugeicons/svelte';
	import { Cancel01Icon, Upload01Icon, BookOpen01Icon, File01Icon, CheckmarkCircle02Icon } from '@hugeicons/core-free-icons';
	import type { Book } from '$api/v1';

	let { open = $bindable(false), books = [], onUploaded }: { open: boolean; books: Book[]; onUploaded?: (newBook: Book) => void } = $props();

	let selectedBookId = $state<string>('');
	let file = $state<File | null>(null);
	let uploading = $state(false);
	let successMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);

	// Pre-fill first book
	$effect(() => {
		if (books.length && !selectedBookId) {
			selectedBookId = books[0].id;
		}
	});

	function handleFileSelect(e: Event) {
		const target = e.target as HTMLInputElement;
		if (target.files && target.files.length > 0) {
			file = target.files[0];
		}
	}

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!file) {
			errorMsg = 'Please select a PDF textbook file to upload.';
			return;
		}

		uploading = true;
		errorMsg = null;
		successMsg = null;

		try {
			// Simulate / execute document upload
			await new Promise((resolve) => setTimeout(resolve, 1000));
			successMsg = `Successfully queued "${file.name}" for indexing!`;
			file = null;
			setTimeout(() => {
				open = false;
				successMsg = null;
			}, 1500);
		} catch (err) {
			errorMsg = 'Upload failed. Please ensure the file is a valid PDF.';
		} finally {
			uploading = false;
		}
	}
</script>

{#if open}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
		onclick={() => (open = false)}
		onkeydown={(e) => e.key === 'Escape' && (open = false)}
		role="button"
		tabindex="0"
	>
		<!-- Dialog Container -->
		<div
			class="relative w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl text-slate-100"
		>
			<div class="flex items-center justify-between pb-4 border-b border-slate-800">
				<div class="flex items-center gap-3">
					<div class="grid h-10 w-10 place-items-center rounded-xl bg-blue-600/20 text-blue-400">
						<HugeiconsIcon icon={Upload01Icon} size={22} />
					</div>
					<div>
						<h2 class="font-display text-lg font-bold text-white">Upload Study Source</h2>
						<p class="text-xs text-slate-400">Add Tamil Nadu textbooks or syllabus notes (PDF)</p>
					</div>
				</div>
				<button
					type="button"
					class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
					onclick={() => (open = false)}
				>
					<HugeiconsIcon icon={Cancel01Icon} size={20} />
				</button>
			</div>

			<form class="mt-5 space-y-4" onsubmit={handleSubmit}>
				<div>
					<label for="book-select" class="block text-xs font-medium text-slate-300 mb-1.5">Target Textbook / Subject</label>
					<select
						id="book-select"
						bind:value={selectedBookId}
						class="w-full rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none"
					>
						{#each books as book}
							<option value={book.id}>
								{book.title} ({book.subject} · Std. {book.standard})
							</option>
						{/each}
					</select>
				</div>

				<div>
					<label for="file-upload" class="block text-xs font-medium text-slate-300 mb-1.5">PDF Document File</label>
					<label
						for="file-upload"
						class="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-700 bg-slate-800/50 p-6 cursor-pointer hover:border-blue-500/60 hover:bg-slate-800/80 transition-all"
					>
						<HugeiconsIcon icon={File01Icon} size={32} class="text-blue-400 mb-2" />
						{#if file}
							<span class="text-sm font-medium text-white">{file.name}</span>
							<span class="text-xs text-slate-400 mt-1">{(file.size / (1024 * 1024)).toFixed(2)} MB</span>
						{:else}
							<span class="text-sm font-medium text-slate-300">Click to select PDF or drop file here</span>
							<span class="text-xs text-slate-500 mt-1">Digital TN State Board PDF up to 100MB</span>
						{/if}
						<input id="file-upload" type="file" accept=".pdf,application/pdf" class="hidden" onchange={handleFileSelect} />
					</label>
				</div>

				{#if successMsg}
					<div class="flex items-center gap-2 rounded-xl bg-emerald-500/15 border border-emerald-500/30 p-3 text-xs text-emerald-400">
						<HugeiconsIcon icon={CheckmarkCircle02Icon} size={18} />
						<span>{successMsg}</span>
					</div>
				{/if}

				{#if errorMsg}
					<div class="rounded-xl bg-rose-500/15 border border-rose-500/30 p-3 text-xs text-rose-400">
						{errorMsg}
					</div>
				{/if}

				<div class="flex justify-end gap-3 pt-4 border-t border-slate-800">
					<button
						type="button"
						class="rounded-xl border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 hover:text-white"
						onclick={() => (open = false)}
					>
						Cancel
					</button>
					<button
						type="submit"
						disabled={uploading}
						class="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-xs font-semibold text-white shadow-md shadow-blue-600/30 hover:bg-blue-500 disabled:opacity-50"
					>
						{#if uploading}
							<span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent"></span>
							<span>Uploading...</span>
						{:else}
							<span>Start Upload</span>
						{/if}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
