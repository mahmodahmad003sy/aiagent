<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';

	import type { ChatWidget } from '$lib/apis/widgets';
	import {
		DEFAULT_CRAWL_SETTINGS,
		SUPPORTED_CRAWL_FILE_TYPES,
		canonicalCrawlSettings,
		cancelWidgetCrawlRun,
		extendWidgetKnowledge,
		getWidgetCrawlItems,
		getWidgetCrawlState,
		saveWidgetCrawlConfig,
		setWidgetCrawlSelection,
		startWidgetCrawl,
		type CrawlFileType,
		type CrawlItem,
		type CrawlItemKind,
		type CrawlSettings,
		type CrawlState
	} from '$lib/apis/widgets/crawl';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	export let widget: ChatWidget;

	const i18n = getContext<Writable<i18nType>>('i18n');

	const POLL_INTERVAL_MS = 2000;
	const PAGE_SIZE = 100;
	const ACTIVE_STATUSES = ['pending', 'running'];

	const inputClass =
		'w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 disabled:opacity-60 dark:border-gray-800';
	const labelClass = 'mb-1 text-xs font-medium text-gray-600 dark:text-gray-400';
	const primaryButtonClass =
		'rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100';
	const secondaryButtonClass =
		'rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-800 dark:hover:bg-gray-850';
	const dangerButtonClass =
		'rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900 dark:hover:bg-red-950';

	const TABS: { kind: CrawlItemKind; label: string }[] = [
		{ kind: 'page', label: 'Pages' },
		{ kind: 'file', label: 'Files' },
		{ kind: 'resource', label: 'Other resources' },
		{ kind: 'error', label: 'Errors' }
	];

	const STATUS_LABELS: Record<string, string> = {
		ok: 'OK',
		supported: 'Supported',
		too_large: 'Too large',
		not_a_file: 'Not a file (HTML page)',
		robots_disallowed: 'Blocked by robots.txt',
		http_error: 'HTTP error',
		timeout: 'Timeout',
		blocked: 'Blocked or unresolvable address',
		connection_error: 'Connection error',
		too_many_redirects: 'Too many redirects',
		redirect_off_site: 'Redirected to another site'
	};

	const EXTRACT_LABELS: Record<string, string> = {
		embedded: 'Embedded',
		unchanged: 'Embedded (unchanged)',
		no_text: 'No extractable text found',
		failed: 'Extraction failed',
		skipped_limit: 'Skipped (total size limit)'
	};

	const JOB_STATUS_LABELS: Record<string, string> = {
		pending: 'Queued',
		running: 'Running',
		completed: 'Completed',
		failed: 'Failed',
		cancelled: 'Cancelled'
	};

	const PHASE_LABELS: Record<string, string> = {
		starting: 'Starting',
		sitemap: 'Reading sitemap',
		pages: 'Crawling pages',
		files: 'Checking files',
		saving: 'Saving results',
		done: 'Done'
	};

	const LIMIT_LABELS: Record<string, string> = {
		max_pages: 'Maximum pages reached. Some pages were not crawled.',
		max_total_size: 'Maximum total download size reached. Some pages were not crawled.',
		max_linked_items: 'Maximum number of linked files reached. Some files were not recorded.'
	};

	const WARNING_STATUSES = ['too_large', 'not_a_file', 'robots_disallowed'];
	const WARNING_EXTRACT_STATUSES = ['no_text', 'skipped_limit'];

	let loaded = false;
	let crawlState: CrawlState | null = null;
	let items: CrawlItem[] = [];
	let itemsKey = '';
	let settings: CrawlSettings = canonicalCrawlSettings(DEFAULT_CRAWL_SETTINGS);
	let includePathsText = '';
	let excludePathsText = '';
	let saving = false;
	let starting = false;
	let extending = false;
	let cancelling = false;
	let activeTab: CrawlItemKind = 'page';
	let search = '';
	let visibleCount = PAGE_SIZE;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	const parseLines = (value: string) =>
		value
			.split('\n')
			.map((line) => line.trim())
			.filter((line, index, all) => line && all.indexOf(line) === index);

	$: formSettings = canonicalCrawlSettings({
		...settings,
		include_paths: parseLines(includePathsText),
		exclude_paths: parseLines(excludePathsText)
	});
	$: savedSettings = crawlState?.config ? canonicalCrawlSettings(crawlState.config.settings) : null;
	$: formDirty = !savedSettings || JSON.stringify(formSettings) !== JSON.stringify(savedSettings);
	$: currentRun = crawlState?.current_run ?? null;
	$: resultsRun = crawlState?.results_run ?? null;
	$: summary = crawlState?.summary ?? null;
	$: crawlActive = !!currentRun && ACTIVE_STATUSES.includes(currentRun.status);
	$: extendActive = !!resultsRun && ACTIVE_STATUSES.includes(resultsRun.extend_status ?? '');
	$: jobActive = crawlActive || extendActive;
	$: settingsChangedSinceCrawl =
		!!resultsRun &&
		!!savedSettings &&
		JSON.stringify(canonicalCrawlSettings(resultsRun.settings)) !== JSON.stringify(savedSettings);
	$: canExtend =
		!!resultsRun && !jobActive && !formDirty && !settingsChangedSinceCrawl && !extending;
	$: tabCounts = {
		page: items.filter((item) => item.kind === 'page').length,
		file: items.filter((item) => item.kind === 'file').length,
		resource: items.filter((item) => item.kind === 'resource').length,
		error: items.filter((item) => item.kind === 'error').length
	};
	$: tabItems = items.filter((item) => item.kind === activeTab);
	$: searchTerm = search.trim().toLowerCase();
	$: filteredItems = searchTerm
		? tabItems.filter((item) =>
				`${item.title ?? ''} ${item.name ?? ''} ${item.url}`.toLowerCase().includes(searchTerm)
			)
		: tabItems;
	$: visibleItems = filteredItems.slice(0, visibleCount);

	const isSelectable = (item: CrawlItem) =>
		(item.kind === 'page' && item.status === 'ok') ||
		(item.kind === 'file' && item.status === 'supported');

	const humanSize = (bytes: number | null | undefined) => {
		if (bytes === null || bytes === undefined) return '—';
		const units = ['B', 'KB', 'MB', 'GB'];
		let value = bytes;
		let unit = 0;
		while (value >= 1024 && unit < units.length - 1) {
			value /= 1024;
			unit += 1;
		}
		return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
	};

	const statusText = (item: CrawlItem) => {
		let text = $i18n.t(STATUS_LABELS[item.status] ?? item.status);
		if (item.http_status) text = `${text} (${item.http_status})`;
		if (item.extract_status) {
			text = `${text} · ${$i18n.t(EXTRACT_LABELS[item.extract_status] ?? item.extract_status)}`;
		}
		return text;
	};

	const statusClass = (item: CrawlItem) => {
		if (item.kind === 'error' || item.extract_status === 'failed') return 'text-red-600';
		if (
			WARNING_STATUSES.includes(item.status) ||
			WARNING_EXTRACT_STATUSES.includes(item.extract_status ?? '')
		) {
			return 'text-amber-600';
		}
		if (item.extract_status === 'embedded' || item.extract_status === 'unchanged') {
			return 'text-green-600';
		}
		return 'text-gray-600 dark:text-gray-400';
	};

	const formatTime = (seconds: number | null | undefined) =>
		seconds ? new Date(seconds * 1000).toLocaleString() : '—';

	const applySettings = (value: CrawlSettings | null) => {
		const fallbackDomain = (widget.allowed_domains ?? []).find(
			(domain) => domain && !domain.startsWith('*')
		);
		const next = canonicalCrawlSettings(
			value ?? {
				...DEFAULT_CRAWL_SETTINGS,
				start_url: fallbackDomain ? `https://${fallbackDomain}` : ''
			}
		);
		settings = next;
		includePathsText = next.include_paths.join('\n');
		excludePathsText = next.exclude_paths.join('\n');
	};

	const toggleFileType = (type: CrawlFileType) => {
		settings = {
			...settings,
			allowed_file_types: settings.allowed_file_types.includes(type)
				? settings.allowed_file_types.filter((value) => value !== type)
				: [...settings.allowed_file_types, type]
		};
	};

	const setTab = (kind: CrawlItemKind) => {
		activeTab = kind;
		visibleCount = PAGE_SIZE;
	};

	const loadItems = async () => {
		if (!crawlState?.results_run) {
			items = [];
			return;
		}
		const res = await getWidgetCrawlItems(
			localStorage.token,
			widget.id,
			crawlState.results_run.id
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res && !destroyed) items = res;
	};

	const schedulePoll = () => {
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = null;
		if (destroyed) return;
		const run = crawlState?.current_run;
		const results = crawlState?.results_run;
		const active =
			(run && ACTIVE_STATUSES.includes(run.status)) ||
			(results && ACTIVE_STATUSES.includes(results.extend_status ?? ''));
		if (active) pollTimer = setTimeout(loadState, POLL_INTERVAL_MS);
	};

	const loadState = async () => {
		const res = await getWidgetCrawlState(localStorage.token, widget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res || destroyed) return;

		const firstLoad = !crawlState;
		crawlState = res;
		if (firstLoad) applySettings(res.config?.settings ?? null);

		const key = res.results_run
			? `${res.results_run.id}:${res.results_run.extend_status ?? ''}:${res.results_run.extend_finished_at ?? ''}`
			: '';
		if (key !== itemsKey) {
			itemsKey = key;
			await loadItems();
		}
		schedulePoll();
	};

	const saveSettings = async (): Promise<boolean> => {
		if (!formSettings.start_url) {
			toast.error($i18n.t('Website URL is required'));
			return false;
		}
		saving = true;
		const res = await saveWidgetCrawlConfig(localStorage.token, widget.id, formSettings).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		saving = false;
		if (!res) return false;
		if (crawlState) crawlState = { ...crawlState, config: res };
		applySettings(res.settings);
		toast.success($i18n.t('Saved'));
		return true;
	};

	const startCrawl = async () => {
		if (jobActive) return;
		if (formDirty && !(await saveSettings())) return;
		starting = true;
		const run = await startWidgetCrawl(localStorage.token, widget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		starting = false;
		if (run) {
			toast.success($i18n.t('Crawl started'));
			await loadState();
		}
	};

	const extendKnowledge = async () => {
		if (!resultsRun || !canExtend) return;
		extending = true;
		const run = await extendWidgetKnowledge(localStorage.token, widget.id, resultsRun.id).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		extending = false;
		if (run) {
			toast.success($i18n.t('Extend Knowledge started'));
			await loadState();
		}
	};

	const cancelJob = async () => {
		const run = crawlActive ? currentRun : extendActive ? resultsRun : null;
		if (!run) return;
		cancelling = true;
		await cancelWidgetCrawlRun(localStorage.token, widget.id, run.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		cancelling = false;
		await loadState();
	};

	const toggleItem = async (item: CrawlItem, selected: boolean) => {
		if (!resultsRun || extendActive || !isSelectable(item)) return;
		const previous = item.selected;
		items = items.map((value) => (value.id === item.id ? { ...value, selected } : value));
		const res = await setWidgetCrawlSelection(localStorage.token, widget.id, resultsRun.id, {
			selected,
			item_ids: [item.id],
			kind: null
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res) {
			items = items.map((value) =>
				value.id === item.id ? { ...value, selected: previous } : value
			);
			return;
		}
		if (crawlState) crawlState = { ...crawlState, summary: res };
	};

	const selectAllInTab = async (selected: boolean) => {
		if (!resultsRun || extendActive) return;
		if (activeTab !== 'page' && activeTab !== 'file') return;
		const kind = activeTab;
		const res = await setWidgetCrawlSelection(localStorage.token, widget.id, resultsRun.id, {
			selected,
			item_ids: null,
			kind
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res) return;
		items = items.map((value) =>
			value.kind === kind && isSelectable(value) ? { ...value, selected } : value
		);
		if (crawlState) crawlState = { ...crawlState, summary: res };
	};

	onMount(async () => {
		await loadState();
		loaded = true;
	});

	onDestroy(() => {
		destroyed = true;
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<section class="mt-3 rounded-lg border border-gray-100 dark:border-gray-850">
	<div
		class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-850"
	>
		<div>
			<div class="text-sm font-medium">{$i18n.t('Website knowledge')}</div>
			<div class="text-xs text-gray-500">
				{$i18n.t('Crawl a website, review what was found, then add it to the widget knowledge.')}
			</div>
		</div>
		{#if crawlState?.knowledge_id}
			<div class="text-xs text-gray-500">
				{crawlState.knowledge_item_count}
				{$i18n.t('items in widget knowledge')}
			</div>
		{/if}
	</div>

	{#if !loaded}
		<div class="flex h-32 items-center justify-center">
			<Spinner />
		</div>
	{:else}
		<div class="space-y-4 p-4">
			<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
				<div class="space-y-3">
					<label class="block">
						<div class={labelClass}>{$i18n.t('Website URL')}</div>
						<input
							class={inputClass}
							bind:value={settings.start_url}
							placeholder="https://example.com"
							disabled={jobActive}
						/>
					</label>

					<div class="grid grid-cols-2 gap-3">
						<label class="block">
							<div class={labelClass}>{$i18n.t('Crawl depth')}</div>
							<input
								type="number"
								min="0"
								max="5"
								class={inputClass}
								bind:value={settings.max_depth}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum pages')}</div>
							<input
								type="number"
								min="1"
								max="1000"
								class={inputClass}
								bind:value={settings.max_pages}
								disabled={jobActive}
							/>
						</label>
					</div>

					<label class="block">
						<div class={labelClass}>{$i18n.t('Include paths')}</div>
						<textarea
							class="{inputClass} min-h-20"
							bind:value={includePathsText}
							placeholder={'/docs\n/blog'}
							disabled={jobActive}
						></textarea>
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t(
								'One path per line. Only pages whose path starts with one of these are crawled. Leave empty to crawl all paths.'
							)}
						</div>
					</label>

					<label class="block">
						<div class={labelClass}>{$i18n.t('Exclude paths')}</div>
						<textarea
							class="{inputClass} min-h-20"
							bind:value={excludePathsText}
							placeholder={'/admin\n/login'}
							disabled={jobActive}
						></textarea>
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('One path per line. Pages whose path starts with one of these are skipped.')}
						</div>
					</label>
				</div>

				<div class="space-y-3">
					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Same domain only')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Only crawl pages on the website domain')}
							</div>
						</div>
						<Switch
							bind:state={settings.same_domain_only}
							ariaLabel={$i18n.t('Same domain only')}
						/>
					</div>

					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Follow sitemap')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Also crawl pages listed in sitemap.xml')}
							</div>
						</div>
						<Switch bind:state={settings.follow_sitemap} ariaLabel={$i18n.t('Follow sitemap')} />
					</div>

					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Respect robots.txt')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Skip URLs the website does not allow crawlers to visit')}
							</div>
						</div>
						<Switch
							bind:state={settings.respect_robots}
							ariaLabel={$i18n.t('Respect robots.txt')}
						/>
					</div>

					<div class="rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850">
						<div class="flex items-center justify-between">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Discover linked files')}</div>
								<div class="text-xs text-gray-500">
									{$i18n.t('Record files and other resources linked from pages')}
								</div>
							</div>
							<Switch
								bind:state={settings.discover_files}
								ariaLabel={$i18n.t('Discover linked files')}
							/>
						</div>
						{#if settings.discover_files}
							<div class="mt-2 flex flex-wrap gap-3">
								{#each SUPPORTED_CRAWL_FILE_TYPES as type (type)}
									<label class="flex items-center gap-1.5 text-xs">
										<input
											type="checkbox"
											checked={settings.allowed_file_types.includes(type)}
											disabled={jobActive}
											on:change={() => toggleFileType(type)}
										/>
										{type.toUpperCase()}
									</label>
								{/each}
							</div>
						{/if}
					</div>

					<div class="grid grid-cols-2 gap-3">
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum file size (MB)')}</div>
							<input
								type="number"
								min="1"
								max="100"
								class={inputClass}
								bind:value={settings.max_file_size_mb}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum total download (MB)')}</div>
							<input
								type="number"
								min="10"
								max="5000"
								class={inputClass}
								bind:value={settings.max_total_size_mb}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Request timeout (seconds)')}</div>
							<input
								type="number"
								min="5"
								max="120"
								class={inputClass}
								bind:value={settings.request_timeout}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Delay between requests (ms)')}</div>
							<input
								type="number"
								min="0"
								max="10000"
								class={inputClass}
								bind:value={settings.request_delay_ms}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Parallel requests')}</div>
							<input
								type="number"
								min="1"
								max="5"
								class={inputClass}
								bind:value={settings.max_concurrency}
								disabled={jobActive}
							/>
						</label>
					</div>
				</div>
			</div>

			<div
				class="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
			>
				<div>
					<span class="font-semibold">{$i18n.t('PDF support:')}</span>
					{$i18n.t(
						'Only extractable text inside PDF files can be added to knowledge. Text inside scanned pages or images is not processed.'
					)}
				</div>
				<div>
					<span class="font-semibold">{$i18n.t('Note:')}</span>
					{$i18n.t('Pages that load their content with JavaScript may appear empty or incomplete.')}
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-2">
				<button
					class={secondaryButtonClass}
					disabled={saving || jobActive || !formDirty}
					on:click={saveSettings}
				>
					{saving ? $i18n.t('Saving...') : $i18n.t('Save settings')}
				</button>
				<button
					class={primaryButtonClass}
					disabled={starting || saving || jobActive}
					on:click={startCrawl}
				>
					{resultsRun ? $i18n.t('Re-crawl') : $i18n.t('Start crawl')}
				</button>
				{#if jobActive}
					<button class={dangerButtonClass} disabled={cancelling} on:click={cancelJob}>
						{$i18n.t('Cancel')}
					</button>
				{/if}
				{#if formDirty && savedSettings}
					<span class="text-xs text-amber-600">{$i18n.t('Unsaved settings')}</span>
				{/if}
			</div>

			{#if currentRun && currentRun.id !== resultsRun?.id}
				<div class="rounded-lg border border-gray-100 px-3 py-2 text-sm dark:border-gray-850">
					<div class="flex items-center gap-2">
						{#if crawlActive}
							<Spinner className="size-4" />
						{/if}
						<span class="font-medium">
							{$i18n.t('Crawl')}: {$i18n.t(
								JOB_STATUS_LABELS[currentRun.status] ?? currentRun.status
							)}
						</span>
						{#if crawlActive && currentRun.progress?.phase}
							<span class="text-gray-500">
								· {$i18n.t(PHASE_LABELS[currentRun.progress.phase] ?? currentRun.progress.phase)}
							</span>
						{/if}
					</div>
					{#if crawlActive}
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('Pages')}: {currentRun.progress?.pages ?? 0} · {$i18n.t('Files')}:
							{currentRun.progress?.files ?? 0} · {$i18n.t('Other resources')}:
							{currentRun.progress?.resources ?? 0} · {$i18n.t('Errors')}:
							{currentRun.progress?.errors ?? 0} · {$i18n.t('Downloaded')}:
							{humanSize(currentRun.progress?.bytes_downloaded ?? 0)}
						</div>
					{/if}
					{#if currentRun.status === 'failed' && currentRun.error}
						<div class="mt-1 text-xs text-red-600">{currentRun.error}</div>
					{/if}
					{#if currentRun.status === 'cancelled'}
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('The crawl was cancelled. Previous results are kept.')}
						</div>
					{/if}
				</div>
			{/if}

			{#if resultsRun && summary}
				<div class="rounded-lg border border-gray-100 dark:border-gray-850">
					<div
						class="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-3 py-3 dark:border-gray-850"
					>
						<div class="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
							<div>{$i18n.t('Pages')}: <span class="font-medium">{summary.pages}</span></div>
							<div>
								{$i18n.t('Supported files')}: <span class="font-medium">{summary.files}</span>
							</div>
							<div>
								{$i18n.t('Other resources')}: <span class="font-medium">{summary.resources}</span>
							</div>
							<div>{$i18n.t('Errors')}: <span class="font-medium">{summary.errors}</span></div>
							<div>
								{$i18n.t('Selected pages')}:
								<span class="font-medium"
									>{summary.selected_pages} / {summary.selectable_pages}</span
								>
							</div>
							<div>
								{$i18n.t('Selected files')}:
								<span class="font-medium"
									>{summary.selected_files} / {summary.selectable_files}</span
								>
							</div>
						</div>
						<div class="flex gap-2">
							<button
								class={secondaryButtonClass}
								disabled={starting || saving || jobActive}
								on:click={startCrawl}
							>
								{$i18n.t('Re-crawl')}
							</button>
							<button class={primaryButtonClass} disabled={!canExtend} on:click={extendKnowledge}>
								{$i18n.t('Extend Knowledge')}
							</button>
						</div>
					</div>

					<div class="space-y-1 px-3 py-2 text-xs">
						<div class="text-gray-500">
							{$i18n.t('Crawled')}: {formatTime(resultsRun.finished_at)}
						</div>
						{#if resultsRun.progress?.limit_reached}
							<div class="text-amber-600">
								{$i18n.t(
									LIMIT_LABELS[resultsRun.progress.limit_reached] ??
										resultsRun.progress.limit_reached
								)}
							</div>
						{/if}
						{#if settingsChangedSinceCrawl}
							<div class="text-amber-600">
								{$i18n.t(
									'Crawl settings changed since this crawl. Re-crawl before extending knowledge.'
								)}
							</div>
						{:else if formDirty}
							<div class="text-amber-600">
								{$i18n.t('Save or revert your settings changes before extending knowledge.')}
							</div>
						{/if}
						{#if resultsRun.extend_status}
							<div
								class={resultsRun.extend_status === 'failed'
									? 'text-red-600'
									: 'text-gray-600 dark:text-gray-400'}
							>
								<span class="font-medium">
									{$i18n.t('Extend Knowledge')}: {$i18n.t(
										JOB_STATUS_LABELS[resultsRun.extend_status] ?? resultsRun.extend_status
									)}
								</span>
								{#if extendActive}
									· {resultsRun.extend_progress?.done ?? 0} / {resultsRun.extend_progress?.total ??
										0}
								{/if}
								{#if !extendActive && resultsRun.extend_status !== 'failed'}
									· {$i18n.t('Embedded')}: {resultsRun.extend_progress?.embedded ?? 0} · {$i18n.t(
										'Unchanged'
									)}: {resultsRun.extend_progress?.unchanged ?? 0} · {$i18n.t('Removed')}:
									{resultsRun.extend_progress?.removed ?? 0} · {$i18n.t('No text')}:
									{resultsRun.extend_progress?.no_text ?? 0} · {$i18n.t('Failed')}:
									{resultsRun.extend_progress?.failed ?? 0} · {$i18n.t('Skipped')}:
									{resultsRun.extend_progress?.skipped_limit ?? 0}
								{/if}
								{#if resultsRun.extend_status === 'failed' && resultsRun.extend_error}
									· {resultsRun.extend_error}
								{/if}
							</div>
						{/if}
					</div>

					<div
						class="flex flex-wrap items-center gap-2 border-y border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						{#each TABS as tab (tab.kind)}
							<button
								class="rounded-lg px-2.5 py-1 text-sm {activeTab === tab.kind
									? 'bg-gray-100 font-medium dark:bg-gray-850'
									: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-900'}"
								on:click={() => setTab(tab.kind)}
							>
								{$i18n.t(tab.label)} ({tabCounts[tab.kind]})
							</button>
						{/each}
						<div class="flex-1"></div>
						{#if activeTab === 'page' || activeTab === 'file'}
							<button
								class="rounded-lg px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-850"
								disabled={extendActive}
								on:click={() => selectAllInTab(true)}
							>
								{$i18n.t('Select all')}
							</button>
							<button
								class="rounded-lg px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-850"
								disabled={extendActive}
								on:click={() => selectAllInTab(false)}
							>
								{$i18n.t('Select none')}
							</button>
						{/if}
						<input
							class="w-48 rounded-lg border border-gray-200 bg-transparent px-2 py-1 text-xs outline-none focus:border-gray-400 dark:border-gray-800"
							placeholder={$i18n.t('Search')}
							bind:value={search}
							on:input={() => (visibleCount = PAGE_SIZE)}
						/>
					</div>

					{#if activeTab === 'file'}
						<div
							class="border-b border-gray-100 px-3 py-2 text-xs text-amber-700 dark:border-gray-850 dark:text-amber-300"
						>
							<span class="font-semibold">{$i18n.t('PDF support:')}</span>
							{$i18n.t(
								'Only extractable text inside PDF files can be added to knowledge. Text inside scanned pages or images is not processed.'
							)}
						</div>
					{/if}

					<div class="overflow-x-auto">
						{#if filteredItems.length === 0}
							<div class="px-3 py-8 text-center text-sm text-gray-500">
								{$i18n.t('Nothing found')}
							</div>
						{:else if activeTab === 'page'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="w-12 px-3 py-2">{$i18n.t('Embed')}</th>
										<th class="px-3 py-2">{$i18n.t('Page Title')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Depth')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="px-3 py-2">
												<input
													type="checkbox"
													checked={item.selected}
													disabled={!isSelectable(item) || extendActive}
													on:change={(event) => toggleItem(item, event.currentTarget.checked)}
												/>
											</td>
											<td class="max-w-64 truncate px-3 py-2" title={item.title ?? ''}>
												{item.title ?? '—'}
											</td>
											<td class="max-w-80 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="px-3 py-2">{item.depth ?? '—'}</td>
											<td class="px-3 py-2 {statusClass(item)}" title={item.extract_error ?? ''}>
												{statusText(item)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else if activeTab === 'file'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="w-12 px-3 py-2">{$i18n.t('Embed')}</th>
										<th class="px-3 py-2">{$i18n.t('Name')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Type')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Size')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="px-3 py-2">
												<input
													type="checkbox"
													checked={item.selected}
													disabled={!isSelectable(item) || extendActive}
													on:change={(event) => toggleItem(item, event.currentTarget.checked)}
												/>
											</td>
											<td class="max-w-48 truncate px-3 py-2" title={item.name ?? ''}>
												{item.name ?? '—'}
											</td>
											<td class="px-3 py-2">{(item.file_type ?? '').toUpperCase() || '—'}</td>
											<td class="px-3 py-2">{humanSize(item.size)}</td>
											<td class="max-w-64 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2 {statusClass(item)}" title={item.extract_error ?? ''}>
												{statusText(item)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else if activeTab === 'resource'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="px-3 py-2">{$i18n.t('Name')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Type')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Size')}</th>
										<th class="px-3 py-2">{$i18n.t('Link Text / Context')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 align-top dark:border-gray-900">
											<td class="max-w-48 truncate px-3 py-2" title={item.name ?? ''}>
												{item.name ?? '—'}
											</td>
											<td class="px-3 py-2">{item.file_type ?? '—'}</td>
											<td class="max-w-64 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2">{humanSize(item.size)}</td>
											<td class="max-w-80 px-3 py-2">
												<div class="truncate" title={item.link_text ?? ''}>
													{item.link_text ?? '—'}
												</div>
												{#if item.context}
													<div class="line-clamp-2 text-gray-500" title={item.context}>
														{item.context}
													</div>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Depth')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="max-w-80 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2 {statusClass(item)}">{statusText(item)}</td>
											<td class="px-3 py-2">{item.depth ?? '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					{#if filteredItems.length > visibleCount}
						<div class="flex justify-center px-3 py-2">
							<button
								class={secondaryButtonClass}
								on:click={() => (visibleCount = visibleCount + PAGE_SIZE)}
							>
								{$i18n.t('Show more')} ({filteredItems.length - visibleCount})
							</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</section>
