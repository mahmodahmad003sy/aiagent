import { marked } from 'marked';
import DOMPurify from 'dompurify';

// Shared by streaming, completed and restored widget answers. No remote assets.
export function renderMarkdown(text) {
	const fragment = DOMPurify.sanitize(marked.parse(text || '', { gfm: true, breaks: true }), {
		RETURN_DOM_FRAGMENT: true,
		ALLOWED_TAGS: [
			'p',
			'br',
			'strong',
			'em',
			'del',
			'a',
			'ul',
			'ol',
			'li',
			'blockquote',
			'pre',
			'code',
			'h1',
			'h2',
			'h3',
			'h4',
			'h5',
			'h6',
			'hr',
			'table',
			'thead',
			'tbody',
			'tr',
			'th',
			'td'
		],
		ALLOWED_ATTR: ['href', 'title', 'start'],
		ALLOW_DATA_ATTR: false
	});
	fragment.querySelectorAll('a').forEach((link) => {
		const href = link.getAttribute('href') || '';
		if (!/^https?:\/\//i.test(href)) {
			link.removeAttribute('href');
			return;
		}
		link.target = '_blank';
		link.rel = 'noopener noreferrer';
	});
	fragment.querySelectorAll('table').forEach((table) => {
		const wrapper = document.createElement('div');
		wrapper.className = 'owui-table-scroll';
		wrapper.tabIndex = 0;
		wrapper.setAttribute('role', 'region');
		wrapper.setAttribute('aria-label', 'Table; scroll horizontally for more columns');
		table.replaceWith(wrapper);
		wrapper.appendChild(table);
	});
	return fragment;
}
