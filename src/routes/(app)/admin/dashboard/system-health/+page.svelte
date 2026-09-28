<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	import { WEBUI_BASE_URL } from '$lib/constants';

	import { getModels } from '$lib/apis';
	import { getSummary, getDailyStats, getTokenUsage } from '$lib/apis/analytics';

	import { getOpenAIConfig, getOpenAIModels } from '$lib/apis/openai';
	import { getOllamaConfig, getOllamaModels } from '$lib/apis/ollama';

	import ChartLine from '$lib/components/admin/Analytics/ChartLine.svelte';

	type ServiceState = 'online' | 'offline' | 'disabled' | 'checking';

	type Service = {
		id: string;
		name: string;
		type: string;
		status: ServiceState;
		latency: number | null;
		models: number;
		detail?: string;
	};

	let services: Service[] = [];

	let refreshing = false;
	let lastUpdated: Date | null = null;

	let totalModels = 0;
	let totalMessages = 0;
	let totalChats = 0;
	let totalUsers = 0;
	let totalTokens = 0;

	let dailyStats: Array<{
		date: string;
		models: Record<string, number>;
	}> = [];

	let latencyHistory: Array<{
		date: string;
		models: Record<string, number>;
	}> = [];

	let refreshTimer: ReturnType<typeof setInterval> | null = null;

	const chartColors = [
		'#3b82f6',
		'#10b981',
		'#f59e0b',
		'#ef4444',
		'#8b5cf6',
		'#ec4899',
		'#06b6d4',
		'#84cc16'
	];

	const getModelCount = (result: any) => {
		if (Array.isArray(result)) {
			return result.length;
		}

		if (Array.isArray(result?.data)) {
			return result.data.length;
		}

		if (Array.isArray(result?.models)) {
			return result.models.length;
		}

		return 0;
	};

	const getProviderName = (url: string) => {
		try {
			const hostname = new URL(url).hostname.toLowerCase();

			if (hostname.includes('openrouter')) {
				return 'OpenRouter';
			}

			if (hostname.includes('openai')) {
				return 'OpenAI';
			}

			if (hostname.includes('localhost') || hostname.includes('127.0.0.1')) {
				return hostname;
			}

			return hostname;
		} catch {
			return 'OpenAI Compatible';
		}
	};

	const measure = async <T>(callback: () => Promise<T>) => {
		const started = performance.now();

		const result = await callback();

		const latency = Math.round(performance.now() - started);

		return {
			result,
			latency
		};
	};

	const checkBackend = async (): Promise<Service> => {
		const started = performance.now();

		try {
			const response = await fetch(`${WEBUI_BASE_URL}/health`);

			const latency = Math.round(performance.now() - started);

			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}

			const data = await response.json();

			return {
				id: 'open-webui',
				name: 'Open WebUI',
				type: 'Backend',
				status: data?.status === true ? 'online' : 'offline',
				latency,
				models: 0
			};
		} catch (error) {
			return {
				id: 'open-webui',
				name: 'Open WebUI',
				type: 'Backend',
				status: 'offline',
				latency: null,
				models: 0,
				detail: error instanceof Error ? error.message : 'Connection failed'
			};
		}
	};

	const checkOpenAIProviders = async (): Promise<Service[]> => {
	try {
		const config = await getOpenAIConfig(localStorage.token);

		if (!config?.ENABLE_OPENAI_API) {
			return [
				{
					id: 'openai-disabled',
					name: 'OpenAI Compatible',
					type: 'Model Provider',
					status: 'disabled',
					latency: null,
					models: 0
				}
			];
		}

		const urls: string[] = config?.OPENAI_API_BASE_URLS ?? [];
		const apiConfigs = config?.OPENAI_API_CONFIGS ?? {};

		// Models Open WebUI already knows about.
		const availableModels = await getModels(
			localStorage.token,
			null,
			false,
			true
		).catch(() => []);

		const checks = urls.map(async (url, index) => {
			// Open WebUI supports both index-keyed and legacy URL-keyed config.
			const providerConfig =
				apiConfigs?.[index.toString()] ??
				apiConfigs?.[url] ??
				{};

			const configuredModelIds =
				providerConfig?.model_ids ?? [];

			if (providerConfig?.enable === false) {
				return {
					id: `openai-${index}`,
					name: getProviderName(url),
					type: 'OpenAI Compatible',
					status: 'disabled' as ServiceState,
					latency: null,
					models: 0
				};
			}

			// Models associated with this provider connection.
			const providerModels = availableModels.filter((model: any) => {
				return (
					Number(model?.urlIdx) === index ||
					Number(model?.openai?.urlIdx) === index
				);
			});

			try {
				const { result, latency } = await measure(() =>
					getOpenAIModels(localStorage.token, index)
				);

				const remoteModelCount = getModelCount(result);

				return {
					id: `openai-${index}`,
					name: getProviderName(url),
					type: 'OpenAI Compatible',
					status: 'online' as ServiceState,
					latency,
					models:
						remoteModelCount ||
						providerModels.length ||
						configuredModelIds.length,
					detail: 'Provider model endpoint responded successfully'
				};
			} catch (error) {
				/*
				 * Do NOT immediately call the provider offline.
				 *
				 * The /models request may fail even though Open WebUI
				 * has manually configured models that can still be used.
				 */
				const modelCount =
					providerModels.length ||
					configuredModelIds.length;

				if (modelCount > 0) {
					return {
						id: `openai-${index}`,
						name: getProviderName(url),
						type: 'OpenAI Compatible',
						status: 'available' as ServiceState,
						latency: null,
						models: modelCount,
						detail:
							'Configured models are available, but provider model-list verification failed'
					};
				}

				return {
					id: `openai-${index}`,
					name: getProviderName(url),
					type: 'OpenAI Compatible',
					status: 'offline' as ServiceState,
					latency: null,
					models: 0,
					detail:
						error instanceof Error
							? error.message
							: String(error)
				};
			}
		});

		return await Promise.all(checks);
	} catch (error) {
		console.error('Failed to check OpenAI providers:', error);

		return [];
	}
};

	const checkOllamaProviders = async (): Promise<Service[]> => {
		try {
			const config = await getOllamaConfig(localStorage.token);

			if (!config?.ENABLE_OLLAMA_API) {
				return [
					{
						id: 'ollama-disabled',
						name: 'Ollama',
						type: 'Model Provider',
						status: 'disabled',
						latency: null,
						models: 0
					}
				];
			}

			const urls: string[] = config?.OLLAMA_BASE_URLS ?? [];
			const apiConfigs = config?.OLLAMA_API_CONFIGS ?? {};

			const checks = urls.map(async (url, index) => {
				const providerConfig = apiConfigs?.[index.toString()] ?? {};

				if (providerConfig?.enable === false) {
					return {
						id: `ollama-${index}`,
						name: urls.length > 1 ? `Ollama ${index + 1}` : 'Ollama',
						type: 'Model Provider',
						status: 'disabled' as ServiceState,
						latency: null,
						models: 0
					};
				}

				try {
					const { result, latency } = await measure(() =>
						getOllamaModels(localStorage.token, index)
					);

					return {
						id: `ollama-${index}`,
						name: urls.length > 1 ? `Ollama ${index + 1}` : 'Ollama',
						type: 'Model Provider',
						status: 'online' as ServiceState,
						latency,
						models: getModelCount(result)
					};
				} catch (error) {
					return {
						id: `ollama-${index}`,
						name: urls.length > 1 ? `Ollama ${index + 1}` : 'Ollama',
						type: 'Model Provider',
						status: 'offline' as ServiceState,
						latency: null,
						models: 0,
						detail: error instanceof Error ? error.message : String(error)
					};
				}
			});

			return await Promise.all(checks);
		} catch (error) {
			console.error('Failed to check Ollama:', error);

			return [];
		}
	};

	const loadAnalytics = async () => {
		const now = Math.floor(Date.now() / 1000);
		const start = now - 7 * 24 * 60 * 60;

		try {
			const [summaryResult, dailyResult, tokenResult, modelResult] = await Promise.allSettled([
				getSummary(localStorage.token, start, now),
				getDailyStats(localStorage.token, start, now, 'daily'),
				getTokenUsage(localStorage.token, start, now),
				getModels(localStorage.token, null, false, true)
			]);

			if (summaryResult.status === 'fulfilled' && summaryResult.value) {
				totalMessages = summaryResult.value.total_messages ?? 0;
				totalChats = summaryResult.value.total_chats ?? 0;
				totalUsers = summaryResult.value.total_users ?? 0;
			}

			if (dailyResult.status === 'fulfilled' && dailyResult.value) {
				dailyStats = dailyResult.value.data ?? [];
			}

			if (tokenResult.status === 'fulfilled' && tokenResult.value) {
				totalTokens = tokenResult.value.total_tokens ?? 0;
			}

			if (modelResult.status === 'fulfilled' && modelResult.value) {
				totalModels = modelResult.value.length ?? 0;
			}
		} catch (error) {
			console.error('Failed loading analytics:', error);
		}
	};

	const loadHealth = async () => {
		const [backend, openAI, ollama] = await Promise.all([
			checkBackend(),
			checkOpenAIProviders(),
			checkOllamaProviders()
		]);

		services = [backend, ...openAI, ...ollama];

		const latencyModels: Record<string, number> = {};

		for (const service of services) {
			if (service.status === 'online' && service.latency !== null) {
				latencyModels[service.name] = service.latency;
			}
		}

		latencyHistory = [
			...latencyHistory,
			{
				date: new Date().toISOString(),
				models: latencyModels
			}
		].slice(-20);
	};

	const refresh = async () => {
		if (refreshing) return;

		refreshing = true;

		try {
			await Promise.all([loadHealth(), loadAnalytics()]);
			lastUpdated = new Date();
		} finally {
			refreshing = false;
		}
	};

	const formatNumber = (value: number) => {
		return new Intl.NumberFormat('en', {
			notation: value >= 10000 ? 'compact' : 'standard',
			maximumFractionDigits: 1
		}).format(value);
	};

	$: enabledServices = services.filter((service) => service.status !== 'disabled');

	$: onlineServices = enabledServices.filter(
		(service) => service.status === 'online'
	).length;

	$: averageLatency = (() => {
		const values = enabledServices
			.filter((service) => service.status === 'online' && service.latency !== null)
			.map((service) => service.latency as number);

		if (values.length === 0) return 0;

		return Math.round(
			values.reduce((total, latency) => total + latency, 0) / values.length
		);
	})();

	$: allChartModels = [
		...new Set(dailyStats.flatMap((item) => Object.keys(item.models ?? {})))
	];

	$: modelTotals = Object.fromEntries(
		allChartModels.map((model) => [
			model,
			dailyStats.reduce(
				(total, item) => total + (item.models?.[model] ?? 0),
				0
			)
		])
	);

	$: topChartModels = [...allChartModels]
		.sort((a, b) => (modelTotals[b] ?? 0) - (modelTotals[a] ?? 0))
		.slice(0, 6);

	$: latencyServices = [
		...new Set(
			latencyHistory.flatMap((item) => Object.keys(item.models ?? {}))
		)
	];

	onMount(async () => {
		await refresh();

		refreshTimer = setInterval(() => {
			loadHealth().then(() => {
				lastUpdated = new Date();
			});
		}, 30000);
	});

	onDestroy(() => {
		if (refreshTimer) {
			clearInterval(refreshTimer);
		}
	});
</script>

<div class="w-full space-y-6">
	<!-- Header -->
	<div class="flex items-start justify-between gap-4">
		<div>
			<h2 class="text-lg font-medium text-gray-900 dark:text-white">
				System Health
			</h2>

			<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
				Live provider status, model availability and platform activity.
			</p>
		</div>

		<div class="flex items-center gap-3">
			{#if lastUpdated}
				<div class="hidden text-xs text-gray-400 md:block">
					Updated {lastUpdated.toLocaleTimeString()}
				</div>
			{/if}

			<button
				type="button"
				on:click={refresh}
				disabled={refreshing}
				class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium
					hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50
					dark:border-gray-700 dark:hover:bg-gray-800"
			>
				{refreshing ? 'Refreshing…' : 'Refresh'}
			</button>
		</div>
	</div>

	<!-- Statistic cards -->
	<div class="grid grid-cols-2 gap-3 xl:grid-cols-6">
		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Services Online
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{onlineServices}
				<span class="text-sm font-normal text-gray-400">
					/ {enabledServices.length}
				</span>
			</div>
		</div>

		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Models Available
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{totalModels}
			</div>
		</div>

		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Average Latency
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{averageLatency}
				<span class="text-sm font-normal text-gray-400">ms</span>
			</div>
		</div>

		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Messages · 7d
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{formatNumber(totalMessages)}
			</div>
		</div>

		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Tokens · 7d
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{formatNumber(totalTokens)}
			</div>
		</div>

		<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Users · 7d
			</div>

			<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
				{totalUsers}
			</div>

			<div class="mt-1 text-[11px] text-gray-400">
				{totalChats.toLocaleString()} chats
			</div>
		</div>
	</div>

	<!-- Message activity -->
	<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
		<div class="mb-4 flex items-center justify-between">
			<div>
				<div class="text-sm font-medium text-gray-900 dark:text-white">
					Message Activity
				</div>

				<div class="mt-0.5 text-xs text-gray-400">
					Last 7 days
				</div>
			</div>
		</div>

		{#if dailyStats.length > 1 && topChartModels.length > 0}
			<ChartLine
				data={dailyStats}
				models={topChartModels}
				colors={chartColors}
				height={240}
				period="week"
			/>
		{:else}
			<div class="flex h-48 items-center justify-center text-sm text-gray-400">
				No activity data available.
			</div>
		{/if}
	</div>

	<!-- Services -->
	<div class="rounded-xl border border-gray-200 dark:border-gray-800">
		<div class="border-b border-gray-200 px-4 py-3 dark:border-gray-800">
			<div class="text-sm font-medium text-gray-900 dark:text-white">
				Services & Providers
			</div>
		</div>

		<div class="divide-y divide-gray-200 dark:divide-gray-800">
			{#if services.length === 0}
				<div class="px-4 py-6 text-center text-sm text-gray-400">
					Checking services…
				</div>
			{:else}
				{#each services as service}
					<div class="flex items-center justify-between gap-4 px-4 py-4">
						<div class="flex min-w-0 items-center gap-3">
							<div
								class="h-2.5 w-2.5 shrink-0 rounded-full
									{service.status === 'online'
										? 'bg-green-500'
										: service.status === 'offline'
											? 'bg-red-500'
											: service.status === 'disabled'
												? 'bg-gray-400'
												: 'bg-yellow-500'}"
							></div>

							<div class="min-w-0">
								<div class="truncate text-sm font-medium text-gray-900 dark:text-white">
									{service.name}
								</div>

								<div class="mt-0.5 text-xs text-gray-400">
									{service.type}
								</div>
							</div>
						</div>

						<div class="flex shrink-0 items-center gap-5">
							{#if service.models > 0}
								<div class="hidden text-right sm:block">
									<div class="text-sm text-gray-700 dark:text-gray-300">
										{service.models}
									</div>

									<div class="text-[10px] uppercase tracking-wide text-gray-400">
										models
									</div>
								</div>
							{/if}

							<div class="hidden min-w-[65px] text-right sm:block">
								{#if service.latency !== null}
									<div class="text-sm text-gray-700 dark:text-gray-300">
										{service.latency} ms
									</div>

									<div class="text-[10px] uppercase tracking-wide text-gray-400">
										latency
									</div>
								{:else}
									<div class="text-sm text-gray-400">—</div>
								{/if}
							</div>

							<div
								class="min-w-[70px] rounded-full px-2.5 py-1 text-center text-xs font-medium
									{service.status === 'online'
										? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
										: service.status === 'offline'
											? 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
											: service.status === 'disabled'
												? 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
												: 'bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400'}"
							>
								{service.status.charAt(0).toUpperCase() + service.status.slice(1)}
							</div>
						</div>
					</div>
				{/each}
			{/if}
		</div>
	</div>

	<!-- Live latency chart -->
	<div class="rounded-xl border border-gray-200 p-4 dark:border-gray-800">
		<div class="mb-4">
			<div class="text-sm font-medium text-gray-900 dark:text-white">
				Live Provider Latency
			</div>

			<div class="mt-0.5 text-xs text-gray-400">
				30-second health checks · current browser session
			</div>
		</div>

		{#if latencyHistory.length > 1 && latencyServices.length > 0}
			<ChartLine
				data={latencyHistory}
				models={latencyServices}
				colors={chartColors}
				height={200}
				period="hour"
			/>
		{:else}
			<div class="flex h-36 items-center justify-center text-sm text-gray-400">
				Collecting latency samples…
			</div>
		{/if}
	</div>
</div>