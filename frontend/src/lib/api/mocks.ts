/**
 * Realistic mocks for the API v1 routes that are still `planned` (api_spec.md §1),
 * plus a drop-in data source for the implemented catalog routes when no backend
 * base URL is configured. Shapes mirror the frozen contract exactly so swapping
 * to the live backend is a config change, not a refactor.
 */
import type {
	Answer,
	AnswerRequest,
	AnswerStreamEvent,
	Asset,
	Block,
	Book,
	Capabilities,
	CatalogFilters,
	SearchRequest,
	SearchResponse
} from './v1';

/* ----------------------------- Catalog mocks ---------------------------- */

export const mockBooks: Book[] = [
	{ id: '3c508224-5f38-4721-b22c-31f9a043e877', title: 'Science — Standard 8', standard: 8, subject: 'Science', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:30:00Z' },
	{ id: '7a1c9e2b-4f6d-4a8f-9c3e-2b5d8f1a7c9e', title: 'Mathematics — Standard 9', standard: 9, subject: 'Mathematics', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:31:00Z' },
	{ id: '9d4f7b3a-1c8e-4d2b-8a5f-3e6c9b2d4f7a', title: 'Social Science — Standard 10', standard: 10, subject: 'Social Science', language: 'english', edition: '2024–2025', created_at: '2026-07-15T09:32:00Z' },
	{ id: '2b6e9c4d-8a1f-4b3c-9d5e-7f2a4c6b8d1e', title: 'English — Standard 7', standard: 7, subject: 'English', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:33:00Z' },
	{ id: '5f8a2d6c-3e9b-4c1d-8a7f-2b4e6d8c1a3f', title: 'Science — Standard 10', standard: 10, subject: 'Science', language: 'english', edition: '2024–2025', created_at: '2026-07-15T09:34:00Z' },
	{ id: '8c3e7a1f-9d2b-4e6c-a4f8-1c5b9e3d7a2f', title: 'Mathematics — Standard 6', standard: 6, subject: 'Mathematics', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:35:00Z' },
	{ id: '1e5b8d2c-7a4f-4b9e-8c3d-6a2f4b8e1c5d', title: 'Computer Applications — Standard 8', standard: 8, subject: 'Computer Applications', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:36:00Z' },
	{ id: '4d9c2f6a-8b3e-4a7d-9c1f-5b8e2d4a6c9f', title: 'Social Science — Standard 8', standard: 8, subject: 'Social Science', language: 'english', edition: '2025–2026', created_at: '2026-07-15T09:37:00Z' }
];

export const mockCapabilities: Capabilities = {
	answer_streaming: true,
	answer_modes: ['textbook_only', 'textbook_plus_general'],
	max_top_k: 20,
	answer_retention_seconds: 86400
};

export const mockFilters: CatalogFilters = {
	standards: [6, 7, 8, 9, 10],
	subjects: ['Science', 'Mathematics', 'Social Science', 'English', 'Computer Applications']
};

/* ----------------------------- Asset mocks ------------------------------ */

const pressureFigure: Asset = {
	asset_id: 'd8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7',
	kind: 'figure',
	alt_text: 'Diagram comparing the contact area of a sharp knife and a blunt knife under the same force.',
	pixel_width: 1280,
	pixel_height: 668,
	content_url: '/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/content',
	thumbnail_url: '/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/thumbnail',
	thumbnail_pixel_width: 640,
	thumbnail_pixel_height: 334
};

/* ----------------------------- Search mock ------------------------------ */

export function mockSearch(req: SearchRequest): SearchResponse {
	const q = req.query.toLowerCase();
	const results = [
		{
			rank: 1,
			score: 0.91,
			chunk_id: 'fda7e283-d42f-4b17-8a17-34cce0f35a01',
			document_id: '2e55606d-d0e1-4bbd-9052-1a39dd71a56a',
			book_id: '3c508224-5f38-4721-b22c-31f9a043e877',
			book_title: 'Science — Standard 8',
			standard: 8 as const,
			subject: 'Science',
			pdf_page_index: 17,
			printed_page_label: '12',
			section_path: ['Force and Pressure', 'Pressure'],
			content_type: 'prose' as const,
			text: 'A sharp knife has a smaller contact area and therefore produces more pressure for the same force. Pressure is the force acting per unit area.',
			assets: [pressureFigure],
			source_url: '/v1/sources/fda7e283-d42f-4b17-8a17-34cce0f35a01'
		},
		{
			rank: 2,
			score: 0.84,
			chunk_id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
			document_id: '2e55606d-d0e1-4bbd-9052-1a39dd71a56a',
			book_id: '3c508224-5f38-4721-b22c-31f9a043e877',
			book_title: 'Science — Standard 8',
			standard: 8 as const,
			subject: 'Science',
			pdf_page_index: 18,
			printed_page_label: '13',
			section_path: ['Force and Pressure', 'Pressure in liquids'],
			content_type: 'prose' as const,
			text: 'Liquids exert pressure in all directions. The pressure increases with depth because the weight of the liquid above increases.',
			assets: [],
			source_url: '/v1/sources/a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d'
		},
		{
			rank: 3,
			score: 0.77,
			chunk_id: 'b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e',
			document_id: '9f8e7d6c-5b4a-4321-8765-432109876543',
			book_id: '7a1c9e2b-4f6d-4a8f-9c3e-2b5d8f1a7c9e',
			book_title: 'Mathematics — Standard 9',
			standard: 9 as const,
			subject: 'Mathematics',
			pdf_page_index: 102,
			printed_page_label: '96',
			section_path: ['Mensuration', 'Surface area and volume'],
			content_type: 'prose' as const,
			text: 'The pressure exerted by a solid depends on the area of contact; this idea recurs when we compare force distributed over different surfaces.',
			assets: [],
			source_url: '/v1/sources/b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e'
		}
	].filter((r) => q.length === 0 || /pressure|force|knife|cut|area/i.test(q) || r.rank <= 2);

	return { results: results.slice(0, req.top_k ?? 10), request_id: crypto.randomUUID() };
}

/* ----------------------------- Answer mock ------------------------------ */

const knifeBlocks: Block[] = [
	{
		type: 'paragraph',
		nodes: [
			{
				type: 'text',
				content:
					'A sharp knife concentrates the applied force over a much smaller contact area. Because pressure is force divided by area, the same push produces far greater pressure at the edge, so the material parts more easily. '
			},
			{ type: 'citation', citation_id: 'T1', fallback_text: '[T1]' }
		]
	},
	{
		type: 'paragraph',
		nodes: [
			{
				type: 'text',
				content:
					'A blunt knife spreads that same force over a larger area, producing less pressure, which is why it crushes rather than cuts. '
			},
			{ type: 'citation', citation_id: 'T2', fallback_text: '[T2]' }
		]
	},
	{
		type: 'bullet_list',
		items: [
			[
				{ type: 'text', content: 'Pressure = Force ÷ Area — smaller area, larger pressure. ' },
				{ type: 'citation', citation_id: 'T1', fallback_text: '[T1]' }
			],
			[
				{ type: 'text', content: 'The textbook illustrates this with a sharp vs. blunt blade diagram. ' },
				{ type: 'citation', citation_id: 'T1', fallback_text: '[T1]' }
			]
		]
	}
];

const knifeCitations = [
	{
		citation_id: 'T1',
		chunk_id: 'fda7e283-d42f-4b17-8a17-34cce0f35a01',
		page_id: '0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9',
		document_id: '2e55606d-d0e1-4bbd-9052-1a39dd71a56a',
		book_id: '3c508224-5f38-4721-b22c-31f9a043e877',
		book_title: 'Science — Standard 8',
		edition: '2025–2026',
		standard: 8 as const,
		subject: 'Science',
		pdf_page_index: 17,
		printed_page_label: '12',
		section_path: ['Force and Pressure', 'Pressure'],
		content_type: 'prose' as const,
		text: 'A sharp knife has a smaller contact area and therefore produces more pressure for the same force.',
		assets: [pressureFigure],
		source_url: '/v1/sources/fda7e283-d42f-4b17-8a17-34cce0f35a01'
	},
	{
		citation_id: 'T2',
		chunk_id: 'c3d4e5f6-a7b8-4c9d-8e1f-2a3b4c5d6e7f',
		page_id: '1517f0ad-8966-4c5a-9d2e-3b4c5d6e7f80',
		document_id: '2e55606d-d0e1-4bbd-9052-1a39dd71a56a',
		book_id: '3c508224-5f38-4721-b22c-31f9a043e877',
		book_title: 'Science — Standard 8',
		edition: '2025–2026',
		standard: 8 as const,
		subject: 'Science',
		pdf_page_index: 18,
		printed_page_label: '13',
		section_path: ['Force and Pressure', 'Applications of pressure'],
		content_type: 'prose' as const,
		text: 'A blunt blade exerts the same force over a larger area, producing less pressure and crushing the material instead of slicing it.',
		assets: [],
		source_url: '/v1/sources/c3d4e5f6-a7b8-4c9d-8e1f-2a3b4c5d6e7f'
	}
];

export function mockAnswer(req: AnswerRequest): Answer {
	const supplementary =
		req.mode === 'textbook_plus_general'
			? {
					kind: 'general_knowledge' as const,
					blocks: [
						{
							type: 'paragraph' as const,
							nodes: [
								{
									type: 'text' as const,
									content:
										'In material science, edge geometry, blade stiffness and friction also affect cutting performance — a sharper edge also reduces the force needed to start a crack in the material.'
								}
							]
						}
					]
				}
			: null;

	return {
		answer_id: '895e220e-f9d2-4950-a2cb-07af92bf2b32',
		query: req.query,
		mode: req.mode,
		textbook: { status: 'answered', blocks: knifeBlocks, citations: knifeCitations },
		supplementary,
		request_id: crypto.randomUUID(),
		created_at: new Date().toISOString()
	};
}

/* ------------------------ SSE stream simulation ------------------------- */

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Concatenate the plain-text content of blocks (for the provisional preview). */
export function plainTextOf(blocks: Block[]): string {
	const parts: string[] = [];
	for (const block of blocks) {
		if (block.type === 'paragraph') {
			parts.push(block.nodes.filter((n) => n.type === 'text').map((n) => (n as { content: string }).content).join(''));
		} else {
			for (const item of block.items) {
				parts.push('• ' + item.filter((n) => n.type === 'text').map((n) => (n as { content: string }).content).join(''));
			}
		}
	}
	return parts.join('\n');
}

/**
 * Simulate the POST /v1/answers SSE sequence (spec §11):
 * started → progress(retrieval) → progress(generation) → delta… → completed.
 */
export async function* mockAnswerStream(req: AnswerRequest): AsyncGenerator<AnswerStreamEvent> {
	const answer = mockAnswer(req);
	yield { type: 'started', answer_id: answer.answer_id, request_id: answer.request_id };
	await sleep(350);
	yield { type: 'progress', stage: 'retrieval' };
	await sleep(500);
	yield { type: 'progress', stage: 'generation' };

	const full = plainTextOf(answer.textbook.blocks);
	const words = full.split(' ');
	let acc = '';
	for (let i = 0; i < words.length; i += 4) {
		const chunk = words.slice(i, i + 4).join(' ') + ' ';
		acc += chunk;
		yield { type: 'delta', section: 'textbook', content: chunk, provisional: true };
		await sleep(60);
	}

	await sleep(250);
	yield { type: 'progress', stage: 'validation' };
	await sleep(300);
	yield { type: 'completed', answer };
}
