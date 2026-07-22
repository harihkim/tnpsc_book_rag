/**
 * Hand-written subset of the frozen API v1 contract (openapi.v1.yaml).
 *
 * This ships so the app type-checks out of the box. For 100% generated types run:
 *   pnpm generate:api   # openapi-typescript ../openapi.v1.yaml -o src/lib/api/v1.generated.d.ts
 * and point `client.ts` at the generated `paths` type.
 *
 * Conventions honored from api_spec.md §3.3:
 *  - snake_case fields, lowercase UUID ids, RFC 3339 UTC timestamps
 *  - `standard` ∈ 6..10, `language` = "english"
 *  - `pdf_page_index` is zero-based; `printed_page_label` may be null
 *  - `score` is a ranking signal, NOT a calibrated confidence
 */

export type Standard = 6 | 7 | 8 | 9 | 10;
export type AnswerMode = 'textbook_only' | 'textbook_plus_general';
export type ResponseLength = 'short' | 'medium' | 'long';

/* ------------------------------- Catalog ------------------------------- */

export interface Book {
	id: string;
	title: string;
	standard: Standard;
	subject: string;
	language: 'english';
	edition: string | null;
	created_at: string;
}

export interface Paginated<T> {
	items: T[];
	next_cursor: string | null;
	count?: number;
}

export interface CatalogFilters {
	standards: Standard[];
	subjects: string[];
}

export interface Capabilities {
	answer_streaming: boolean;
	answer_modes: AnswerMode[];
	max_top_k: number;
	answer_retention_seconds: number;
}

/* ------------------------------- Library ------------------------------- */

export interface LibraryItem {
	document_id: string;
	book_id: string;
	title: string;
	standard: Standard;
	subject: string;
	edition: string;
	publisher: string;
	source_filename: string;
	file_size_bytes: number;
	state: 'uploading' | 'uploaded' | 'extracting' | 'ready' | 'failed';
	page_count: number | null;
	uploaded_at: string;
	active: boolean;
}

export interface LibraryResponse {
	items: LibraryItem[];
}

/* ------------------------------- Assets -------------------------------- */

export interface Asset {
	asset_id: string;
	kind: 'figure' | 'image' | 'table';
	alt_text: string | null;
	pixel_width: number;
	pixel_height: number;
	content_url: string;
	thumbnail_url: string;
	thumbnail_pixel_width: number;
	thumbnail_pixel_height: number;
}

/* ------------------------------- Search -------------------------------- */

export interface SearchFilters {
	standards?: Standard[];
	subjects?: string[];
	book_ids?: string[];
	document_ids?: string[];
}

export interface SearchRequest {
	query: string;
	top_k?: number;
	filters?: SearchFilters;
}

export interface Evidence {
	chunk_id: string;
	document_id: string;
	book_id: string;
	book_title: string;
	standard: Standard;
	subject: string;
	pdf_page_index: number;
	printed_page_label: string | null;
	section_path: string[];
	content_type: 'prose' | 'list' | 'caption' | 'table';
	text: string;
	assets: Asset[];
	source_url: string;
}

export interface SearchResult {
	rank: number;
	/** Ranking signal only — never render as a confidence percentage. */
	score: number;
	evidence: Evidence;
}

export interface SearchResponse {
	results: SearchResult[];
	request_id: string;
}

/* ------------------------------- Answers ------------------------------- */

export interface TextNode {
	type: 'text';
	content: string;
}
export interface CitationNode {
	type: 'citation';
	citation_id: string;
	fallback_text: string;
}
export type InlineNode = TextNode | CitationNode;

export interface ParagraphBlock {
	type: 'paragraph';
	nodes: InlineNode[];
}
export interface BulletListBlock {
	type: 'bullet_list';
	items: InlineNode[][];
}
export type Block = ParagraphBlock | BulletListBlock;

export interface Citation {
	citation_id: string; // "T1", "T2", ...
	chunk_id: string;
	page_id: string;
	document_id: string;
	book_id: string;
	book_title: string;
	edition: string | null;
	standard: Standard;
	subject: string;
	pdf_page_index: number;
	printed_page_label: string | null;
	section_path: string[];
	content_type: 'prose' | 'list' | 'caption' | 'table';
	text: string;
	assets: Asset[];
	source_url: string;
}

export interface TextbookAnswer {
	status: 'answered' | 'insufficient_evidence';
	blocks: Block[];
	citations: Citation[];
}

export interface Supplementary {
	kind: 'general_knowledge';
	blocks: Block[];
}

export interface Answer {
	answer_id: string;
	query: string;
	mode: AnswerMode;
	textbook: TextbookAnswer;
	supplementary: Supplementary | null;
	request_id: string;
	created_at: string;
}

export interface AnswerRequest {
	query: string;
	mode: AnswerMode;
	top_k?: number;
	response_length?: ResponseLength;
	filters?: SearchFilters;
}

/* --------------------------- SSE event stream -------------------------- */
/* POST /v1/answers with `Accept: text/event-stream` (spec §11).           */

export type AnswerStreamEvent =
	| { type: 'started'; answer_id: string; request_id: string }
	| { type: 'progress'; stage: 'retrieval' | 'augmentation' | 'generation' | 'validation' }
	| { type: 'delta'; section: 'textbook' | 'supplementary'; content: string; provisional: boolean }
	| { type: 'reset'; reason: string }
	| { type: 'completed'; answer: Answer }
	| { type: 'failed'; detail: string };

/* --------------------------- openapi-fetch paths ----------------------- */

export interface paths {
	'/v1/capabilities': {
		get: {
			responses: { 200: { content: { 'application/json': Capabilities } } };
		};
	};
	'/v1/catalog/filters': {
		get: {
			responses: { 200: { content: { 'application/json': CatalogFilters } } };
		};
	};
	'/v1/library': {
		get: {
			responses: { 200: { content: { 'application/json': LibraryResponse } } };
		};
	};
	'/v1/books': {
		get: {
			parameters: {
				query?: {
					standard?: Standard[];
					subject?: string[];
					q?: string;
					limit?: number;
					cursor?: string;
					include_count?: boolean;
				};
			};
			responses: { 200: { content: { 'application/json': Paginated<Book> } } };
		};
	};
	'/v1/books/{book_id}': {
		get: {
			parameters: { path: { book_id: string } };
			responses: { 200: { content: { 'application/json': Book } } };
		};
	};
	'/v1/search': {
		post: {
			requestBody: { content: { 'application/json': SearchRequest } };
			responses: { 200: { content: { 'application/json': SearchResponse } } };
		};
	};
	'/v1/answers': {
		post: {
			requestBody: { content: { 'application/json': AnswerRequest } };
			responses: { 200: { content: { 'application/json': Answer } } };
		};
	};
}
