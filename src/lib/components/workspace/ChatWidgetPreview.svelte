<script lang="ts">
	import { WIDGET_FONT_STACKS, type ChatWidgetTheme } from '$lib/apis/widgets';

	export let theme: ChatWidgetTheme;
	export let name: string;
	export let welcomeMessage: string | null;

	const launcherRadius = {
		circle: '999px',
		rounded: '16px',
		square: '6px'
	};

	$: fontFamily = WIDGET_FONT_STACKS[theme.font_family] ?? WIDGET_FONT_STACKS.system;
	$: panelSide = theme.position === 'left' ? 'left: 12px;' : 'right: 12px;';
	$: launcherSide = theme.position === 'left' ? 'left: 12px;' : 'right: 12px;';
	$: title = theme.header_title || name || 'Chat';
	$: subtitle = theme.header_subtitle || 'Online';
	$: assistantText = welcomeMessage || 'Hi! How can I help you?';
</script>

<div
	class="relative h-[560px] w-full overflow-hidden rounded-lg border border-gray-100 bg-gray-100 dark:border-gray-850 dark:bg-gray-900"
>
	<div
		class="absolute flex flex-col overflow-hidden border border-black/10 bg-white shadow-xl"
		style={`bottom: ${theme.launcher_size + 18 + 12}px; ${panelSide} width: min(${theme.panel_width}px, calc(100% - 24px)); height: 420px; border-radius: ${theme.panel_radius}px; font-family: ${fontFamily};`}
	>
		<div
			class="flex h-[62px] shrink-0 items-center justify-between border-b border-black/10 px-3"
			style={`background: ${theme.header_background_color}; color: ${theme.header_text_color};`}
		>
			<div class="flex min-w-0 items-center gap-2.5">
				<div
					class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[10px]"
					style={`background: ${theme.primary_color}; color: ${theme.primary_text_color};`}
				>
					{#if theme.avatar_url}
						<img src={theme.avatar_url} alt="" class="h-full w-full object-cover" />
					{:else}
						<svg class="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
							<path
								d="M5.5 4A3.5 3.5 0 0 0 2 7.5v5A3.5 3.5 0 0 0 5.5 16H7v3.2a.8.8 0 0 0 1.3.62L13.08 16h5.42A3.5 3.5 0 0 0 22 12.5v-5A3.5 3.5 0 0 0 18.5 4h-13Z"
							/>
						</svg>
					{/if}
				</div>

				<div class="min-w-0">
					<div
						class="truncate text-[15px] font-semibold leading-tight"
						style={`color: ${theme.header_text_color}; font-size: ${theme.font_size + 1}px;`}
					>
						{title}
					</div>
					{#if theme.show_status}
						<div
							class="mt-1 flex items-center gap-1.5 text-xs leading-tight opacity-70"
							style={`color: ${theme.header_text_color};`}
						>
							<span class="h-[7px] w-[7px] rounded-full bg-green-600"></span>
							<span class="truncate">{subtitle}</span>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<div
			class="flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden p-3.5"
			style={`background: ${theme.background_color};`}
		>
			<div
				class="max-w-[82%] whitespace-pre-wrap break-words border border-black/10 px-3 py-2 leading-relaxed shadow-sm"
				style={`background: ${theme.assistant_bubble_color}; color: ${theme.assistant_text_color}; border-radius: ${theme.bubble_radius}px; font-size: ${theme.font_size}px; font-family: ${fontFamily};`}
			>
				{assistantText}
			</div>
			<div
				class="ml-auto max-w-[82%] whitespace-pre-wrap break-words border px-3 py-2 leading-relaxed"
				style={`background: ${theme.user_bubble_color}; color: ${theme.user_text_color}; border-color: ${theme.user_bubble_color}; border-radius: ${theme.bubble_radius}px; font-size: ${theme.font_size}px; font-family: ${fontFamily};`}
			>
				I have a question about my order.
			</div>
			<div
				class="max-w-[82%] whitespace-pre-wrap break-words border border-black/10 px-3 py-2 leading-relaxed shadow-sm"
				style={`background: ${theme.assistant_bubble_color}; color: ${theme.assistant_text_color}; border-radius: ${theme.bubble_radius}px; font-size: ${theme.font_size}px; font-family: ${fontFamily};`}
			>
				Sure - what is your order number?
			</div>
		</div>

		<div class="flex shrink-0 items-end gap-2 border-t border-black/10 bg-white p-2.5">
			<textarea
				disabled
				readonly
				rows="1"
				aria-label="Message"
				value={theme.input_placeholder}
				class="min-h-[42px] flex-1 resize-none rounded-[10px] border border-gray-200 bg-white px-3 py-2.5 text-gray-400 outline-none"
				style={`font-size: ${theme.font_size}px; font-family: ${fontFamily};`}
			></textarea>
			<button
				type="button"
				disabled
				aria-label="Send message"
				class="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-[10px]"
				style={`background: ${theme.primary_color}; color: ${theme.primary_text_color};`}
			>
				<svg class="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
					<path d="M3.4 20.4 21.2 12 3.4 3.6 3 10.2l10.4 1.8L3 13.8l.4 6.6Z" />
				</svg>
			</button>
		</div>
	</div>

	<div
		class="absolute bottom-3 flex items-center justify-center overflow-hidden shadow-lg"
		style={`${launcherSide} width: ${theme.launcher_size}px; height: ${theme.launcher_size}px; border-radius: ${launcherRadius[theme.launcher_shape]}; background: ${theme.primary_color}; color: ${theme.primary_text_color};`}
	>
		{#if theme.launcher_icon === 'avatar' && theme.avatar_url}
			<img src={theme.avatar_url} alt="" class="h-full w-full object-cover" />
		{:else}
			<svg class="h-7 w-7 fill-current" viewBox="0 0 24 24" aria-hidden="true">
				<path
					d="M5.5 4A3.5 3.5 0 0 0 2 7.5v5A3.5 3.5 0 0 0 5.5 16H7v3.2a.8.8 0 0 0 1.3.62L13.08 16h5.42A3.5 3.5 0 0 0 22 12.5v-5A3.5 3.5 0 0 0 18.5 4h-13Zm0 2h13A1.5 1.5 0 0 1 20 7.5v5a1.5 1.5 0 0 1-1.5 1.5h-6.12L9 16.7V14H5.5A1.5 1.5 0 0 1 4 12.5v-5A1.5 1.5 0 0 1 5.5 6Z"
				/>
			</svg>
		{/if}
	</div>
</div>

<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
	Offsets apply on the live site only.
</div>
