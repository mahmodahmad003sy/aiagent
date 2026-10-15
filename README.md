# SmartLilac AI Studio

A private, self-hosted AI workspace for chatting with local models (Ollama or any OpenAI-compatible server), with knowledge bases, tools, notes and channels.

## Branding

The name, links, logos and icons are all configured in [`branding/`](branding/README.md).
Edit `branding/branding.json` and the images in `branding/assets/`, then run `npm run branding:apply`
(also run automatically by `npm run dev` / `npm run build`).

## Running with Docker

```bash
docker compose up -d --build
```

The app is served on http://localhost:3000 (override with `OPEN_WEBUI_PORT`).

## Running for development

```bash
# frontend
npm install
npm run dev

# backend (separate terminal)
cd backend
pip install -r requirements.txt
./dev.sh            # or start_windows.bat on Windows
```

## License

This project is a derivative of Open WebUI and is distributed under the terms in [LICENSE](LICENSE).
