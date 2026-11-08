<script lang="ts">
	import { onMount } from 'svelte';
	import {
		listWidgetUploads,
		uploadWidgetFile,
		deleteWidgetUpload,
		type WidgetUpload
	} from '$lib/apis/widgets/crawl';
	export let widgetId: string;
	let files: WidgetUpload[] = [];
	let busy = false;
	let loading = true;
	let status = '';
	let error = '';
	let results: { name: string; ok: boolean; message: string }[] = [];
	let removeId = '';
	async function refresh() {
		loading = true;
		try {
			files = await listWidgetUploads(localStorage.token, widgetId);
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}
	async function upload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const selected = Array.from(input.files ?? []);
		if (!selected.length) return;
		busy = true;
		error = '';
		results = [];
		for (const [index, file] of selected.entries()) {
			status = `Processing ${index + 1} of ${selected.length}: ${file.name}`;
			try {
				if (file.size > 20 * 1024 * 1024) throw new Error('Maximum file size is 20 MB');
				await uploadWidgetFile(localStorage.token, widgetId, file);
				results = [
					...results,
					{ name: file.name, ok: true, message: 'Added to chatbot knowledge' }
				];
			} catch (e) {
				results = [...results, { name: file.name, ok: false, message: String(e) }];
			}
		}
		status = 'Upload processing finished.';
		input.value = '';
		await refresh();
		busy = false;
	}
	async function remove(file: WidgetUpload) {
		busy = true;
		error = '';
		try {
			await deleteWidgetUpload(localStorage.token, widgetId, file.id);
			removeId = '';
			await refresh();
		} catch (e) {
			error = String(e);
		} finally {
			busy = false;
		}
	}
	onMount(() => {
		refresh();
	});
</script>

<section
	class="mt-3 rounded-lg border border-gray-200 p-4 dark:border-gray-800"
	aria-label="Local knowledge files"
>
	<h2 class="text-sm font-medium">Local knowledge files</h2>
	<p class="mt-1 text-xs text-gray-500">
		Upload documents from your computer to this chatbot’s knowledge base. These files stay available
		when you re-crawl the website.
	</p>
	<label class="mt-3 block text-sm">
		<span class="mb-2 block">Add files — PDF, DOCX, XLSX, CSV, TXT or PPTX (20 MB each)</span>
		<input
			type="file"
			multiple
			accept=".pdf,.docx,.xlsx,.csv,.txt,.pptx"
			disabled={busy}
			on:change={upload}
			class="block w-full rounded-lg border border-gray-200 p-3 text-sm disabled:opacity-50 dark:border-gray-700"
		/>
	</label>
	<p class="mt-2 text-xs text-gray-500">
		Files are ready only after text extraction and indexing finish. Image-only documents may require
		OCR configured in Open WebUI.
	</p>
	{#if status}<p class="mt-2 text-sm" role="status">{status}</p>{/if}
	{#if error}<p class="mt-2 text-sm text-red-600" role="alert">{error}</p>{/if}
	{#each results as result}
		<p
			class="mt-1 break-words text-xs {result.ok
				? 'text-green-700 dark:text-green-400'
				: 'text-red-600'}"
		>
			{result.name}: {result.message}
		</p>
	{/each}
	<div class="mt-4 flex items-center justify-between">
		<h3 class="text-xs font-medium">Uploaded files ({files.length})</h3>
		<button
			class="rounded-lg border px-3 py-1 text-xs disabled:opacity-50"
			disabled={busy || loading}
			on:click={() => {
				error = '';
				refresh();
			}}>Refresh</button
		>
	</div>
	{#if loading}<p class="mt-2 text-sm" role="status">Loading files…</p>
	{:else if !files.length}<p class="mt-2 text-sm text-gray-500">No local files uploaded yet.</p>
	{:else}
		<ul class="mt-2 divide-y divide-gray-100 dark:divide-gray-800">
			{#each files as file (file.id)}
				<li class="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
					<span class="min-w-0 break-words">{file.name}</span>
					{#if removeId === file.id}
						<div class="flex items-center gap-2 text-xs">
							<span>Remove from knowledge?</span><button
								disabled={busy}
								class="text-red-600 underline"
								on:click={() => remove(file)}>Remove</button
							><button disabled={busy} class="underline" on:click={() => (removeId = '')}
								>Cancel</button
							>
						</div>
					{:else}<button
							class="text-xs text-red-600 underline disabled:opacity-50"
							disabled={busy}
							on:click={() => (removeId = file.id)}>Remove</button
						>{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>
