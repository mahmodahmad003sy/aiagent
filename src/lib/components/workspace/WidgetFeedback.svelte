<script lang="ts">
	import { onMount } from 'svelte';
	import { getChatWidgetFeedback, type ChatWidgetFeedbackEntry } from '$lib/apis/widgets';
	export let widgetId: string;
	let vote = '';
	let items: ChatWidgetFeedbackEntry[] = [];
	let loading = false;
	let error = '';
	let page = 0;
	let hasMore = false;
	let requestId = 0;
	const text = (value: unknown): string =>
		typeof value === 'string' ? value : JSON.stringify(value ?? '');
	async function load(nextPage = 0) {
		const id = ++requestId;
		loading = true;
		error = '';
		try {
			const result = await getChatWidgetFeedback(localStorage.token, widgetId, vote, nextPage * 25);
			if (id !== requestId) return;
			items = result.items;
			hasMore = result.has_more;
			page = nextPage;
		} catch {
			if (id === requestId) {
				items = [];
				error = 'Could not load feedback. Please try again.';
			}
		} finally {
			if (id === requestId) loading = false;
		}
	}
	onMount(() => {
		load();
	});
</script>

<section
	class="mt-3 rounded-lg border border-gray-200 p-4 dark:border-gray-800"
	aria-label="Answer feedback"
>
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<h2 class="text-sm font-medium">Answer feedback</h2>
			<p class="text-xs text-gray-500">
				Review visitor feedback with the original question and answer.
			</p>
		</div>
		<div class="flex items-center gap-2 text-sm">
			<select
				aria-label="Filter feedback"
				bind:value={vote}
				on:change={() => load()}
				class="rounded-lg border border-gray-200 bg-transparent p-2 dark:border-gray-700"
			>
				<option value="">All feedback</option>
				<option value="1">Helpful</option>
				<option value="-1">Not helpful</option>
			</select>
			<button
				class="rounded-lg border px-3 py-2 disabled:opacity-50"
				on:click={() => load(page)}
				disabled={loading}>Refresh</button
			>
		</div>
	</div>
	{#if loading}
		<p class="py-6 text-sm" role="status">Loading feedback…</p>
	{:else if error}
		<p class="py-6 text-sm text-red-600" role="alert">{error}</p>
	{:else if items.length === 0}
		<p class="py-6 text-sm text-gray-500">No feedback matches this filter yet.</p>
	{:else}
		<div class="mt-4 space-y-3">
			{#each items as item (item.answer.id)}
				<article class="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
					<div class="mb-3 flex flex-wrap items-center gap-3 text-xs">
						<strong
							class={item.answer.feedback_vote === 1
								? 'text-green-700 dark:text-green-400'
								: 'text-red-700 dark:text-red-400'}
							>{item.answer.feedback_vote === 1 ? '👍 Helpful' : '👎 Not helpful'}</strong
						>
						{#if item.answer.feedback?.score}<span>Score: {item.answer.feedback.score}/5</span>{/if}
						<time datetime={new Date(item.answer.created_at * 1000).toISOString()}
							>{new Date(item.answer.created_at * 1000).toLocaleString()}</time
						>
						<span>Model: {item.answer.model_id || 'Unknown'}</span>
					</div>
					<div class="grid gap-4 md:grid-cols-2">
						<div>
							<h3 class="text-xs font-semibold text-gray-500">Question</h3>
							<p class="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm">
								{item.question
									? text(item.question.content)
									: 'Question link unavailable for this older answer. See its conversation below.'}
							</p>
						</div>
						<div>
							<h3 class="text-xs font-semibold text-gray-500">Answer</h3>
							<p class="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm">
								{text(item.answer.content)}
							</p>
						</div>
					</div>
					{#if item.answer.feedback?.comment}<div
							class="mt-3 rounded-lg bg-gray-50 p-3 dark:bg-gray-900"
						>
							<h3 class="text-xs font-semibold">Visitor comment</h3>
							<p class="mt-1 whitespace-pre-wrap break-words text-sm">
								{item.answer.feedback.comment}
							</p>
						</div>{/if}
					<div class="mt-3 break-all text-xs text-gray-500">
						Conversation: {item.answer.session_id}
						<span class="ml-3">Visitor: {item.visitor_id}</span>
						{#if item.chat_id}
							<a class="ml-3 underline" href={`/c/${item.chat_id}`}>Open conversation</a>
						{/if}
					</div>
				</article>
			{/each}
		</div>
	{/if}
	<div class="mt-3 flex items-center justify-end gap-3 text-sm">
		<button
			class="rounded-lg border px-3 py-1 disabled:opacity-40"
			disabled={loading || page === 0}
			on:click={() => load(page - 1)}>Previous</button
		>
		<span>Page {page + 1}</span>
		<button
			class="rounded-lg border px-3 py-1 disabled:opacity-40"
			disabled={loading || !hasMore}
			on:click={() => load(page + 1)}>Next</button
		>
	</div>
</section>
