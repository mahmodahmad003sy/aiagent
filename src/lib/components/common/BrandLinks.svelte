<script lang="ts">
	import { BRANDING } from '$lib/constants';

	export let className = '';
	export let linkClassName = '';

	const LABELS: Record<string, string> = {
		website: 'Website',
		github: 'GitHub',
		discord: 'Discord',
		x: 'X'
	};

	$: links = Object.entries(LABELS)
		.map(([key, label]) => ({ label, href: BRANDING.links?.[key] ?? '' }))
		.filter((link) => link.href);
</script>

{#if links.length > 0}
	<div class={className}>
		{#each links as link}
			<a class={linkClassName} href={link.href} target="_blank" rel="noopener noreferrer"
				>{link.label}</a
			>
		{/each}
	</div>
{/if}
