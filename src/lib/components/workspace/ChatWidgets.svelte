<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';

	import { models, workspaceActions, workspaceCounts } from '$lib/stores';
	import {
		DEFAULT_WIDGET_THEME,
		createChatWidget,
		deleteChatWidget,
		deleteChatWidgetSession,
		getChatWidgetSessionMessages,
		getChatWidgetSessions,
		getChatWidgets,
		rotateChatWidgetToken,
		updateChatWidget,
		type ChatWidget,
		type ChatWidgetForm,
		type ChatWidgetMessage,
		type ChatWidgetSession,
		type ChatWidgetTheme
	} from '$lib/apis/widgets';
	import { getTools } from '$lib/apis/tools';
	import { copyToClipboard } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ChatWidgetPreview from '$lib/components/workspace/ChatWidgetPreview.svelte';
	import WidgetCrawl from '$lib/components/workspace/WidgetCrawl.svelte';
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
	let conversations: ChatWidgetSession[] = [];
	let conversationMessages: ChatWidgetMessage[] = [];
	let selectedConversation: ChatWidgetSession | null = null;
	let conversationDeleteTarget: ChatWidgetSession | null = null;
	let showConversationDeleteConfirm = false;
	let conversationsLoading = false;
	let messagesLoading = false;
	let mcpServers: { id: string; name: string; description: string; authenticated?: boolean }[] = [];
	let avatarInputElement: HTMLInputElement;

	let form: ChatWidgetForm = {
		name: '',
		model_id: '',
		system_prompt: '',
		welcome_message: '',
		enabled: true,
		allowed_domains: [],
		mcp_enabled: false,
		mcp_tool_ids: [],
		theme: structuredClone(DEFAULT_WIDGET_THEME)
	};
	let domainsText = '';

	$: embedCode = selectedWidget ? buildEmbedCode(selectedWidget) : '';
	$: selectedModelName =
		$models?.find((model) => model.id === form.model_id)?.name ?? form.model_id ?? '';
	$: unavailableMcpToolIds = form.mcp_tool_ids.filter(
		(toolId) => !mcpServers.some((server) => server.id === toolId)
	);
	$: if (!form.model_id && $models?.length) {
		form = { ...form, model_id: $models[0].id };
	}

	type ThemeColorField =
		| 'primary_color'
		| 'primary_text_color'
		| 'header_background_color'
		| 'header_text_color'
		| 'background_color'
		| 'assistant_bubble_color'
		| 'assistant_text_color'
		| 'user_bubble_color'
		| 'user_text_color';

	const colorFields: { label: string; key: ThemeColorField }[] = [
		{ label: 'Primary', key: 'primary_color' },
		{ label: 'Text on primary', key: 'primary_text_color' },
		{ label: 'Header background', key: 'header_background_color' },
		{ label: 'Header text', key: 'header_text_color' },
		{ label: 'Chat background', key: 'background_color' },
		{ label: 'Assistant bubble', key: 'assistant_bubble_color' },
		{ label: 'Assistant text', key: 'assistant_text_color' },
		{ label: 'User bubble', key: 'user_bubble_color' },
		{ label: 'User text', key: 'user_text_color' }
	];

	const fontOptions: { label: string; value: ChatWidgetTheme['font_family'] }[] = [
		{ label: 'System', value: 'system' },
		{ label: 'Arial', value: 'arial' },
		{ label: 'Verdana', value: 'verdana' },
		{ label: 'Tahoma', value: 'tahoma' },
		{ label: 'Trebuchet', value: 'trebuchet' },
		{ label: 'Georgia', value: 'georgia' },
		{ label: 'Times New Roman', value: 'times' },
		{ label: 'Courier', value: 'courier' }
	];

	const resetForm = () => {
		selectedWidget = null;
		conversations = [];
		conversationMessages = [];
		selectedConversation = null;
		conversationDeleteTarget = null;
		form = {
			name: '',
			model_id: $models?.[0]?.id ?? '',
			system_prompt: '',
			welcome_message: '',
			enabled: true,
			allowed_domains: [],
			mcp_enabled: false,
			mcp_tool_ids: [],
			theme: structuredClone(DEFAULT_WIDGET_THEME)
		};
		domainsText = '';
	};

	const editWidget = (widget: ChatWidget) => {
		selectedWidget = widget;
		selectedConversation = null;
		conversationMessages = [];
		form = {
			name: widget.name,
			model_id: widget.model_id,
			system_prompt: widget.system_prompt ?? '',
			welcome_message: widget.welcome_message ?? '',
			enabled: widget.enabled,
			allowed_domains: widget.allowed_domains ?? [],
			mcp_enabled: widget.mcp_enabled,
			mcp_tool_ids: [...(widget.mcp_tool_ids ?? [])],
			theme: { ...DEFAULT_WIDGET_THEME, ...(widget.theme ?? {}) }
		};
		domainsText = (widget.allowed_domains ?? []).join('\n');
		loadConversations(widget);
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
		allowed_domains: normalizeDomains(),
		mcp_tool_ids: form.mcp_enabled ? form.mcp_tool_ids : [],
		theme: {
			...form.theme,
			header_title: form.theme.header_title?.trim() || null,
			header_subtitle: form.theme.header_subtitle?.trim() || null,
			input_placeholder: form.theme.input_placeholder?.trim() || 'Type a message'
		}
	});

	const updateTheme = (updates: Partial<ChatWidgetTheme>) => {
		form = { ...form, theme: { ...form.theme, ...updates } };
	};

	const toggleMcpTool = (toolId: string) => {
		form = {
			...form,
			mcp_tool_ids: form.mcp_tool_ids.includes(toolId)
				? form.mcp_tool_ids.filter((id) => id !== toolId)
				: [...form.mcp_tool_ids, toolId]
		};
	};

	const removeMcpTool = (toolId: string) => {
		form = { ...form, mcp_tool_ids: form.mcp_tool_ids.filter((id) => id !== toolId) };
	};

	const normalizeColorField = (key: ThemeColorField) => {
		const value = form.theme[key];
		updateTheme({
			[key]: /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : DEFAULT_WIDGET_THEME[key]
		});
	};

	const resetColors = () => {
		form = {
			...form,
			theme: {
				...form.theme,
				...Object.fromEntries(colorFields.map(({ key }) => [key, DEFAULT_WIDGET_THEME[key]]))
			}
		};
	};

	const resetAppearance = () => {
		form = { ...form, theme: structuredClone(DEFAULT_WIDGET_THEME) };
	};

	const uploadAvatar = (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;

		if (file.size > 5 * 1024 * 1024) {
			toast.error($i18n.t('Image is too large'));
			input.value = '';
			return;
		}

		const reader = new FileReader();
		reader.onload = (readerEvent) => {
			const originalImageUrl = `${readerEvent.target?.result}`;
			const img = new Image();
			img.src = originalImageUrl;

			img.onload = () => {
				const canvas = document.createElement('canvas');
				const ctx = canvas.getContext('2d');
				if (!ctx) return;

				const size = 128;
				const aspectRatio = img.width / img.height;
				let newWidth;
				let newHeight;
				if (aspectRatio > 1) {
					newWidth = size * aspectRatio;
					newHeight = size;
				} else {
					newWidth = size;
					newHeight = size / aspectRatio;
				}

				canvas.width = size;
				canvas.height = size;
				ctx.drawImage(img, (size - newWidth) / 2, (size - newHeight) / 2, newWidth, newHeight);

				let avatar = canvas.toDataURL('image/webp', 0.85);
				if (avatar.length > 150000) {
					avatar = canvas.toDataURL('image/webp', 0.6);
				}
				if (avatar.length > 150000) {
					toast.error($i18n.t('Image is too large'));
				} else {
					updateTheme({ avatar_url: avatar });
				}
				input.value = '';
			};
		};
		reader.readAsDataURL(file);
	};

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
		if (form.mcp_enabled && form.mcp_tool_ids.length === 0) {
			toast.error($i18n.t('Select at least one MCP server'));
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

	const loadConversations = async (widget = selectedWidget) => {
		if (!widget) return;

		const widgetId = widget.id;
		conversationsLoading = true;
		const res = await getChatWidgetSessions(localStorage.token, widgetId).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		conversationsLoading = false;

		if (res && selectedWidget?.id === widgetId) {
			conversations = res;
			if (selectedConversation && !res.some((session) => session.id === selectedConversation?.id)) {
				selectedConversation = null;
				conversationMessages = [];
			}
		}
	};

	const openConversation = async (session: ChatWidgetSession) => {
		if (!selectedWidget) return;

		const widgetId = selectedWidget.id;
		selectedConversation = session;
		conversationMessages = [];
		messagesLoading = true;
		const res = await getChatWidgetSessionMessages(localStorage.token, widgetId, session.id).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		messagesLoading = false;

		if (res && selectedWidget?.id === widgetId && selectedConversation?.id === session.id) {
			conversationMessages = res;
		}
	};

	const confirmConversationDelete = (session: ChatWidgetSession) => {
		conversationDeleteTarget = session;
		showConversationDeleteConfirm = true;
	};

	const deleteSelectedConversation = async () => {
		if (!selectedWidget || !conversationDeleteTarget) return;

		const deletedSessionId = conversationDeleteTarget.id;
		const res = await deleteChatWidgetSession(
			localStorage.token,
			selectedWidget.id,
			deletedSessionId
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Deleted'));
			conversations = conversations.filter((session) => session.id !== deletedSessionId);
			if (selectedConversation?.id === deletedSessionId) {
				selectedConversation = null;
				conversationMessages = [];
			}
			conversationDeleteTarget = null;
		}
	};

	const contentToText = (content: unknown): string => {
		if (typeof content === 'string') return content;
		if (Array.isArray(content)) {
			return content
				.map((item) => {
					if (typeof item === 'string') return item;
					if (item && typeof item === 'object') {
						const value = item as Record<string, unknown>;
						return typeof value.text === 'string'
							? value.text
							: typeof value.content === 'string'
								? value.content
								: '';
					}
					return '';
				})
				.filter(Boolean)
				.join('');
		}
		if (content && typeof content === 'object') return JSON.stringify(content, null, 2);
		return '';
	};

	const shortId = (id: string) => (id.length > 12 ? `${id.slice(0, 8)}...${id.slice(-4)}` : id);

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
				label: $i18n.t('New widget'),
				onClick: resetForm
			}
		]);
		resetForm();
		const tools = await getTools(localStorage.token).catch(() => []);
		mcpServers = (tools ?? [])
			.filter((tool) => tool.id.startsWith('server:mcp:'))
			.map((tool) => ({
				id: tool.id,
				name: tool.name,
				description: tool.meta?.description ?? '',
				authenticated: tool.authenticated
			}));
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

<ConfirmDialog
	bind:show={showConversationDeleteConfirm}
	title={$i18n.t('Delete conversation?')}
	message={$i18n.t('This will remove the widget conversation and its chat in your chat history.')}
	on:confirm={deleteSelectedConversation}
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
						type="button"
						class="px-3 py-1.5 text-sm font-medium rounded-lg bg-black text-white dark:bg-white dark:text-black"
						on:click={resetForm}
					>
						{$i18n.t('New widget')}
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
											{$i18n.t('Updated')}
											{dayjs.unix(widget.updated_at).fromNow()}
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
						<div
							class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
						>
							<div>
								<div class="text-sm font-medium">{$i18n.t('Enabled')}</div>
								<div class="text-xs text-gray-500">
									{form.enabled
										? $i18n.t('Public embed accepts chat')
										: $i18n.t('Public embed is paused')}
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

						<div class="rounded-lg border border-gray-100 p-3 dark:border-gray-850">
							<div class="flex items-center justify-between gap-3">
								<div>
									<div class="text-sm font-medium">{$i18n.t('MCP tools')}</div>
									<div class="text-xs text-gray-500">
										{form.mcp_enabled
											? $i18n.t('Let this widget call MCP servers')
											: $i18n.t('Tools are off')}
									</div>
								</div>
								<Switch bind:state={form.mcp_enabled} ariaLabel={$i18n.t('MCP tools')} />
							</div>

							{#if form.mcp_enabled}
								<div class="mt-3 space-y-2">
									{#if mcpServers.length === 0}
										<div class="text-xs text-gray-500">
											{$i18n.t(
												'No MCP servers available. Ask an admin to add one in Settings > External Tools.'
											)}
										</div>
									{:else}
										{#each mcpServers as server (server.id)}
											<label
												class="flex items-start gap-2 rounded-lg border border-gray-100 px-2.5 py-2 dark:border-gray-850"
											>
												<input
													type="checkbox"
													class="mt-1"
													checked={form.mcp_tool_ids.includes(server.id)}
													disabled={server.authenticated === false}
													on:change={() => toggleMcpTool(server.id)}
												/>
												<div class="min-w-0 flex-1">
													<div class="truncate text-sm font-medium">{server.name}</div>
													{#if server.description}
														<div class="truncate text-xs text-gray-500">{server.description}</div>
													{/if}
													{#if server.authenticated === false}
														<div class="mt-1 text-xs text-amber-600 dark:text-amber-400">
															{$i18n.t('Sign in to this server from a normal chat first')}
														</div>
													{/if}
												</div>
											</label>
										{/each}
									{/if}

									{#each unavailableMcpToolIds as toolId (toolId)}
										<div
											class="flex items-center justify-between gap-2 rounded-lg border border-amber-200 px-2.5 py-2 dark:border-amber-900"
										>
											<div class="min-w-0">
												<div class="text-sm font-medium">{$i18n.t('Unavailable')}</div>
												<div class="truncate font-mono text-xs text-gray-500">{toolId}</div>
											</div>
											<button
												type="button"
												class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
												on:click={() => removeMcpTool(toolId)}
											>
												{$i18n.t('Remove')}
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>

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

				<div class="border-t border-gray-100 p-4 dark:border-gray-850">
					<div class="mb-3 text-sm font-medium">{$i18n.t('Appearance')}</div>
					<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
						<div class="space-y-4">
							<div>
								<div class="mb-2 text-xs font-medium uppercase text-gray-500">
									{$i18n.t('Avatar')}
								</div>
								<div class="flex items-center gap-3">
									<div
										class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-gray-100 dark:border-gray-850"
										style={`background: ${form.theme.primary_color}; color: ${form.theme.primary_text_color};`}
									>
										{#if form.theme.avatar_url}
											<img src={form.theme.avatar_url} alt="" class="h-full w-full object-cover" />
										{:else}
											<ChatBubble className="size-5" />
										{/if}
									</div>
									<div class="flex flex-wrap items-center gap-2">
										<input
											bind:this={avatarInputElement}
											type="file"
											hidden
											accept="image/png,image/jpeg,image/webp,image/gif"
											on:change={uploadAvatar}
										/>
										<button
											type="button"
											class="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900"
											on:click={() => avatarInputElement?.click()}
										>
											{$i18n.t('Upload')}
										</button>
										{#if form.theme.avatar_url}
											<button
												type="button"
												class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:text-red-600"
												on:click={() => updateTheme({ avatar_url: null, launcher_icon: 'chat' })}
											>
												{$i18n.t('Remove')}
											</button>
										{/if}
									</div>
								</div>
								<label class="mt-3 block">
									<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
										{$i18n.t('Launcher icon')}
									</div>
									<select
										class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 disabled:opacity-50 dark:border-gray-800"
										bind:value={form.theme.launcher_icon}
										disabled={!form.theme.avatar_url}
									>
										<option value="chat">{$i18n.t('Chat icon')}</option>
										<option value="avatar">{$i18n.t('Avatar')}</option>
									</select>
								</label>
							</div>

							<div>
								<div class="mb-2 flex items-center justify-between gap-2">
									<div class="text-xs font-medium uppercase text-gray-500">{$i18n.t('Colors')}</div>
									<button
										type="button"
										class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
										on:click={resetColors}
									>
										{$i18n.t('Reset colors')}
									</button>
								</div>
								<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
									{#each colorFields as field (field.key)}
										<label class="block">
											<div class="mb-1 text-xs text-gray-500">{$i18n.t(field.label)}</div>
											<div class="flex items-center gap-2">
												<input
													type="color"
													class="h-9 w-11 shrink-0 rounded border border-gray-200 bg-transparent p-1 dark:border-gray-800"
													bind:value={form.theme[field.key]}
													on:blur={() => normalizeColorField(field.key)}
												/>
												<input
													class="min-w-0 flex-1 rounded-lg border border-gray-200 bg-transparent px-2 py-1.5 font-mono text-xs outline-none focus:border-gray-400 dark:border-gray-800"
													bind:value={form.theme[field.key]}
													on:blur={() => normalizeColorField(field.key)}
												/>
											</div>
										</label>
									{/each}
								</div>
							</div>

							<div>
								<div class="mb-2 text-xs font-medium uppercase text-gray-500">
									{$i18n.t('Text')}
								</div>
								<div class="space-y-3">
									<label class="block">
										<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
											{$i18n.t('Font')}
										</div>
										<select
											class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
											bind:value={form.theme.font_family}
										>
											{#each fontOptions as option (option.value)}
												<option value={option.value}>{option.label}</option>
											{/each}
										</select>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Font size')}</span>
											<span>{form.theme.font_size}px</span>
										</div>
										<input
											type="range"
											min="12"
											max="20"
											step="1"
											class="w-full"
											bind:value={form.theme.font_size}
										/>
									</label>

									<label class="block">
										<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
											{$i18n.t('Header title')}
										</div>
										<input
											class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
											bind:value={form.theme.header_title}
											maxlength="60"
											placeholder={form.name}
										/>
									</label>

									<label class="block">
										<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
											{$i18n.t('Header subtitle')}
										</div>
										<input
											class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
											bind:value={form.theme.header_subtitle}
											maxlength="80"
											placeholder="Online"
										/>
									</label>

									<label class="block">
										<div class="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">
											{$i18n.t('Input placeholder')}
										</div>
										<input
											class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:border-gray-800"
											bind:value={form.theme.input_placeholder}
											maxlength="120"
										/>
									</label>

									<div
										class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
									>
										<div class="text-sm font-medium">{$i18n.t('Show status')}</div>
										<Switch
											bind:state={form.theme.show_status}
											ariaLabel={$i18n.t('Show status')}
										/>
									</div>
								</div>
							</div>

							<div>
								<div class="mb-2 text-xs font-medium uppercase text-gray-500">
									{$i18n.t('Layout')}
								</div>
								<div class="space-y-3">
									<div>
										<div class="mb-1 text-xs text-gray-500">{$i18n.t('Position')}</div>
										<div
											class="inline-flex rounded-lg border border-gray-200 p-0.5 dark:border-gray-800"
										>
											{#each ['left', 'right'] as position}
												<button
													type="button"
													class="rounded-md px-3 py-1.5 text-sm capitalize {form.theme.position ===
													position
														? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
														: 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-100'}"
													on:click={() =>
														updateTheme({ position: position as ChatWidgetTheme['position'] })}
												>
													{$i18n.t(position === 'left' ? 'Left' : 'Right')}
												</button>
											{/each}
										</div>
									</div>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Horizontal offset')}</span><span>{form.theme.offset_x}px</span
											>
										</div>
										<input
											type="range"
											min="0"
											max="120"
											class="w-full"
											bind:value={form.theme.offset_x}
										/>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Vertical offset')}</span><span>{form.theme.offset_y}px</span>
										</div>
										<input
											type="range"
											min="0"
											max="120"
											class="w-full"
											bind:value={form.theme.offset_y}
										/>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Panel width')}</span><span>{form.theme.panel_width}px</span>
										</div>
										<input
											type="range"
											min="300"
											max="480"
											step="10"
											class="w-full"
											bind:value={form.theme.panel_width}
										/>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Panel height')}</span><span>{form.theme.panel_height}px</span>
										</div>
										<input
											type="range"
											min="400"
											max="760"
											step="10"
											class="w-full"
											bind:value={form.theme.panel_height}
										/>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Panel corner radius')}</span><span
												>{form.theme.panel_radius}px</span
											>
										</div>
										<input
											type="range"
											min="0"
											max="24"
											class="w-full"
											bind:value={form.theme.panel_radius}
										/>
									</label>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Bubble corner radius')}</span><span
												>{form.theme.bubble_radius}px</span
											>
										</div>
										<input
											type="range"
											min="0"
											max="24"
											class="w-full"
											bind:value={form.theme.bubble_radius}
										/>
									</label>

									<div>
										<div class="mb-1 text-xs text-gray-500">{$i18n.t('Launcher shape')}</div>
										<div
											class="inline-flex rounded-lg border border-gray-200 p-0.5 dark:border-gray-800"
										>
											{#each ['circle', 'rounded', 'square'] as shape}
												<button
													type="button"
													class="rounded-md px-3 py-1.5 text-sm capitalize {form.theme
														.launcher_shape === shape
														? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
														: 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-100'}"
													on:click={() =>
														updateTheme({
															launcher_shape: shape as ChatWidgetTheme['launcher_shape']
														})}
												>
													{$i18n.t(
														shape === 'circle'
															? 'Circle'
															: shape === 'rounded'
																? 'Rounded'
																: 'Square'
													)}
												</button>
											{/each}
										</div>
									</div>

									<label class="block">
										<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
											<span>{$i18n.t('Launcher size')}</span><span
												>{form.theme.launcher_size}px</span
											>
										</div>
										<input
											type="range"
											min="44"
											max="72"
											step="2"
											class="w-full"
											bind:value={form.theme.launcher_size}
										/>
									</label>
								</div>
							</div>

							<button
								type="button"
								class="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
								on:click={resetAppearance}
							>
								{$i18n.t('Reset appearance')}
							</button>
						</div>

						<ChatWidgetPreview
							theme={form.theme}
							name={form.name}
							welcomeMessage={form.welcome_message}
						/>
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
						type="button"
						class="inline-flex min-w-20 items-center justify-center rounded-lg bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-black"
						disabled={saving}
						on:click={saveWidget}
					>
						{#if saving}
							<Spinner className="size-4" />
						{:else}
							{selectedWidget ? $i18n.t('Save') : $i18n.t('Create widget')}
						{/if}
					</button>
				</div>
			</section>
		</div>

		{#if selectedWidget}
			{#key selectedWidget.id}
				<WidgetCrawl widget={selectedWidget} />
			{/key}
		{/if}

		{#if selectedWidget}
			<section class="mt-3 rounded-lg border border-gray-100 dark:border-gray-850">
				<div
					class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-850"
				>
					<div>
						<div class="text-sm font-medium">{$i18n.t('Conversations')}</div>
						<div class="text-xs text-gray-500">
							{conversations.length}
							{$i18n.t('sessions')}
						</div>
					</div>
					<Tooltip content={$i18n.t('Refresh')}>
						<button
							class="rounded-lg p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
							aria-label={$i18n.t('Refresh')}
							on:click={() => loadConversations()}
						>
							{#if conversationsLoading}
								<Spinner className="size-4" />
							{:else}
								<ArrowPath className="size-4" />
							{/if}
						</button>
					</Tooltip>
				</div>

				<div class="grid grid-cols-1 lg:grid-cols-[minmax(280px,420px)_1fr]">
					<div
						class="min-h-72 border-b border-gray-100 p-3 dark:border-gray-850 lg:border-b-0 lg:border-r"
					>
						{#if conversationsLoading && conversations.length === 0}
							<div class="flex h-48 items-center justify-center">
								<Spinner />
							</div>
						{:else if conversations.length === 0}
							<div
								class="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-gray-200 px-4 text-center dark:border-gray-800"
							>
								<ChatBubble className="size-6 text-gray-400" />
								<div class="mt-2 text-sm font-medium">{$i18n.t('No conversations yet')}</div>
							</div>
						{:else}
							<div class="flex max-h-[32rem] flex-col gap-1 overflow-auto pr-1">
								{#each conversations as session (session.id)}
									<div
										class="group flex gap-2 rounded-lg border px-3 py-2 transition {selectedConversation?.id ===
										session.id
											? 'border-gray-400 bg-gray-50 dark:border-gray-600 dark:bg-gray-900'
											: 'border-gray-100 hover:bg-gray-50 dark:border-gray-850 dark:hover:bg-gray-900'}"
									>
										<button
											class="min-w-0 flex-1 text-left"
											on:click={() => openConversation(session)}
										>
											<div class="flex items-start justify-between gap-2">
												<div class="min-w-0">
													<div class="truncate text-sm font-medium">
														{session.title || shortId(session.id)}
													</div>
													<div class="mt-0.5 truncate font-mono text-[11px] text-gray-500">
														{session.id}
													</div>
												</div>
												<div class="shrink-0 text-xs text-gray-500">
													{session.message_count}
												</div>
											</div>
											<div class="mt-2 grid grid-cols-1 gap-1 text-xs text-gray-500 sm:grid-cols-2">
												<div class="truncate">
													{$i18n.t('Created')}
													{dayjs.unix(session.created_at).format('MMM D, HH:mm')}
												</div>
												<div class="truncate sm:text-right">
													{$i18n.t('Active')}
													{dayjs.unix(session.last_activity_at).fromNow()}
												</div>
												<div class="truncate sm:col-span-2">
													{$i18n.t('Model')}: {session.model_id || selectedWidget.model_id}
												</div>
											</div>
										</button>
										{#if session.chat_id}
											<Tooltip content={$i18n.t('Open in chat')}>
												<a
													href={`/c/${session.chat_id}`}
													class="h-8 w-8 shrink-0 rounded-lg p-1.5 text-gray-400 opacity-100 hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-850 dark:hover:text-gray-100 lg:opacity-0 lg:group-hover:opacity-100"
													aria-label={$i18n.t('Open in chat')}
												>
													<ChatBubble className="size-4" />
												</a>
											</Tooltip>
										{/if}
										<Tooltip content={$i18n.t('Delete')}>
											<button
												class="h-8 w-8 shrink-0 rounded-lg p-1.5 text-gray-400 opacity-100 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950 lg:opacity-0 lg:group-hover:opacity-100"
												aria-label={$i18n.t('Delete')}
												on:click={() => confirmConversationDelete(session)}
											>
												<GarbageBin className="size-4" />
											</button>
										</Tooltip>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					<div class="min-h-72 p-3">
						{#if selectedConversation}
							<div class="mb-3 flex flex-wrap items-start justify-between gap-2">
								<div class="min-w-0">
									<div class="truncate text-sm font-medium">
										{selectedConversation.title || shortId(selectedConversation.id)}
									</div>
									<div class="truncate font-mono text-xs text-gray-500">
										{selectedConversation.id}
									</div>
								</div>
								<div class="flex shrink-0 items-center gap-3">
									{#if selectedConversation.chat_id}
										<a
											href={`/c/${selectedConversation.chat_id}`}
											class="inline-flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
										>
											<ChatBubble className="size-3.5" />
											{$i18n.t('Open in chat')}
										</a>
									{/if}
									<div class="text-xs text-gray-500">
										{selectedConversation.message_count}
										{$i18n.t('messages')}
									</div>
								</div>
							</div>

							{#if messagesLoading}
								<div class="flex h-48 items-center justify-center">
									<Spinner />
								</div>
							{:else}
								<div
									class="flex max-h-[32rem] flex-col gap-3 overflow-auto rounded-lg bg-gray-50 p-3 dark:bg-gray-900"
								>
									{#each conversationMessages as message (message.id)}
										<div class="flex {message.role === 'user' ? 'justify-end' : 'justify-start'}">
											<div
												class="max-w-[82%] rounded-xl border px-3 py-2 text-sm leading-relaxed {message.role ===
												'user'
													? 'border-gray-900 bg-gray-900 text-white dark:border-gray-100 dark:bg-gray-100 dark:text-gray-900'
													: message.error
														? 'border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100'
														: 'border-gray-200 bg-white text-gray-900 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-100'}"
											>
												<div
													class="mb-1 flex items-center justify-between gap-3 text-[11px] opacity-70"
												>
													<span class="capitalize">{message.role}</span>
													<span>{dayjs.unix(message.created_at).format('MMM D, HH:mm')}</span>
												</div>
												<div class="whitespace-pre-wrap break-words">
													{contentToText(message.content)}
												</div>
											</div>
										</div>
									{/each}
								</div>
							{/if}
						{:else}
							<div
								class="flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed border-gray-200 px-4 text-center dark:border-gray-800"
							>
								<ChatBubble className="size-6 text-gray-400" />
								<div class="mt-2 text-sm font-medium">{$i18n.t('Select a conversation')}</div>
							</div>
						{/if}
					</div>
				</div>
			</section>
		{/if}
	</div>
{:else}
	<div class="flex h-full items-center justify-center">
		<Spinner />
	</div>
{/if}
