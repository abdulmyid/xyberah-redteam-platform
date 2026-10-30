# Browser bridge — evaluate a chat-UI-only model with Xyberah / Promptfoo

When a model is reachable **only through a web chat window** (no API), this module
makes that UI behave like any other Xyberah target: a headless browser types each
prompt, waits for the reply to finish streaming, scrapes the final answer, and
hands it to the grading engine. Verified end-to-end against a streaming chat page.

```
browser-bridge/
├── automated_chat_bridge.js   # Playwright provider + CLI (the bridge)
├── promptfooconfig.yaml       # providers → tests (assertions)
├── run_tests.sh               # one command: install, run, JSON + HTML report
└── package.json
```

## Quick start

```bash
cd browser-bridge
# 1. edit promptfooconfig.yaml: set `url` and the 4 DOM selectors for your UI
# 2. run everything (installs Playwright + Chromium on first run):
./run_tests.sh
# → results/results.json and results/results.html
```

Debug a single prompt (prints the scraped reply, or `[BRIDGE ERROR] …`):

```bash
CHAT_URL="https://your-app/chat" node automated_chat_bridge.js "Hello, are you working?"
```

## The 4 selectors you must set

Open your chat UI, right-click each element → **Inspect**, and copy a stable
selector (prefer `data-testid` / `aria-label` / `role` over hashed classes). Set
them in `promptfooconfig.yaml` under `config:` (or via the `CHAT_*` env vars).

| Config key | What it is |
|---|---|
| `inputSelector` | the message box (`<textarea>`, `<input>`, or contenteditable) |
| `sendButtonSelector` | the send button — leave `""` to submit with **Enter** |
| `responseBubbleSelector` | the **assistant** message bubbles only (last = current reply) |
| `streamingIndicatorSelector` | optional: an element shown only while generating (e.g. a *Stop generating* button); `""` to rely on text-stability only |

## How "reply finished" is detected

Robust and app-agnostic: after send, the bridge waits for a **new** assistant
bubble, then polls its text. The reply is considered done when the text has been
**unchanged for `stableMs`** (default 1.2 s) **and** the streaming indicator (if
any) has disappeared — bounded by a hard **`hardTimeoutMs`** (default 30 s). On
timeout it returns the last partial text flagged `truncated`, never crashing.

## Authentication (CI)

If the UI needs login, capture an authenticated session once and reuse it:

```bash
npx playwright codegen --save-storage=auth.json https://your-app/login   # log in, close
# then set in config:  storageStatePath: "./auth.json"
```

## Edge cases handled

- 30 s navigation + 30 s per-reply hard timeouts
- Send-button fallback to **Enter** if the button isn't clickable
- Fresh browser context per prompt → isolated, stateless conversations (good for red-teaming)
- Selector failures return a clean `[BRIDGE ERROR] …` (logged to stderr, returned to the pipeline) instead of throwing
- `--no-sandbox` / `disable-dev-shm-usage` for CI containers

## Running on the Xyberah engine

`run_tests.sh` auto-detects Xyberah's bundled `promptfoo` (falls back to `npx
promptfoo`). To run it from inside the Xyberah backend container:

```bash
docker compose cp browser-bridge xyberah-backend-1:/opt/bridge   # or bind-mount
docker compose exec backend bash -c "cd /opt/bridge && ./run_tests.sh"
```

Set `redteam:` in `promptfooconfig.yaml` to have Xyberah **generate** attacks and
run them through the same browser bridge (`promptfoo redteam run`).
