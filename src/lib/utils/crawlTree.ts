import type { CrawlItem } from '$lib/apis/widgets/crawl';

export function crawlTree(items: CrawlItem[], collapsed = new Set<string>()) {
	const byUrl = new Map(items.map((item) => [item.url, item]));
	const children = new Map<string, CrawlItem[]>();
	const roots: CrawlItem[] = [];
	for (const item of items) {
		if (item.found_on && item.found_on !== item.url && byUrl.has(item.found_on)) {
			children.set(item.found_on, [...(children.get(item.found_on) ?? []), item]);
		} else roots.push(item);
	}
	const rows: { item: CrawlItem; level: number; hasChildren: boolean }[] = [];
	const visited = new Set<string>();
	const walk = (item: CrawlItem, level: number, hidden = false) => {
		if (visited.has(item.url)) return;
		visited.add(item.url);
		const descendants = children.get(item.url) ?? [];
		if (!hidden) rows.push({ item, level, hasChildren: descendants.length > 0 });
		for (const child of descendants) walk(child, level + 1, hidden || collapsed.has(item.url));
	};
	roots.forEach((item) => walk(item, 0));
	// Malformed or older manifests can contain cycles; keep every item reachable.
	items.forEach((item) => {
		if (!visited.has(item.url)) walk(item, 0);
	});
	return rows;
}
