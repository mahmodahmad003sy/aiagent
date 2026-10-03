import { WEBUI_API_BASE_URL } from '$lib/constants';

export type CrawlFileType = 'pdf' | 'docx' | 'xlsx' | 'csv' | 'txt' | 'pptx';

export const SUPPORTED_CRAWL_FILE_TYPES: CrawlFileType[] = [
	'pdf',
	'docx',
	'xlsx',
	'csv',
	'txt',
	'pptx'
];

export type CrawlSettings = {
	start_url: string;
	max_depth: number;
	max_pages: number;
	same_domain_only: boolean;
	follow_sitemap: boolean;
	respect_robots: boolean;
	discover_files: boolean;
	include_paths: string[];
	exclude_paths: string[];
	allowed_file_types: CrawlFileType[];
	max_file_size_mb: number;
	max_total_size_mb: number;
	request_timeout: number;
	request_delay_ms: number;
	max_concurrency: number;
};

// Must match backend ChatWidgetCrawlSettings defaults exactly.
export const DEFAULT_CRAWL_SETTINGS: CrawlSettings = {
	start_url: '',
	max_depth: 2,
	max_pages: 100,
	same_domain_only: true,
	follow_sitemap: true,
	respect_robots: true,
	discover_files: true,
	include_paths: [],
	exclude_paths: [],
	allowed_file_types: [...SUPPORTED_CRAWL_FILE_TYPES],
	max_file_size_mb: 20,
	max_total_size_mb: 500,
	request_timeout: 20,
	request_delay_ms: 500,
	max_concurrency: 2
};

export type CrawlConfig = {
	id: string;
	widget_id: string;
	settings: CrawlSettings;
	created_at: number;
	updated_at: number;
};

export type CrawlJobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type CrawlRun = {
	id: string;
	widget_id: string;
	user_id: string;
	settings: CrawlSettings;
	status: CrawlJobStatus;
	progress: Record<string, any>;
	error?: string | null;
	cancel_requested: boolean;
	heartbeat_at?: number | null;
	started_at?: number | null;
	finished_at?: number | null;
	extend_status?: CrawlJobStatus | null;
	extend_progress: Record<string, any>;
	extend_error?: string | null;
	extend_started_at?: number | null;
	extend_finished_at?: number | null;
	created_at: number;
};

export type CrawlSummary = {
	pages: number;
	files: number;
	resources: number;
	errors: number;
	selected_pages: number;
	selectable_pages: number;
	selected_files: number;
	selectable_files: number;
};

export type CrawlState = {
	config: CrawlConfig | null;
	current_run: CrawlRun | null;
	results_run: CrawlRun | null;
	summary: CrawlSummary | null;
	knowledge_id: string | null;
	knowledge_item_count: number;
};

export type CrawlItemKind = 'page' | 'file' | 'resource' | 'error';

export type CrawlItem = {
	id: string;
	run_id: string;
	kind: CrawlItemKind;
	url: string;
	title?: string | null;
	name?: string | null;
	file_type?: string | null;
	size?: number | null;
	depth?: number | null;
	found_on?: string | null;
	found_on_title?: string | null;
	link_text?: string | null;
	context?: string | null;
	status: string;
	http_status?: number | null;
	selected: boolean;
	extract_status?: string | null;
	extract_error?: string | null;
};

export type CrawlSelectionForm = {
	selected: boolean;
	item_ids: string[] | null;
	kind: 'page' | 'file' | null;
};

// Builds settings in a fixed key order so two settings objects can be compared with JSON.stringify.
export const canonicalCrawlSettings = (settings: Partial<CrawlSettings>): CrawlSettings => {
	const fileTypes = settings.allowed_file_types ?? DEFAULT_CRAWL_SETTINGS.allowed_file_types;
	return {
		start_url: (settings.start_url ?? '').trim(),
		max_depth: Number(settings.max_depth ?? DEFAULT_CRAWL_SETTINGS.max_depth),
		max_pages: Number(settings.max_pages ?? DEFAULT_CRAWL_SETTINGS.max_pages),
		same_domain_only: settings.same_domain_only ?? DEFAULT_CRAWL_SETTINGS.same_domain_only,
		follow_sitemap: settings.follow_sitemap ?? DEFAULT_CRAWL_SETTINGS.follow_sitemap,
		respect_robots: settings.respect_robots ?? DEFAULT_CRAWL_SETTINGS.respect_robots,
		discover_files: settings.discover_files ?? DEFAULT_CRAWL_SETTINGS.discover_files,
		include_paths: [...(settings.include_paths ?? [])],
		exclude_paths: [...(settings.exclude_paths ?? [])],
		allowed_file_types: SUPPORTED_CRAWL_FILE_TYPES.filter((type) => fileTypes.includes(type)),
		max_file_size_mb: Number(settings.max_file_size_mb ?? DEFAULT_CRAWL_SETTINGS.max_file_size_mb),
		max_total_size_mb: Number(
			settings.max_total_size_mb ?? DEFAULT_CRAWL_SETTINGS.max_total_size_mb
		),
		request_timeout: Number(settings.request_timeout ?? DEFAULT_CRAWL_SETTINGS.request_timeout),
		request_delay_ms: Number(settings.request_delay_ms ?? DEFAULT_CRAWL_SETTINGS.request_delay_ms),
		max_concurrency: Number(settings.max_concurrency ?? DEFAULT_CRAWL_SETTINGS.max_concurrency)
	};
};

const parseError = async (res: Response) => {
	try {
		const json = await res.json();
		const detail = json?.detail ?? json;
		if (Array.isArray(detail)) {
			return detail.map((item) => item?.msg ?? JSON.stringify(item)).join(', ');
		}
		return detail;
	} catch {
		return res.statusText;
	}
};

const request = async <T>(
	token: string,
	path: string,
	method = 'GET',
	body?: unknown
): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets/${path}`, {
		method,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!res.ok) throw await parseError(res);
	return res.json();
};

export const getWidgetCrawlState = (token: string, widgetId: string) =>
	request<CrawlState>(token, `${encodeURIComponent(widgetId)}/crawl/state`);

export const saveWidgetCrawlConfig = (token: string, widgetId: string, settings: CrawlSettings) =>
	request<CrawlConfig>(token, `${encodeURIComponent(widgetId)}/crawl/config`, 'PUT', settings);

export const startWidgetCrawl = (token: string, widgetId: string) =>
	request<CrawlRun>(token, `${encodeURIComponent(widgetId)}/crawl/runs`, 'POST');

export const getWidgetCrawlItems = (token: string, widgetId: string, runId: string) =>
	request<CrawlItem[]>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/items`
	);

export const setWidgetCrawlSelection = (
	token: string,
	widgetId: string,
	runId: string,
	form: CrawlSelectionForm
) =>
	request<CrawlSummary>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/selection`,
		'POST',
		form
	);

export const cancelWidgetCrawlRun = (token: string, widgetId: string, runId: string) =>
	request<CrawlRun>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/cancel`,
		'POST'
	);

export const extendWidgetKnowledge = (token: string, widgetId: string, runId: string) =>
	request<CrawlRun>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/extend`,
		'POST'
	);
