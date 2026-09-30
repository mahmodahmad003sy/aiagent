# Chat Widget Feature Implementation Plan

## Stage 1 — Data Model
- Create `chat_widget` database model.
- Fields:
  - `id`
  - `user_id`
  - `name`
  - `model_id`
  - `system_prompt`
  - `welcome_message`
  - `token`
  - `enabled`
  - `allowed_domains`
  - `created_at`
  - `updated_at`
- Create widget conversation/session tables.

## Stage 2 — Widget Management Backend
- Add authenticated widget CRUD API.
- Required endpoints:
  - `POST /api/v1/widgets`
  - `GET /api/v1/widgets`
  - `GET /api/v1/widgets/{id}`
  - `PUT /api/v1/widgets/{id}`
  - `DELETE /api/v1/widgets/{id}`
  - `POST /api/v1/widgets/{id}/rotate-token`
- Allow users to select only models they already have permission to use.
- Verify ownership on every widget-management request.

## Stage 3 — Public Widget API
- Add public endpoints:
  - `GET /api/v1/widgets/public/config`
  - `POST /api/v1/widgets/public/chat`
- Authenticate using `wgt_...` widget token.
- Check:
  - widget exists
  - widget enabled
  - token valid
  - request domain allowed
  - configured model still accessible
- Never expose Open WebUI/API provider keys.

## Stage 4 — Chat Processing
- Reuse Open WebUI model/chat completion logic.
- Apply widget:
  - model
  - system prompt
  - conversation history
- Create anonymous visitor session ID.
- Store widget conversations separately from normal user chats.
- Support streaming responses.

## Stage 5 — Security
- Generate secure random widget tokens.
- Add token rotation.
- Add per-widget rate limiting.
- Add request/message size limits.
- Validate allowed domains.
- Add CORS rules for widget endpoints.
- Prevent changing `model_id` through public requests.
- Prevent access to models outside widget owner's permissions.

## Stage 6 — Widget Management UI
- Add `Workspace/Admin -> Chat Widgets`.
- Pages:
  - widget list
  - create widget
  - edit widget
  - delete/disable widget
- Settings:
  - name
  - model
  - system prompt
  - welcome message
  - allowed domains
- Show generated embed code.
- Add copy button.
- Add rotate-token button.

## Stage 7 — Embed Script
- Create:
  - `/static/widget/chat-widget.js`
- Script reads:
  - `data-widget-id`
  - `data-token`
  - `data-api-base`
- Inject floating chat button.
- Open/close chat window.
- Load widget config.
- Send messages to public widget API.
- Stream assistant responses.
- Store visitor session ID in browser storage.

## Stage 8 — Widget UI
- Add:
  - launcher button
  - chat header
  - welcome message
  - message list
  - input
  - send button
  - loading/streaming state
  - error state
- Make responsive for desktop/mobile.

## Stage 9 — Conversations
- Add widget conversation list for widget owner.
- Show:
  - session ID
  - created date
  - last activity
  - message count
  - model
- Allow opening conversation history.
- Allow deleting widget conversations.

## Stage 10 — Testing
- Test widget on external HTML page.
- Test allowed and blocked domains.
- Test invalid/expired token.
- Test disabled widget.
- Test model permission removal.
- Test multiple visitors.
- Test streaming.
- Test rate limits.
- Test token rotation.
- Test mobile layout.

## Stage 11 — V1 Release
V1 includes:
- create/edit/delete widget
- model selection
- system prompt
- welcome message
- domain restrictions
- secure widget token
- embed script
- anonymous chat sessions
- streaming responses
- widget conversation storage
- basic rate limiting

Not in V1:
- MCP tools
- Knowledge/RAG
- file uploads
- web search
- visitor login/SSO
- advanced analytics
- full theme editor
