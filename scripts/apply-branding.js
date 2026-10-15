/**
 * Applies branding/branding.json to the static files that can't read it at runtime:
 * copies brand images to every location the app serves them from, and regenerates
 * the PWA manifest, OpenSearch descriptor and initial <title> in src/app.html.
 *
 * Runs automatically before `npm run dev` / `npm run build`; run manually with
 * `npm run branding:apply` after editing branding/branding.json or branding/assets.
 */
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const brandingDir = resolve(root, 'branding');
const branding = JSON.parse(readFileSync(resolve(brandingDir, 'branding.json'), 'utf8'));

// image key in branding.json -> files it replaces (relative to repo root)
const IMAGE_TARGETS = {
	favicon: [
		'static/favicon.png',
		'static/static/favicon.png',
		'static/static/favicon-96x96.png',
		'static/static/apple-touch-icon.png',
		'static/static/web-app-manifest-192x192.png',
		'static/static/web-app-manifest-512x512.png'
	],
	favicon_svg: ['static/static/favicon.svg'],
	favicon_ico: ['static/static/favicon.ico'],
	logo: ['static/static/logo.png'],
	splash: ['static/static/splash.png'],
	splash_dark: ['static/static/splash-dark.png']
};

const escapeXml = (s) =>
	String(s).replace(
		/[<>&"']/g,
		(c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[c]
	);

for (const [key, targets] of Object.entries(IMAGE_TARGETS)) {
	const source = branding.images?.[key];
	if (!source) continue;
	const sourcePath = resolve(brandingDir, source);
	if (!existsSync(sourcePath)) {
		console.warn(`[branding] images.${key}: ${source} not found, skipping`);
		continue;
	}
	for (const target of targets) {
		copyFileSync(sourcePath, resolve(root, target));
	}
}

writeFileSync(
	resolve(root, 'static/static/site.webmanifest'),
	JSON.stringify(
		{
			name: branding.name,
			short_name: branding.short_name ?? branding.name,
			icons: [
				{
					src: '/static/web-app-manifest-192x192.png',
					sizes: '192x192',
					type: 'image/png',
					purpose: 'maskable'
				},
				{
					src: '/static/web-app-manifest-512x512.png',
					sizes: '512x512',
					type: 'image/png',
					purpose: 'maskable'
				}
			],
			theme_color: branding.theme_color ?? '#ffffff',
			background_color: branding.background_color ?? '#ffffff',
			display: 'standalone'
		},
		null,
		2
	) + '\n'
);

writeFileSync(
	resolve(root, 'static/opensearch.xml'),
	`<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" xmlns:moz="http://www.mozilla.org/2006/browser/search/">
<ShortName>${escapeXml(branding.name)}</ShortName>
<Description>Search ${escapeXml(branding.name)}</Description>
<InputEncoding>UTF-8</InputEncoding>
<Image width="16" height="16" type="image/x-icon">http://localhost:5137/favicon.png</Image>
<Url type="text/html" method="get" template="http://localhost:5137/?q={searchTerms}"/>
<moz:SearchForm>http://localhost:5137</moz:SearchForm>
</OpenSearchDescription>
`
);

const appHtmlPath = resolve(root, 'src/app.html');
const appHtml = readFileSync(appHtmlPath, 'utf8');
const updatedAppHtml = appHtml.replace(
	/<title>[\s\S]*?<\/title>/,
	`<title>${escapeXml(branding.name)}</title>`
);
if (updatedAppHtml !== appHtml) writeFileSync(appHtmlPath, updatedAppHtml);

console.log(`[branding] applied "${branding.name}"`);
