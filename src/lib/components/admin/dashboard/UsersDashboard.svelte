<script lang="ts">
	import { onMount } from 'svelte';

	import { getUsers } from '$lib/apis/users';
	import {
		getUserAnalytics,
		getSummary,
		getTokenUsage,
		getDailyStats
	} from '$lib/apis/analytics';

	import ChartLine from '$lib/components/admin/Analytics/ChartLine.svelte';

	type UserItem = {
		id: string;
		name?: string;
		email?: string;
		role?: string;
		last_active_at?: number;
		created_at?: number;
		profile_image_url?: string;
	};

	type UserAnalytics = {
		user_id: string;
		name?: string;
		email?: string;
		count: number;
		input_tokens?: number;
		output_tokens?: number;
		total_tokens?: number;
	};

	let loading = true;
	let error = '';

	let users: UserItem[] = [];
	let userStats: UserAnalytics[] = [];

	let totalMessages = 0;
	let totalTokens = 0;
	let analyticsActiveUsers = 0;

	let dailyStats: Array<{
		date: string;
		models: Record<string, number>;
	}> = [];

	let selectedPeriod = '30d';

	const periods = [
		{ value: '7d', label: '7 days', days: 7 },
		{ value: '30d', label: '30 days', days: 30 },
		{ value: '90d', label: '90 days', days: 90 }
	];

	const chartColors = ['#3b82f6'];

	const loadAllUsers = async () => {
		let page = 1;
		let result: UserItem[] = [];
		let total = 0;

		while (page <= 100) {
			const response = await getUsers(
				localStorage.token,
				undefined,
				'created_at',
				'desc',
				page
			);

			const pageUsers = response?.users ?? [];

			if (page === 1) {
				total = response?.total ?? pageUsers.length;
			}

			result = [...result, ...pageUsers];

			if (
				pageUsers.length === 0 ||
				result.length >= total
			) {
				break;
			}

			page += 1;
		}

		return result;
	};

	const loadDashboard = async () => {
		loading = true;
		error = '';

		try {
			const period =
				periods.find((item) => item.value === selectedPeriod) ??
				periods[1];

			const now = Math.floor(Date.now() / 1000);
			const start = now - period.days * 24 * 60 * 60;

			const [
				usersResult,
				userAnalyticsResult,
				summaryResult,
				tokenResult,
				dailyResult
			] = await Promise.all([
				loadAllUsers(),

				getUserAnalytics(
					localStorage.token,
					start,
					now,
					50
				),

				getSummary(
					localStorage.token,
					start,
					now
				),

				getTokenUsage(
					localStorage.token,
					start,
					now
				),

				getDailyStats(
					localStorage.token,
					start,
					now,
					'daily'
				)
			]);

			users = usersResult;

			userStats = userAnalyticsResult?.users ?? [];

			totalMessages =
				summaryResult?.total_messages ?? 0;

			analyticsActiveUsers =
				summaryResult?.total_users ?? 0;

			totalTokens =
				tokenResult?.total_tokens ?? 0;

			dailyStats =
				dailyResult?.data ?? [];
		} catch (err) {
			console.error(err);

			error =
				err instanceof Error
					? err.message
					: String(err);
		}

		loading = false;
	};

	const formatNumber = (value: number) => {
		return new Intl.NumberFormat('en', {
			notation: value >= 10000 ? 'compact' : 'standard',
			maximumFractionDigits: 1
		}).format(value);
	};

	const relativeTime = (timestamp?: number) => {
		if (!timestamp) {
			return 'Never';
		}

		const now = Math.floor(Date.now() / 1000);

		const difference =
			Math.max(0, now - timestamp);

		if (difference < 60) {
			return 'Just now';
		}

		if (difference < 3600) {
			const minutes =
				Math.floor(difference / 60);

			return `${minutes} min ago`;
		}

		if (difference < 86400) {
			const hours =
				Math.floor(difference / 3600);

			return `${hours}h ago`;
		}

		const days =
			Math.floor(difference / 86400);

		return `${days}d ago`;
	};

	const changePeriod = async (
		event: Event
	) => {
		selectedPeriod = (
			event.currentTarget as HTMLSelectElement
		).value;

		await loadDashboard();
	};

	$: nowTimestamp =
		Math.floor(Date.now() / 1000);

	$: active24h = users.filter(
		(user) =>
			user.last_active_at &&
			user.last_active_at >=
				nowTimestamp - 24 * 60 * 60
	).length;

	$: active7d = users.filter(
		(user) =>
			user.last_active_at &&
			user.last_active_at >=
				nowTimestamp - 7 * 24 * 60 * 60
	).length;

	$: adminCount = users.filter(
		(user) => user.role === 'admin'
	).length;

	$: normalUserCount = users.filter(
		(user) => user.role === 'user'
	).length;

	$: pendingCount = users.filter(
		(user) => user.role === 'pending'
	).length;

	$: roleTotal =
		adminCount +
		normalUserCount +
		pendingCount;

	$: adminPercentage =
		roleTotal > 0
			? (adminCount / roleTotal) * 100
			: 0;

	$: userPercentage =
		roleTotal > 0
			? (normalUserCount / roleTotal) * 100
			: 0;

	$: pendingPercentage =
		roleTotal > 0
			? (pendingCount / roleTotal) * 100
			: 0;

	$: adminEnd = adminPercentage;

	$: userEnd =
		adminPercentage + userPercentage;

	$: topUsers = [...userStats]
		.sort((a, b) => b.count - a.count)
		.slice(0, 8);

	$: maxUserMessages =
		Math.max(
			...topUsers.map(
				(user) => user.count
			),
			1
		);

	$: recentUsers = [...users]
		.sort(
			(a, b) =>
				(b.created_at ?? 0) -
				(a.created_at ?? 0)
		)
		.slice(0, 8);

	/*
	 * ChartLine expects its values inside
	 * an object named "models".
	 *
	 * Convert model-level daily analytics
	 * into one total message series.
	 */
	$: messageTrend = dailyStats.map(
		(day) => ({
			date: day.date,

			models: {
				Messages: Object.values(
					day.models ?? {}
				).reduce(
					(total, count) =>
						total + count,
					0
				)
			}
		})
	);

	onMount(() => {
		loadDashboard();
	});
</script>

<div class="w-full space-y-6">
	<!-- Header -->
	<div
		class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
	>
		<div>
			<h2
				class="text-lg font-medium text-gray-900 dark:text-white"
			>
				Users Dashboard
			</h2>

			<p
				class="mt-1 text-sm text-gray-500 dark:text-gray-400"
			>
				User activity, roles and platform usage.
			</p>
		</div>

		<div class="flex items-center gap-2">
			<select
				value={selectedPeriod}
				on:change={changePeriod}
				class="rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-xs outline-none dark:border-gray-700"
			>
				{#each periods as period}
					<option value={period.value}>
						Last {period.label}
					</option>
				{/each}
			</select>

			<a
				href="/admin/users/overview"
				class="rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800"
			>
				Manage users
			</a>
		</div>
	</div>

	{#if loading}
		<div
			class="flex h-64 items-center justify-center text-sm text-gray-400"
		>
			Loading user analytics…
		</div>
	{:else if error}
		<div
			class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
		>
			{error}
		</div>
	{:else}

		<!-- Summary cards -->
		<div
			class="grid grid-cols-2 gap-3 xl:grid-cols-4"
		>
			<div
				class="rounded-xl border border-gray-200 p-4 dark:border-gray-800"
			>
				<div
					class="text-xs text-gray-500 dark:text-gray-400"
				>
					Total Accounts
				</div>

				<div
					class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white"
				>
					{users.length}
				</div>

				<div
					class="mt-1 text-[11px] text-gray-400"
				>
					All registered users
				</div>
			</div>

			<div
				class="rounded-xl border border-gray-200 p-4 dark:border-gray-800"
			>
				<div
					class="text-xs text-gray-500 dark:text-gray-400"
				>
					Active · 24h
				</div>

				<div
					class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white"
				>
					{active24h}
				</div>

				<div
					class="mt-1 text-[11px] text-gray-400"
				>
					Based on last activity
				</div>
			</div>

			<div
				class="rounded-xl border border-gray-200 p-4 dark:border-gray-800"
			>
				<div
					class="text-xs text-gray-500 dark:text-gray-400"
				>
					Active · 7d
				</div>

				<div
					class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white"
				>
					{active7d}
				</div>

				<div
					class="mt-1 text-[11px] text-gray-400"
				>
					{analyticsActiveUsers} sent messages in selected period
				</div>
			</div>

			<div
				class="rounded-xl border border-gray-200 p-4 dark:border-gray-800"
			>
				<div
					class="text-xs text-gray-500 dark:text-gray-400"
				>
					Messages · {selectedPeriod}
				</div>

				<div
					class="mt-2 text-2xl font-semibold text-gray-900 dark:text-white"
				>
					{formatNumber(totalMessages)}
				</div>

				<div
					class="mt-1 text-[11px] text-gray-400"
				>
					{formatNumber(totalTokens)} tokens
				</div>
			</div>
		</div>

		<!-- Charts -->
		<div
			class="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]"
		>
			<!-- Role donut -->
			<div
				class="rounded-xl border border-gray-200 p-5 dark:border-gray-800"
			>
				<div
					class="text-sm font-medium text-gray-900 dark:text-white"
				>
					Role Distribution
				</div>

				<div
					class="mt-1 text-xs text-gray-400"
				>
					Current account roles
				</div>

				<div
					class="flex items-center justify-center py-7"
				>
					<div
						class="relative flex h-44 w-44 items-center justify-center rounded-full"
						style="background: conic-gradient(
							#3b82f6 0% {adminEnd}%,
							#10b981 {adminEnd}% {userEnd}%,
							#f59e0b {userEnd}% 100%
						);"
					>
						<div
							class="flex h-28 w-28 flex-col items-center justify-center rounded-full bg-white dark:bg-gray-950"
						>
							<div
								class="text-2xl font-semibold text-gray-900 dark:text-white"
							>
								{roleTotal}
							</div>

							<div
								class="text-[11px] uppercase tracking-wide text-gray-400"
							>
								Users
							</div>
						</div>
					</div>
				</div>

				<div class="space-y-2.5">
					<div
						class="flex items-center justify-between text-sm"
					>
						<div
							class="flex items-center gap-2"
						>
							<span
								class="h-2.5 w-2.5 rounded-full bg-blue-500"
							></span>

							<span
								class="text-gray-600 dark:text-gray-300"
							>
								Admins
							</span>
						</div>

						<div
							class="font-medium text-gray-900 dark:text-white"
						>
							{adminCount}
						</div>
					</div>

					<div
						class="flex items-center justify-between text-sm"
					>
						<div
							class="flex items-center gap-2"
						>
							<span
								class="h-2.5 w-2.5 rounded-full bg-green-500"
							></span>

							<span
								class="text-gray-600 dark:text-gray-300"
							>
								Users
							</span>
						</div>

						<div
							class="font-medium text-gray-900 dark:text-white"
						>
							{normalUserCount}
						</div>
					</div>

					<div
						class="flex items-center justify-between text-sm"
					>
						<div
							class="flex items-center gap-2"
						>
							<span
								class="h-2.5 w-2.5 rounded-full bg-amber-500"
							></span>

							<span
								class="text-gray-600 dark:text-gray-300"
							>
								Pending
							</span>
						</div>

						<div
							class="font-medium text-gray-900 dark:text-white"
						>
							{pendingCount}
						</div>
					</div>
				</div>
			</div>

			<!-- Top users -->
			<div
				class="rounded-xl border border-gray-200 p-5 dark:border-gray-800"
			>
				<div
					class="flex items-center justify-between"
				>
					<div>
						<div
							class="text-sm font-medium text-gray-900 dark:text-white"
						>
							Top Active Users
						</div>

						<div
							class="mt-1 text-xs text-gray-400"
						>
							Messages during the selected period
						</div>
					</div>
				</div>

				{#if topUsers.length > 0}
					<div class="mt-6 space-y-5">
						{#each topUsers as item, index}
							<div>
								<div
									class="mb-1.5 flex items-center justify-between gap-4"
								>
									<div
										class="flex min-w-0 items-center gap-2"
									>
										<div
											class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-100 text-[11px] font-medium dark:bg-gray-800"
										>
											{index + 1}
										</div>

										<div class="min-w-0">
											<div
												class="truncate text-sm text-gray-800 dark:text-gray-200"
											>
												{item.name ??
													item.email ??
													item.user_id}
											</div>

											{#if item.email}
												<div
													class="truncate text-[10px] text-gray-400"
												>
													{item.email}
												</div>
											{/if}
										</div>
									</div>

									<div
										class="shrink-0 text-sm font-medium tabular-nums text-gray-900 dark:text-white"
									>
										{item.count.toLocaleString()}
									</div>
								</div>

								<div
									class="h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800"
								>
									<div
										class="h-full rounded-full bg-gray-800 dark:bg-gray-300"
										style="width: {Math.max(
											(item.count /
												maxUserMessages) *
												100,
											2
										)}%"
									></div>
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<div
						class="flex h-64 items-center justify-center text-sm text-gray-400"
					>
						No user activity for this period.
					</div>
				{/if}
			</div>
		</div>

		<!-- Message trend -->
		<div
			class="rounded-xl border border-gray-200 p-5 dark:border-gray-800"
		>
			<div>
				<div
					class="text-sm font-medium text-gray-900 dark:text-white"
				>
					User Activity
				</div>

				<div
					class="mt-1 text-xs text-gray-400"
				>
					Total messages over the selected period
				</div>
			</div>

			<div class="mt-5">
				{#if messageTrend.length > 1}
					<ChartLine
						data={messageTrend}
						models={['Messages']}
						colors={chartColors}
						height={230}
						period={selectedPeriod === '90d'
							? 'year'
							: selectedPeriod === '30d'
								? 'month'
								: 'week'}
					/>
				{:else}
					<div
						class="flex h-48 items-center justify-center text-sm text-gray-400"
					>
						Not enough activity data yet.
					</div>
				{/if}
			</div>
		</div>

		<!-- Recent users -->
		<div
			class="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800"
		>
			<div
				class="flex items-center justify-between border-b border-gray-200 px-5 py-4 dark:border-gray-800"
			>
				<div>
					<div
						class="text-sm font-medium text-gray-900 dark:text-white"
					>
						Recent Accounts
					</div>

					<div
						class="mt-0.5 text-xs text-gray-400"
					>
						Newest registered users
					</div>
				</div>

				<a
					href="/admin/users/overview"
					class="text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"
				>
					View all →
				</a>
			</div>

			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead
						class="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-400 dark:bg-gray-900/50"
					>
						<tr>
							<th
								class="px-5 py-3 font-medium"
							>
								User
							</th>

							<th
								class="px-5 py-3 font-medium"
							>
								Role
							</th>

							<th
								class="px-5 py-3 font-medium"
							>
								Last active
							</th>
						</tr>
					</thead>

					<tbody
						class="divide-y divide-gray-100 dark:divide-gray-800"
					>
						{#each recentUsers as item}
							<tr
								class="hover:bg-gray-50/70 dark:hover:bg-gray-900/40"
							>
								<td class="px-5 py-3">
									<div
										class="font-medium text-gray-800 dark:text-gray-200"
									>
										{item.name ?? 'Unnamed user'}
									</div>

									<div
										class="mt-0.5 text-xs text-gray-400"
									>
										{item.email ?? ''}
									</div>
								</td>

								<td class="px-5 py-3">
									<span
										class="rounded-full bg-gray-100 px-2 py-1 text-xs capitalize text-gray-600 dark:bg-gray-800 dark:text-gray-300"
									>
										{item.role ?? 'unknown'}
									</span>
								</td>

								<td
									class="whitespace-nowrap px-5 py-3 text-gray-500 dark:text-gray-400"
								>
									{relativeTime(
										item.last_active_at
									)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>