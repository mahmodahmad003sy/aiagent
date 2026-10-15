# Branding

Everything that identifies the product — name, links, logos, icons — is configured here.
Edit these files instead of touching the app code.

## `branding.json`

| Key | Used for |
| --- | --- |
| `name` | App name everywhere: page titles, UI text, translations (`{{APP_NAME}}`), API title, server banner, emails/notifications, OAuth client name |
| `short_name` | PWA install name |
| `description` | PWA manifest description |
| `copyright_holder` | "Copyright (c) <year> …" line in Settings → About |
| `favicon_url` | Absolute public URL of the icon, used in webhook cards (e.g. Teams). Leave empty if not public |
| `theme_color`, `background_color` | PWA manifest colors |
| `links.website` | Copyright link + "Website" link in About / Admin settings |
| `links.documentation` | "Documentation" / "Read the docs" links (hidden when empty) |
| `links.github`, `links.discord`, `links.x` | Community links in About / Admin settings (hidden when empty) |
| `images.*` | Paths (relative to this folder) of the brand images, see below |

## Images (`assets/`)

| Key | Replaces | Recommended |
| --- | --- | --- |
| `favicon` | favicon, app icons, apple-touch icon, PWA icons, default model avatar | square PNG, 512×512, transparent background |
| `favicon_svg` | `favicon.svg` | square SVG |
| `favicon_ico` | `favicon.ico` | multi-size ICO |
| `logo` | `logo.png` (PWA install icon) | square PNG, 500×500 |
| `splash` | loading screen / sidebar logo (light mode) | square PNG, 500×500 |
| `splash_dark` | loading screen logo (dark mode) | square PNG, 500×500 |

To change an image, drop the new file into `assets/` (same name, or update the path in `branding.json`).

## Applying changes

`npm run dev` and `npm run build` apply branding automatically. To apply it manually:

```bash
npm run branding:apply
```

This copies the images into `static/` and regenerates `static/static/site.webmanifest`,
`static/opensearch.xml` and the `<title>` in `src/app.html`. The frontend and backend
read `branding.json` directly, so a restart/rebuild picks up name and link changes.

The backend looks for this file at `$BRANDING_CONFIG_PATH`, falling back to
`<repo>/branding/branding.json` (`/app/branding/branding.json` in Docker).
The `WEBUI_NAME` environment variable still overrides `name` on the backend.
