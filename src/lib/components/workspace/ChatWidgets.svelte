<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';

	import { models, workspaceActions, workspaceCounts } from '$lib/stores';
	import {
		createChatWidget,
		deleteChatWidget,
		getChatWidgets,
		rotateChatWidgetToken,
		updateChatWidget,
		type ChatWidget,
		type ChatWidgetForm
	} from '$lib/apis/widgets';
	import { copyToClipboard } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChatBubble from '$lib/components/icons/ChatBubble.svelte';

	const i18n = getContext<Writable<i18nType>>('i18n');
	dayjs.extend(relativeTime);

	let loaded = false;
	let saving = false;
	let widgets: ChatWidget[] = [];
	let selectedWidget: ChatWidget | null = null;
	let deleteTarget: ChatWidget | null = null;
	let showDeleteConfirm = false;

	let form: ChatWidgetForm = {
		name: '',
		model_id: '',
		system_prompt: '',
		welcome_message: '',
		enabled: true,
		allowed_domains: []
	};
	let domainsText = '';

	$: embedCode = selectedWidget ? buildEmbedCode(selectedWidget) : '';
	$: selectedModelName =
		$models?.find((model) => model.id === form.model_id)?.name ?? form.model_id ?? '';
	$: if (!form.model_id && $models?.length) {
		form = { ...form, model_id: $models[0].id };
	}

	const resetForm = () => {
		selectedWidget = null;
		form = {
			name: '',
			model_id: $models?.[0]?.id ?? '',
			system_prompt: '',
			welcome_message: '',
			enabled: true,
			allowed_domains: []
		};
		domainsText = '';
	};

	const editWidget = (widget: ChatWidget) => {
		selectedWidget = widget;
		form = {
			name: widget.name,
			model_id: widget.model_id,
			system_prompt: widget.system_prompt ?? '',
			welcome_message: widget.welcome_message ?? '',
			enabled: widget.enabled,
			allowed_domains: widget.allowed_domains ?? []
		};
		domainsText = (widget.allowed_domains ?? []).join('\n');
	};

	const normalizeDomains = () =>
		domainsText
			.split(/[\n,]/)
			.map((domain) => domain.trim())
			.filter((domain, index, domains) => domain && domains.indexOf(domain) === index);

	const buildPayload = (): ChatWidgetForm => ({
		...form,
		name: form.name.trim(),
		system_prompt: form.system_prompt?.trim() || null,
		welcome_message: form.welcome_message?.trim() || null,
		allowed_domains: normalizeDomains()
	});

	const loadWidgets = async () => {
		const res = await getChatWidgets(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			widgets = res;
			workspaceCounts.update((counts) => ({ ...counts, widgets: widgets.length }));
			if (selectedWidget) {
				const updated = widgets.find((widget) => widget.id === selectedWidget?.id);
				if (updated) editWidget(updated);
			}
		}
	};

	const saveWidget = async () => {
		const payload = buildPayload();
		if (!payload.name) {
			toast.error($i18n.t('Name is required'));
			return;
		}
		if (!payload.model_id) {
			toast.error($i18n.t('Model is required'));
			return;
		}

		saving = true;
		const res = selectedWidget
			? await updateChatWidget(localStorage.token, selectedWidget.id, payload).catch((error) => {
					toast.error(`${error}`);
					return null;
				})
			: await createChatWidget(localStorage.token, payload).catch((error) => {
					toast.error(`${error}`);
					return null;
				});
		saving = false;

		if (res) {
			toast.success(selectedWidget ? $i18n.t('Saved') : $i18n.t('Created'));
			await loadWidgets();
			editWidget(res);
		}
	};

	const toggleWidget = async (widget: ChatWidget) => {
		const res = await updateChatWidget(localStorage.token, widget.id, {
			enabled: !widget.enabled
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			widgets = widgets.map((item) => (item.id === res.id ? res : item));
			if (selectedWidget?.id === res.id) editWidget(res);
		}
	};

	const rotateToken = async (widget: ChatWidget) => {
		const res = await rotateChatWidgetToken(localStorage.token, widget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			toast.success($i18n.t('Token rotated'));
			widgets = widgets.map((item) => (item.id === res.id ? res : item));
			editWidget(res);
		}
	};

	const confirmDelete = (widget: ChatWidget) => {
		deleteTarget = widget;
		showDeleteConfirm = true;
	};

	const deleteSelectedWidget = async () => {
		if (!deleteTarget) return;
		const res = await deleteChatWidget(localStorage.token, deleteTarget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Deleted'));
			if (selectedWidget?.id === deleteTarget.id) resetForm();
			deleteTarget = null;
			await loadWidgets();
		}
	};

	const baseUrl = () => (typeof window !== 'undefined' ? window.location.origin : '');
	const buildEmbedCode = (widget: ChatWidget) =>
		`<script src="${baseUrl()}/static/widget/chat-widget.js" data-widget-id="${widget.id}" data-token="${widget.token}" data-api-base="${baseUrl()}"><\/script>`;

	const copyEmbed = async () => {
		if (!embedCode) return;
		if (await copyToClipboard(embedCode)) {
			toast.success($i18n.t('Copied to clipboard'));
		}
	};

	onMount(async () => {
		workspaceActions.set([
			{
				id: 'widgets-new',
				label: $i18n.t('Create'),
				onClick: resetForm
			}
		]);
		resetForm();
		await loadWidgets();
		loaded = true;
	});
</script>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete widget?')}
	message={$i18n.t('This will disable the embed and remove its widget configuration.')}
	on:confirm={deleteSelectedWidget}
/>

{#if loaded}
	<div class="mx-auto w-full max-w-7xl py-3">
		<div class="grid grid-cols-1 xl:grid-cols-[minmax(280px,420px)_1fr] gap-3">
			<section class="min-w-0">
				<div class="flex items-center justify-between pb-2">
					<div class="text-lg font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Chat Widgets')}
					</div>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-lg bg-black text-white dark:bg-white dark:text-black"
						on:click={resetForm}
					>
						{$i18n.t('Create')}
					</button>
				</div>

				<div class="flex flex-col gap-1">
					{#if widgets.length === 0}
						<div
							class="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-gray-200 px-4 text-center dark:border-gray-800"
						>
							<ChatBubble className="size-6 text-gray-400" />
							<div class="mt-2 text-sm font-medium">{$i18n.t('No widgets yet')}</div>
						</div>
					{:else}
						{#each widgets as widget (widget.id)}
							<button
								class="group w-full rounded-lg border px-3 py-2 text-left transition {selectedWidget?.id ===
								widget.id
									? 'border-gray-400 bg-gray-50 dark:border-gray-600 dark:bg-gray-900'
									: 'border-gray-100 hover:bg-gray-50 dark:border-gray-850 dark:hover:bg-gray-900'}"
								on:click={() => editWidget(widget)}
							>
								<div class="flex items-start gap-3">
									<div
										class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full {widget.enabled
											? 'bg-emerald-500'
											: 'bg-gray-300 dark:bg-gray-700'}"
									></div>
									<div class="min-w-0 flex-1">
										<div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
											{widget.name}
										</div>
										<div class="mt-0.5 truncate text-xs text-gray-500">
											{widget.model_id}
										</div>
										<div class="mt-1 text-xs text-gray-400">
											{$i18n.t('Updated')} {dayjs.unix(widget.updated_at).fromNow()}
										</div>
									</div>
									<div class="shrink-0 text-xs text-gray-500">
										{widget.enabled ? $i18n.t('On') : $i18n.t('Off')}
									</div>
								</div>
							</button>
						{/each}
					{/if}
				</div>
			</section>

			<section class="min-w-0 rounded-lg border border-gray-100 dark:border-gray-850">
				<div class="border-b border-gray-100 px-4 py-3 dark:border-gray-850">
					<div class="flex flex-wrap items-center gap-2">
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium">
								{selectedWidget ? $i18n.t('Edit Widget') : $i18n.t('Create Widget')}
							</div>
							<div class="truncate text-xs text-gray-500">
								{selectedWidget?.id ?? $i18n.t('Configure the widget before copying an embed code')}
							</div>
						</div>
						{#if selectedWidget}
							<div class="flex items-center gap-1">
								<Tooltip content={$i18n.t('Rotate token')}>
									<button
										class="rounded-lg p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
										aria-label={$i18n.t('Rotate token')}
										on:click={() => selectedWidget && rotateToken(selectedWidget)}
									>
										<ArrowPath className="size-4" />
									</button>
								</Tooltip>
								<Tooltip content={$i18n.t('Delete')}>
									<button
										class="rounded-lg p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
										aria-label={$i18n.t('Delete')}
										on:click={() => selectedWidget && confirmDelete(selectedWidget)}
									>
										<GarbageBin className="size-4" />
									</button>
								</Tooltip>
							</div>
						{/if}
					</div>
				</div>

				<div class="grid grid-cols-1 lg:grid-cols-2 gap-4 p-4">
					<div class="space-y-3">
						<label class="block">
							<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
								{$i18n.t('Name')}
							</div>
							<input
								class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
								bind:value={form.name}
								placeholder={$i18n.t('Support assistant')}
							/>
						</label>

						<label class="block">
							<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
								{$i18n.t('Model')}
							</div>
							<select
								class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
								bind:value={form.model_id}
							>
								<option value="" disabled>{$i18n.t('Select a model')}</option>
								{#each $models ?? [] as model (model.id)}
									<option value={model.id}>{model.name ?? model.id}</option>
								{/each}
							</select>
							{#if selectedModelName}
								<div class="mt-1 truncate text-xs text-gray-500">{selectedModelName}</div>
							{/if}
						</label>

						<label class="block">
							<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
								{$i18n.t('System prompt')}
							</div>
							<textarea
								class="min-h-28 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
								bind:value={form.system_prompt}
							></textarea>
						</label>

						<label class="block">
							<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
								{$i18n.t('Welcome message')}
							</div>
							<textarea
								class="min-h-20 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
								bind:value={form.welcome_message}
							></textarea>
						</label>
					</div>

					<div class="space-y-3">
						<div class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Enabled')}</div>
								<div class="text-xs text-gray-500">
									{form.enabled ? $i18n.t('Public embed accepts chat') : $i18n.t('Public embed is paused')}
								</div>
							</div>
							<Switch bind:state={form.enabled} ariaLabel={$i18n.t('Enabled')} />
						</div>

						<label class="block">
							<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
								{$i18n.t('Allowed domains')}
							</div>
							<textarea
								class="min-h-24 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
								bind:value={domainsText}
								placeholder={'example.com\n*.example.com'}
							></textarea>
						</label>

						{#if selectedWidget}
							<div>
								<div class="mb-1 flex items-center justify-between">
									<div class="text-xs font-medium text-gray-600 dark:text-gray-400">
										{$i18n.t('Embed code')}
									</div>
									<Tooltip content={$i18n.t('Copy')}>
										<button
											class="rounded-lg p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
											aria-label={$i18n.t('Copy')}
											on:click={copyEmbed}
										>
											<Clipboard className="size-4" />
										</button>
									</Tooltip>
								</div>
								<textarea
									readonly
									class="min-h-24 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs outline-none dark:border-gray-800 dark:bg-gray-900"
									value={embedCode}
								></textarea>
							</div>

							<div>
								<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
									{$i18n.t('Token')}
								</div>
								<input
									readonly
									class="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs outline-none dark:border-gray-800 dark:bg-gray-900"
									value={selectedWidget.token}
								/>
							</div>
						{/if}
					</div>
				</div>

				<div
					class="flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 px-4 py-3 dark:border-gray-850"
				>
					{#if selectedWidget}
						<button
							class="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
							on:click={() => selectedWidget && toggleWidget(selectedWidget)}
						>
							{selectedWidget.enabled ? $i18n.t('Disable widget') : $i18n.t('Enable widget')}
						</button>
					{:else}
						<div></div>
					{/if}
					<button
						class="inline-flex min-w-20 items-center justify-center rounded-lg bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-black"
						disabled={saving}
						on:click={saveWidget}
					>
						{#if saving}
							<Spinner className="size-4" />
						{:else}
							{selectedWidget ? $i18n.t('Save') : $i18n.t('Create')}
						{/if}
					</button>
				</div>
			</section>
		</div>
	</div>
{:else}
	<div class="flex h-full items-center justify-center">
		<Spinner />
	</div>
{/if}
