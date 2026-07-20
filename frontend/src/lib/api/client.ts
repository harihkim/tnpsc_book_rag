/**
 * Type-safe API client (openapi-fetch) with graceful mock fallback.
 *
 * - Base URL comes from PUBLIC_API_BASE_URL (api_spec.md §3.1 — never hardcode a host).
 * - Implemented routes are called live; planned routes (search/answers) and any
 *   no-backend session run on mocks that mirror the frozen contract.
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
	Paginated,
	SearchRequest,
	SearchResponse,
	paths
} from './v1';
import { mockAnswerStream, mockBooks, mockCapabilities, mockFilters, mockSearch } from './mocks';

export const apiBaseUrl = ((env.PUBLIC_API_BASE_URL as string | undefined) ?? '').replace(/\/+$/, '');
export const useLiveApi = apiBaseUrl.length > 0;

export const api = createClient<paths>({ baseUrl: apiBaseUrl || 'http://mock.local' });

/* ------------------------------ Catalog -------------------------------- */

export async function getCapabilities(): Promise<Capabilities> {
	if (!useLiveApi) return mockCapabilities;
	const { data } = await api.GET('/v1/capabilities');
	return data ?? mockCapabilities;
}

export async function getCatalogFilters(): Promise<CatalogFilters> {
	if (!useLiveApi) return mockFilters;
	const { data } = await api.GET('/v1/catalog/filters');
	return data ?? mockFilters;
}

export async function getBooks(query?: {
	standard?: number[];
	subject?: string[];
	q?: string;
}): Promise<Paginated<Book>> {
	if (!useLiveApi) {
		let items = mockBooks;
		if (query?.q) items = items.filter((b) => b.title.toLowerCase().includes(query.q!.toLowerCase()));
		if (query?.standard?.length) items = items.filter((b) => query.standard!.includes(b.standard));
		if (query?.subject?.length) items = items.filter((b) => query.subject!.includes(b.subject));
		return { items, next_cursor: null, count: items.length };
	}
	const { data } = await api.GET('/v1/books', {
		params: { query: { ...query, limit: 50, include_count: true } as never }
	});
	return data ?? { items: [], next_cursor: null };
}

/* ------------------------------ Search --------------------------------- */

export async function search(req: SearchRequest): Promise<SearchResponse> {
	if (!useLiveApi) return mockSearch(req);
	const { data } = await api.POST('/v1/search', { body: req });
	return data ?? { results: [], request_id: crypto.randomUUID() };
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
	if (!useLiveApi) {
		yield* mockAnswerStream(req);
		return;
	}

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
