/**
 * Type-safe API client (openapi-fetch).
 *
 * - Base URL comes from PUBLIC_API_BASE_URL (api_spec.md §3.1 — never hardcode a host).
 * - All routes call the live backend. No mock fallback.
 */
import createClient from 'openapi-fetch';
import { env } from '$env/dynamic/public';
import type {
	Answer,
	AnswerRequest,
	AnswerStreamEvent,
	Book,
	Capabilities,
	CatalogFilters,
	DocumentUploadAccepted,
	LibraryItem,
	LibraryResponse,
	Paginated,
	Problem,
	SearchRequest,
	SearchResponse,
	paths
} from './v1';

export const apiBaseUrl = ((env.PUBLIC_API_BASE_URL as string | undefined) ?? '').replace(/\/+$/, '');

if (!apiBaseUrl) {
	console.warn('[LearnFlow] PUBLIC_API_BASE_URL is not set — API calls will fail.');
}

export const api = createClient<paths>({ baseUrl: apiBaseUrl });

type AccessTokenProvider = () => string | null | Promise<string | null>;
let accessTokenProvider: AccessTokenProvider | null = null;

/**
 * Connect the API client to the app's OIDC session without storing a curator
 * token in public build-time configuration.
 */
export function setAccessTokenProvider(provider: AccessTokenProvider | null): void {
	accessTokenProvider = provider;
}

async function authorizationHeaders(): Promise<Record<string, string>> {
	const token = await accessTokenProvider?.();
	return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiProblemError extends Error {
	constructor(
		public readonly status: number,
		public readonly problem: Problem | null
	) {
		super(problem?.detail ?? `API request failed (${status})`);
		this.name = 'ApiProblemError';
	}
}

async function problemFromResponse(response: Response): Promise<Problem | null> {
	try {
		return (await response.json()) as Problem;
	} catch {
		return null;
	}
}

function idempotencyKey(): string {
	return `web-upload-${crypto.randomUUID()}`;
}

/* ------------------------------ Catalog -------------------------------- */

export async function getCapabilities(): Promise<Capabilities> {
	const { data, error } = await api.GET('/v1/capabilities');
	if (error) throw new Error(`Failed to fetch capabilities: ${JSON.stringify(error)}`);
	return data!;
}

export async function getCatalogFilters(): Promise<CatalogFilters> {
	const { data, error } = await api.GET('/v1/catalog/filters');
	if (error) throw new Error(`Failed to fetch catalog filters: ${JSON.stringify(error)}`);
	return data!;
}

export async function getBooks(query?: {
	standard?: number[];
	subject?: string[];
	q?: string;
}): Promise<Paginated<Book>> {
	const { data, error } = await api.GET('/v1/books', {
		params: { query: { ...query, limit: 50, include_count: true } as never }
	});
	if (error) throw new Error(`Failed to fetch books: ${JSON.stringify(error)}`);
	return data!;
}

export async function getLibrary(): Promise<LibraryItem[]> {
	const { data, error } = await api.GET('/v1/library');
	if (error) throw new Error(`Failed to fetch library: ${JSON.stringify(error)}`);
	return data!.items;
}

/**
 * Upload one PDF to an existing catalog book. FormData sets its own multipart
 * boundary, so Content-Type must not be supplied manually.
 */
export async function uploadBookDocument(input: {
	bookId: string;
	file: File;
	edition: string;
}): Promise<DocumentUploadAccepted> {
	const body = new FormData();
	body.append('file', input.file, input.file.name);
	body.append('edition', input.edition.trim());

	const response = await fetch(
		`${apiBaseUrl}/v1/books/${encodeURIComponent(input.bookId)}/documents`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Idempotency-Key': idempotencyKey(),
				...(await authorizationHeaders())
			},
			body
		}
	);

	if (!response.ok) {
		throw new ApiProblemError(response.status, await problemFromResponse(response));
	}

	return (await response.json()) as DocumentUploadAccepted;
}

/* ------------------------------ Search --------------------------------- */

export async function search(req: SearchRequest): Promise<SearchResponse> {
	const { data, error } = await api.POST('/v1/search', { body: req });
	if (error) throw new Error(`Search failed: ${JSON.stringify(error)}`);
	return data!;
}

/* --------------------------- Answer streaming -------------------------- */

/** Parse a text/event-stream body into {event, data} frames. */
async function* sseFrames(res: Response): AsyncGenerator<{ event: string; data: string }> {
	const reader = res.body!.getReader();
	const decoder = new TextDecoder();
	let buf = '';
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		buf += decoder.decode(value, { stream: true });
		let sep: number;
		while ((sep = buf.indexOf('\n\n')) !== -1) {
			const raw = buf.slice(0, sep);
			buf = buf.slice(sep + 2);
			let event = 'message';
			let data = '';
			for (const line of raw.split('\n')) {
				if (line.startsWith('event:')) event = line.slice(6).trim();
				else if (line.startsWith('data:')) data += line.slice(5).trim();
			}
			if (data) yield { event, data };
		}
	}
}

function mapSseEvent(event: string, data: string): AnswerStreamEvent | null {
	try {
		const payload = JSON.parse(data);
		switch (event) {
			case 'answer.started':
				return { type: 'started', answer_id: payload.answer_id, request_id: payload.request_id };
			case 'answer.progress':
				return { type: 'progress', stage: payload.stage };
			case 'answer.delta':
				return { type: 'delta', section: payload.section, content: payload.content, provisional: payload.provisional };
			case 'answer.reset':
				return { type: 'reset', reason: payload.reason };
			case 'answer.completed':
				return { type: 'completed', answer: payload as Answer };
			case 'answer.failed':
				return { type: 'failed', detail: payload.detail ?? 'generation failed' };
			default:
				return null; // ignore unknown non-terminal events (forward-compat, spec §11)
		}
	} catch {
		return { type: 'failed', detail: 'malformed SSE payload' };
	}
}

/**
 * Stream an answer. Uses fetch + ReadableStream (NOT EventSource — this is a POST
 * with a JSON body, per spec §11). Pass an AbortSignal to cancel intentionally.
 */
export async function* streamAnswer(
	req: AnswerRequest,
	signal?: AbortSignal
): AsyncGenerator<AnswerStreamEvent> {
	const res = await fetch(`${apiBaseUrl}/v1/answers`, {
		method: 'POST',
		signal,
		headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
		body: JSON.stringify(req)
	});

	if (!res.ok || !res.body) {
		yield { type: 'failed', detail: `answer request failed (${res.status})` };
		return;
	}

	for await (const frame of sseFrames(res)) {
		const mapped = mapSseEvent(frame.event, frame.data);
		if (mapped) yield mapped;
	}
}
