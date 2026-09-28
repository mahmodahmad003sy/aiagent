<script lang="ts">
	const services = [
		{
			name: 'Open WebUI',
			type: 'Backend',
			status: 'Checking'
		},
		{
			name: 'OpenRouter',
			type: 'Model Provider',
			status: 'Checking'
		},
		{
			name: 'Ollama',
			type: 'Model Provider',
			status: 'Checking'
		}
	];
</script>

<div class="w-full">
	<div class="mb-5">
		<h2 class="text-lg font-medium text-gray-900 dark:text-white">
			System Health
		</h2>

		<p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
			Connection, provider and model availability.
		</p>
	</div>

	<div class="grid gap-3">
		{#each services as service}
			<div
				class="flex items-center justify-between rounded-xl border border-gray-200 dark:border-gray-800 p-4"
			>
				<div>
					<div class="font-medium text-gray-900 dark:text-white">
						{service.name}
					</div>

					<div class="text-xs text-gray-500 mt-1">
						{service.type}
					</div>
				</div>

				<div class="text-xs text-gray-500">
					{service.status}
				</div>
			</div>
		{/each}
	</div>
</div>