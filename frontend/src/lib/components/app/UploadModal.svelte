<script lang="ts">
	import { HugeiconsIcon } from '@hugeicons/svelte';
	import {
		Cancel01Icon,
		Upload01Icon,
		File01Icon,
		CheckmarkCircle02Icon
	} from '@hugeicons/core-free-icons';
	import { ApiProblemError, uploadBookDocument } from '$api/client';
	import type { Book, DocumentUploadAccepted } from '$api/v1';

	const DEFAULT_MAX_UPLOAD_BYTES = 52_428_800;

	let {
		open = $bindable(false),
		books = [],
		maxUploadBytes = DEFAULT_MAX_UPLOAD_BYTES,
		onUploaded
	}: {
		open: boolean;
		books: Book[];
		maxUploadBytes?: number;
		onUploaded?: (accepted: DocumentUploadAccepted) => void | Promise<void>;
	} = $props();

	let selectedBookId = $state('');
	let edition = $state('');
	let file = $state<File | null>(null);
	let fileInput = $state<HTMLInputElement>();
	let uploading = $state(false);
	let acceptedUpload = $state<DocumentUploadAccepted | null>(null);
	let errorMsg = $state<string | null>(null);

	let maxUploadLabel = $derived(formatBytes(maxUploadBytes));

	$effect(() => {
		if (books.length && !books.some((book) => book.id === selectedBookId)) {
			selectedBookId = books[0].id;
		}
	});

	function formatBytes(bytes: number): string {
		if (bytes >= 1024 * 1024) {
			const value = bytes / (1024 * 1024);
			return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)} MiB`;
		}
		return `${Math.ceil(bytes / 1024)} KiB`;
	}

	function resetForm(): void {
		file = null;
		edition = '';
		acceptedUpload = null;
		errorMsg = null;
		if (fileInput) fileInput.value = '';
	}

	function closeModal(): void {
		if (uploading) return;
		open = false;
		resetForm();
	}

	function setFile(candidate: File | null): void {
		errorMsg = null;
		acceptedUpload = null;

		if (!candidate) {
			file = null;
			return;
		}
		const hasPdfName = candidate.name.toLowerCase().endsWith('.pdf');
		const hasPdfType = candidate.type === 'application/pdf' || candidate.type === '';
		if (!hasPdfName || !hasPdfType) {
			file = null;
			errorMsg = 'Choose a PDF file.';
			if (fileInput) fileInput.value = '';
			return;
		}
		if (candidate.size > maxUploadBytes) {
			file = null;
			errorMsg = `This PDF is ${formatBytes(candidate.size)}. The upload limit is ${maxUploadLabel}.`;
			if (fileInput) fileInput.value = '';
			return;
		}
		file = candidate;
	}

	function handleFileSelect(event: Event): void {
		const target = event.target as HTMLInputElement;
		setFile(target.files?.[0] ?? null);
	}

	function handleDrop(event: DragEvent): void {
		event.preventDefault();
		setFile(event.dataTransfer?.files?.[0] ?? null);
	}

	function errorMessage(error: unknown): string {
		if (!(error instanceof ApiProblemError)) {
			return error instanceof Error ? error.message : 'Upload failed. Please try again.';
		}
		switch (error.status) {
			case 401:
				return 'Sign in with curator access before uploading a textbook.';
			case 403:
				return 'Your account does not have permission to upload textbooks.';
			case 409:
				return error.problem?.detail ?? 'This PDF has already been uploaded.';
			case 413:
				return `The backend rejected this PDF because it exceeds the ${maxUploadLabel} limit.`;
			case 415:
				return 'The backend could not verify this file as a valid PDF.';
			case 429:
				return 'The upload rate limit has been reached. Please try again later.';
			default:
				return error.problem?.detail ?? `Upload failed (${error.status}). Please try again.`;
		}
	}

	async function handleSubmit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!selectedBookId) {
			errorMsg = 'Choose a textbook before uploading.';
			return;
		}
		if (!edition.trim()) {
			errorMsg = 'Enter the edition or academic year for this PDF.';
			return;
		}
		if (!file) {
			errorMsg = 'Choose a PDF textbook file to upload.';
			return;
		}

		uploading = true;
		errorMsg = null;
		acceptedUpload = null;

		try {
			const accepted = await uploadBookDocument({
				bookId: selectedBookId,
				file,
				edition: edition.trim()
			});
			acceptedUpload = accepted;
			try {
				await onUploaded?.(accepted);
			} catch (refreshError) {
				console.error('Upload accepted, but the library refresh failed:', refreshError);
			}
		} catch (error) {
			errorMsg = errorMessage(error);
		} finally {
			uploading = false;
		}
	}

	function handleWindowKeydown(event: KeyboardEvent): void {
		if (open && event.key === 'Escape') closeModal();
	}
</script>

<svelte:window onkeydown={handleWindowKeydown} />

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
		onclick={(event) => event.target === event.currentTarget && closeModal()}
		role="presentation"
	>
		<div
			class="relative w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 text-slate-100 shadow-2xl"
			role="dialog"
			aria-modal="true"
			aria-labelledby="upload-dialog-title"
			aria-describedby="upload-dialog-description"
		>
			<div class="flex items-center justify-between border-b border-slate-800 pb-4">
				<div class="flex items-center gap-3">
					<div class="grid h-10 w-10 place-items-center rounded-xl bg-blue-600/20 text-blue-400">
						<HugeiconsIcon icon={Upload01Icon} size={22} />
					</div>
					<div>
						<h2 id="upload-dialog-title" class="font-display text-lg font-bold text-white">Upload study source</h2>
						<p id="upload-dialog-description" class="text-xs text-slate-400">
							Add a text-based Tamil Nadu textbook PDF to the ingestion queue.
						</p>
					</div>
				</div>
				<button
					type="button"
					class="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:opacity-50"
					onclick={closeModal}
					disabled={uploading}
					aria-label="Close upload dialog"
				>
					<HugeiconsIcon icon={Cancel01Icon} size={20} />
				</button>
			</div>

			<form class="mt-5 space-y-4" onsubmit={handleSubmit}>
				<div>
					<label for="book-select" class="mb-1.5 block text-xs font-medium text-slate-300">Target textbook</label>
					<select
						id="book-select"
						bind:value={selectedBookId}
						disabled={uploading || books.length === 0 || acceptedUpload !== null}
						required
						class="w-full rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
					>
						{#if books.length === 0}
							<option value="">No catalog books available</option>
						{:else}
							{#each books as book}
								<option value={book.id}>
									{book.title} ({book.subject} · Std. {book.standard})
								</option>
							{/each}
						{/if}
					</select>
					{#if books.length === 0}
						<p class="mt-1.5 text-xs text-amber-300">Register a textbook in the catalog before attaching a PDF.</p>
					{/if}
				</div>

				<div>
					<label for="edition" class="mb-1.5 block text-xs font-medium text-slate-300">Edition or academic year</label>
					<input
						id="edition"
						type="text"
						bind:value={edition}
						maxlength="200"
						required
						disabled={uploading || acceptedUpload !== null}
						placeholder="e.g. 2025–26 edition"
						class="w-full rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
					/>
				</div>

				<div>
					<label for="file-upload" class="mb-1.5 block text-xs font-medium text-slate-300">PDF document</label>
					<label
						for="file-upload"
						ondragover={(event) => event.preventDefault()}
						ondrop={handleDrop}
						class="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-700 bg-slate-800/50 p-6 transition-colors hover:border-blue-500/60 hover:bg-slate-800/80 focus-within:border-blue-500"
					>
						<HugeiconsIcon icon={File01Icon} size={32} class="mb-2 text-blue-400" />
						{#if file}
							<span class="max-w-full truncate text-sm font-medium text-white">{file.name}</span>
							<span class="mt-1 text-xs text-slate-400">{formatBytes(file.size)}</span>
						{:else}
							<span class="text-sm font-medium text-slate-300">Choose or drop a PDF</span>
							<span class="mt-1 text-xs text-slate-500">Text-based PDF, up to {maxUploadLabel}</span>
						{/if}
						<input
							id="file-upload"
							bind:this={fileInput}
							type="file"
							accept=".pdf,application/pdf"
							class="sr-only"
							onchange={handleFileSelect}
							disabled={uploading || acceptedUpload !== null}
						/>
					</label>
				</div>

				{#if acceptedUpload}
					<div
						class="flex items-start gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/15 p-3 text-xs text-emerald-300"
						role="status"
					>
						<HugeiconsIcon icon={CheckmarkCircle02Icon} size={18} class="mt-0.5 shrink-0" />
						<div>
							<p class="font-semibold">Upload accepted</p>
							<p class="mt-0.5 text-emerald-300/80">
								{acceptedUpload.document.source_filename} is {acceptedUpload.ingestion_run.status}. Indexing continues in the background.
							</p>
						</div>
					</div>
				{/if}

				{#if errorMsg}
					<div class="rounded-xl border border-rose-500/30 bg-rose-500/15 p-3 text-xs text-rose-300" role="alert">
						{errorMsg}
					</div>
				{/if}

				<div class="flex justify-end gap-3 border-t border-slate-800 pt-4">
					{#if acceptedUpload}
						<button
							type="button"
							class="rounded-xl bg-blue-600 px-5 py-2 text-xs font-semibold text-white shadow-md shadow-blue-600/30 hover:bg-blue-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
							onclick={closeModal}
						>
							Done
						</button>
					{:else}
						<button
							type="button"
							class="rounded-xl border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 hover:text-white disabled:opacity-50"
							onclick={closeModal}
							disabled={uploading}
						>
							Cancel
						</button>
						<button
							type="submit"
							disabled={uploading || books.length === 0}
							class="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-xs font-semibold text-white shadow-md shadow-blue-600/30 hover:bg-blue-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{#if uploading}
								<span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent"></span>
								<span>Uploading…</span>
							{:else}
								<span>Upload and queue</span>
							{/if}
						</button>
					{/if}
				</div>
			</form>
		</div>
	</div>
{/if}
