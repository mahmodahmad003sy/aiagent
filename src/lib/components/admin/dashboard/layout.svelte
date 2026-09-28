<script lang="ts">
	import { page } from '$app/stores';
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	const tabs = [
		{
			name: 'Overview',
			path: '/admin/dashboard/overview'
		},
		{
			name: 'Users',
			path: '/admin/dashboard/users'
		},
		{
			name: 'Model Access',
			path: '/admin/dashboard/model-access'
		},
		{
			name: 'Model Usage',
			path: '/admin/dashboard/model-usage'
		},
		{
			name: 'System Health',
			path: '/admin/dashboard/system-health'
		}
	];
</script>

<div class="w-full max-w-7xl mx-auto px-4 md:px-6 py-4">
	<div class="mb-5">
		<h1 class="text-xl font-semibold text-gray-900 dark:text-white">
			{$i18n.t('Admin Dashboard')}
		</h1>

		<p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
			{$i18n.t('Monitor users, models, access and system activity.')}
		</p>
	</div>

	<div class="flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-gray-800 mb-6">
		{#each tabs as tab}
			<a
				href={tab.path}
				class="whitespace-nowrap px-3 py-2.5 text-sm border-b-2 transition
					{$page.url.pathname === tab.path
					? 'border-gray-900 dark:border-white text-gray-900 dark:text-white font-medium'
					: 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'}"
			>
				{$i18n.t(tab.name)}
			</a>
		{/each}
	</div>

	<slot />
</div>