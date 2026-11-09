import { describe, expect, it } from 'vitest';
import { crawlTree } from './crawlTree';
import type { CrawlItem } from '$lib/apis/widgets/crawl';
const item = (url: string, found_on?: string) =>
	({ id: url, url, found_on, kind: 'page' }) as CrawlItem;
describe('crawl provenance tree', () => {
	it('orders children by discovery parent rather than URL path', () => {
		const rows = crawlTree([
			item('/different?id=43', '/home'),
			item('/home'),
			item('/nested', '/different?id=43')
		]);
		expect(rows.map(({ item, level }) => [item.url, level])).toEqual([
			['/home', 0],
			['/different?id=43', 1],
			['/nested', 2]
		]);
	});
	it('collapses descendants without promoting them to roots', () => {
		expect(
			crawlTree(
				[item('/home'), item('/child', '/home'), item('/leaf', '/child')],
				new Set(['/home'])
			).map((r) => r.item.url)
		).toEqual(['/home']);
	});
	it('retains orphaned and cyclic results exactly once', () => {
		const rows = crawlTree([item('/orphan', '/missing'), item('/a', '/b'), item('/b', '/a')]);
		expect(new Set(rows.map((r) => r.item.url)).size).toBe(3);
		expect(rows.length).toBe(3);
	});
});
