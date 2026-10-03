# Website Crawl and Knowledge Extension Plan

## Goal

Allow each widget to crawl a website, review discovered resources, adjust crawl settings if needed, and only then extend the widget knowledge.

Crawling and knowledge embedding are separate stages.

---

## Stage 1 — Crawl Configuration

Add crawl settings for each widget:

- Website URL
- Crawl depth
- Maximum pages
- Same-domain only
- Follow sitemap
- Include paths
- Exclude paths
- Discover linked files
- Maximum file size
- Allowed/discovered file types
- Maximum total download size (whole crawl)
- Request timeout per page/file
- Request delay / max concurrency (rate limit)
- Respect robots.txt (on by default)

No embedding happens during this stage.

JavaScript-rendered pages (SPA) are **not supported in v1**. Only server-rendered HTML is crawled. The UI must show a notice:

> **Note:** Pages that load their content with JavaScript may appear empty or incomplete.

---

## Stage 2 — Run Crawl

The crawler discovers:

- HTML pages
- Supported files
- Other linked resources
- Broken or inaccessible URLs

Store the crawl results only.

Do not extend knowledge or create embeddings yet.

### Background Job

- A crawl runs as a background task, never inside the HTTP request.
- Each run has a status: `pending`, `running`, `completed`, `failed`, `cancelled`.
- Progress is stored and shown in the UI (pages crawled / queued, files found, errors).
- The admin can cancel a running crawl.
- Only one active crawl per widget at a time.

### Security (SSRF)

- Validate the start URL and **every** discovered URL with the existing `validate_url()` in `retrieval/web/utils.py` (blocks localhost, private/internal IPs, non-HTTP(S) schemes).
- Re-validate after every redirect.
- Use the existing SSRF-safe connector/adapter so DNS rebinding is also blocked.

### Politeness

- Fetch and respect `robots.txt` when enabled.
- Send a clear User-Agent (e.g. `OpenWebUI-WidgetCrawler/1.0`).
- Apply the configured request delay and concurrency limit.

### URL Normalization and De-duplication

Before queuing a URL:

- Lowercase scheme and host
- Remove `#fragment`
- Remove tracking parameters (`utm_*`, `gclid`, `fbclid`, ...)
- Normalize trailing `/`
- Respect `<link rel="canonical">` when present

A URL is crawled and stored only once per run.

### File Size Discovery

- Send a `HEAD` request for linked files to read `Content-Length` and `Content-Type`.
- Skip downloading files larger than the maximum file size; mark them `too_large`.
- If `HEAD` is not supported, stream the download and abort once the limit is exceeded.
- Stop downloading once the maximum total download size is reached; mark the rest `skipped_limit`.

---

## Stage 3 — Crawl Results

Show discovered resources in separate tables.

### Pages

Columns:

| Field | Description |
|---|---|
| Embed | Checkbox, enabled by default |
| Page Title | Discovered page title |
| URL | Page URL |
| Depth | Crawl depth where the page was found |
| Status | Crawl/result status |

All discovered pages are selected for embedding by default.

The user can uncheck any page that should not be added to knowledge.

---

### Files

Columns:

| Field | Description |
|---|---|
| Embed | Checkbox, enabled by default for supported files |
| Name | File name |
| Type | PDF, DOCX, XLSX, CSV, TXT, PPTX, etc. |
| Size | File size |
| URL | Direct file URL |
| Found On | Page where the file was discovered |
| Status | Supported / extraction result / error |

Supported file types for the first version:

- PDF
- DOCX
- XLSX
- CSV
- TXT
- PPTX

All supported files are selected for embedding by default.

The user can uncheck any file that should not be added to knowledge.

---

## Stage 4 — PDF Handling

Do not try to classify PDFs as scanned during crawling.

Show a clear notice in the UI:

> **PDF support:** Only extractable text inside PDF files can be added to knowledge. Text inside scanned pages or images is not processed.

Images inside PDFs are not processed.

If extraction later produces no usable text, show:

> **No extractable text found**

Do not label the PDF as scanned unless that is actually verified.

---

## Stage 5 — Other Resources

Show a separate **Other Resources** table for resources that should not have their actual contents embedded.

Examples:

- ZIP
- Images
- Videos
- EXE
- TAR / GZ
- Other unsupported file types

Columns:

| Field | Description |
|---|---|
| Name | Resource/file name |
| Type | ZIP, Image, Video, etc. |
| URL | Direct resource URL |
| Found On | Page where the resource was discovered |
| Size | Optional resource size |
| Link Text / Context | Text around the discovered link |

These resources do **not** need an Embed checkbox.

Their contents are not downloaded into the knowledge store for embedding.

Instead, store useful metadata so the assistant can direct users to the resource later.

Example metadata:

```json
{
  "resource_type": "file_reference",
  "name": "cities-in-country.zip",
  "file_type": "zip",
  "url": "https://example.com/files/cities-in-country.zip",
  "source_page": "https://example.com/resources",
  "source_page_title": "Country Resources",
  "link_text": "Download the list of cities",
  "context": "Download the complete list of cities and administrative areas."
}
```

Example assistant behavior:

> There is a resource called `cities-in-country.zip` available on the Country Resources page.
>
> File: `https://example.com/files/cities-in-country.zip`
>
> Page: `https://example.com/resources`

The assistant must not claim to know the contents of unsupported resources unless those contents were actually extracted.

---

## Stage 6 — Review and Re-crawl

After crawling, the admin reviews all discovered data.

The admin can:

- Uncheck pages
- Uncheck supported files
- Change crawl depth
- Change maximum pages
- Change include paths
- Change exclude paths
- Change file conditions
- Change other crawl settings
- Re-crawl the website

Changing only the Embed checkboxes does not require another crawl.

Changing crawl configuration requires re-crawling.

### Selections After Re-crawl

- Selections are keyed by normalized URL.
- A URL the admin unchecked stays unchecked after a re-crawl.
- Newly discovered URLs are checked by default (pages and supported files).

---

## Stage 7 — Crawl Summary

Show a clear summary above the result tables.

Example:

```text
Pages:              184
Supported files:     23
Other resources:     41
Errors:                4

Selected pages:     176 / 184
Selected files:      19 / 23
```

Actions:

```text
[ Re-crawl ]        [ Extend Knowledge ]
```

---

## Stage 8 — Extend Knowledge

Only after the admin verifies the discovered dataset should the system extend knowledge.

Process:

```text
Selected Pages
      +
Selected Supported Files
      +
Metadata of Other Resources
      ↓
Extract Content
      ↓
Normalize
      ↓
Chunk
      ↓
Create Embeddings / Index
      ↓
Attach to Widget Knowledge
```

### Content Knowledge

Actual extracted content from:

- HTML pages
- PDF text
- DOCX text
- XLSX content
- CSV content
- TXT files
- PPTX text

### Resource Knowledge

Metadata only for:

- ZIP files
- Images
- Videos
- Executables
- Unsupported files
- Other discovered resources

Store:

- Name
- URL
- Type
- Source page
- Source page title
- Link text
- Surrounding description/context
- Optional size

### Reuse Existing Open WebUI Components

- Page fetching: `SafeWebBaseLoader` / `get_web_loader()` in `retrieval/web/utils.py`.
- File extraction: `Loader` in `retrieval/loaders/main.py` (PDF, DOCX, XLSX, CSV, TXT, PPTX).
- Chunking, embedding and vector storage: the existing retrieval pipeline.
- Storage: a Knowledge collection created for the widget and attached to it. Each extracted item is a file in that collection.

### Extending Knowledge Again (Sync)

Extend Knowledge is a **sync**, not an append:

- Store a content hash (SHA-256 of the normalized text) per item.
- Unchanged items (same URL + same hash) are skipped.
- Changed items are re-extracted and re-embedded; old vectors are removed.
- Items that are now unchecked or no longer found are removed from the widget knowledge.
- Extend Knowledge also runs as a background job with status and progress.

---

## Data Model

### `chat_widget_crawl_config`

| Column | Notes |
|---|---|
| id | PK |
| widget_id | FK → chat_widget, unique |
| start_url | |
| max_depth, max_pages | |
| same_domain_only, follow_sitemap, respect_robots, discover_files | booleans |
| include_paths, exclude_paths | JSON lists |
| allowed_file_types | JSON list |
| max_file_size, max_total_size | bytes |
| request_timeout, request_delay, max_concurrency | |
| created_at, updated_at | |

### `chat_widget_crawl_run`

| Column | Notes |
|---|---|
| id | PK |
| widget_id | FK |
| config_snapshot | JSON copy of the config used |
| status | pending / running / completed / failed / cancelled |
| progress | JSON (counts) |
| error | text |
| started_at, finished_at | |

### `chat_widget_crawl_item`

| Column | Notes |
|---|---|
| id | PK |
| run_id | FK → crawl_run |
| widget_id | FK |
| kind | `page` / `file` / `resource` / `error` |
| url | normalized URL |
| title / name | |
| file_type, size | |
| depth | |
| found_on, found_on_title | source page |
| link_text, context | |
| status | ok / too_large / skipped_limit / http_error / blocked / no_text / ... |
| http_status | |
| selected | boolean |
| content_hash | set after extraction |
| knowledge_file_id | link to the file in the widget Knowledge collection |

Selections (`selected`) are copied from the previous run by URL when a new run is created.

---

## Final Workflow

```text
Configure Crawl
      ↓
Crawl Website
      ↓
Store Crawl Results
      ↓
Pages Table
Files Table
Other Resources Table
Errors
      ↓
Review / Select / Unselect
      ↓
Change Crawl Settings + Re-crawl if Needed
      ↓
Approve Dataset
      ↓
Extend Knowledge
      ↓
Extract + Chunk + Embed
      ↓
Attach Knowledge to Widget
```

---

## Important Rules

- Crawling does not automatically create embeddings.
- Pages are selected for embedding by default.
- Supported files are selected for embedding by default.
- Other resources are stored as searchable metadata only.
- File names and file sizes must be shown for discovered files.
- Page size is not required in the Pages table.
- PDF images are not processed.
- Scanned text inside PDFs is not supported unless OCR is added later.
- The UI must clearly explain the PDF limitation.
- The admin must be able to re-crawl with different settings before extending knowledge.
- The admin must be able to unselect pages or files without re-crawling.
- Crawls and knowledge extension run as cancellable background jobs.
- Every URL (including redirects) passes SSRF validation.
- robots.txt, rate limits, size limits and timeouts are enforced.
- URLs are normalized and de-duplicated.
- Unchecked selections survive re-crawls.
- Extend Knowledge syncs: skips unchanged, updates changed, removes stale items.
- JavaScript-rendered pages are not supported in v1.

## Out of Scope (Later)

- Scheduled / automatic re-crawls
- Sites that require login
- OCR for scanned PDFs and images
