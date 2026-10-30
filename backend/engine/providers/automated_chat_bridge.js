/**
 * automated_chat_bridge.js
 * ----------------------------------------------------------------------------
 * Headless browser bridge that lets Xyberah / Promptfoo evaluate a model that is
 * ONLY reachable through a web chat UI (no HTTP API).
 *
 * Two ways to use it:
 *
 *   1) As a Promptfoo custom provider (the main integration):
 *        providers:
 *          - id: file://automated_chat_bridge.js
 *            config: { url: "...", inputSelector: "...", ... }
 *      Promptfoo calls `callApi(prompt)` once per test; we drive the browser and
 *      return `{ output }` (or `{ error }`) into the grading engine.
 *
 *   2) As a CLI script (handy for debugging a selector set):
 *        node automated_chat_bridge.js "What is the capital of France?"
 *        PROMPTFOO_PROMPT="hi" node automated_chat_bridge.js
 *      Prints the scraped reply to stdout, or "[BRIDGE ERROR] ..." on failure.
 *
 * It launches Chromium ONCE and reuses it, but uses a FRESH browser context for
 * every prompt so each test is an isolated, stateless conversation (important
 * for red-teaming). Everything is wrapped so a selector/timeouts failure returns
 * a clean error string instead of crashing the pipeline.
 * ----------------------------------------------------------------------------
 */

'use strict';

const { chromium } = require('playwright');
const fs = require('fs');

// ===========================================================================
// 1. DOM SELECTORS — update these placeholders to match YOUR chat UI.
//    Find them with devtools (right-click the element → Inspect). Prefer stable
//    attributes (data-testid, aria-label, role) over hashed CSS class names.
//    Every value here can also be overridden per-provider in promptfooconfig.yaml
//    under `config:`, or via the matching ENV var (shown in brackets).
// ===========================================================================
const DEFAULTS = {
  // [CHAT_URL] The chat page URL.
  url: process.env.CHAT_URL || 'http://localhost:3000/chat',

  // [CHAT_INPUT_SELECTOR] The message input box (a <textarea>, <input>, or a
  // contenteditable <div>). Example for ChatGPT-like UIs: "#prompt-textarea".
  inputSelector: process.env.CHAT_INPUT_SELECTOR || "textarea[data-testid='chat-input']",

  // [CHAT_SEND_SELECTOR] The "send" button. Leave empty ("") to submit with Enter.
  sendButtonSelector: process.env.CHAT_SEND_SELECTOR || "button[data-testid='send-button']",

  // [CHAT_RESPONSE_SELECTOR] The ASSISTANT message bubbles ONLY (not the user's).
  // The LAST match is treated as the current reply. Make this assistant-specific,
  // e.g. "[data-message-author-role='assistant']" or ".message.assistant .content".
  responseBubbleSelector: process.env.CHAT_RESPONSE_SELECTOR || "[data-message-author-role='assistant']",

  // [CHAT_STREAMING_SELECTOR] Optional. An element present ONLY while the model is
  // still generating (e.g. a "Stop generating" button or a typing indicator).
  // If set, we also wait for it to disappear. Leave "" to rely on text stability.
  streamingIndicatorSelector: process.env.CHAT_STREAMING_SELECTOR || "button[aria-label='Stop generating']",

  // [CHAT_NEWCHAT_SELECTOR] Optional. If your UI keeps history, a "New chat" button
  // clicked before each prompt. Usually unnecessary (we use a fresh context).
  newChatSelector: process.env.CHAT_NEWCHAT_SELECTOR || '',

  // [CHAT_STORAGE_STATE] Optional path to a Playwright storageState JSON for auth.
  // Create once with:  npx playwright codegen --save-storage=auth.json <url>
  storageStatePath: process.env.CHAT_STORAGE_STATE || '',

  // Behaviour knobs
  headless: (process.env.CHAT_HEADLESS || 'true') !== 'false',
  submitMethod: process.env.CHAT_SUBMIT_METHOD || 'auto', // 'auto' | 'click' | 'enter'
  typeDelayMs: parseInt(process.env.CHAT_TYPE_DELAY_MS || '0', 10), // natural typing; 0 = instant fill
  navigationTimeoutMs: parseInt(process.env.CHAT_NAV_TIMEOUT_MS || '30000', 10),
  hardTimeoutMs: parseInt(process.env.CHAT_HARD_TIMEOUT_MS || '30000', 10), // max wait for a reply
  stableMs: parseInt(process.env.CHAT_STABLE_MS || '1200', 10), // reply "done" after text is unchanged this long
  pollMs: 300,
};

const log = (...a) => console.error(`[bridge ${new Date().toISOString()}]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Shared browser (launched once, reused across prompts).
// ---------------------------------------------------------------------------
let _browserPromise = null;
function getBrowser(headless) {
  if (!_browserPromise) {
    log('launching chromium (headless=' + headless + ')');
    _browserPromise = chromium.launch({
      headless,
      args: ['--no-sandbox', '--disable-dev-shm-usage'], // CI/container friendly
    });
  }
  return _browserPromise;
}

async function closeBrowser() {
  if (_browserPromise) {
    try { (await _browserPromise).close(); } catch (_) { /* ignore */ }
    _browserPromise = null;
  }
}
['SIGINT', 'SIGTERM', 'exit'].forEach((sig) => process.on(sig, () => { closeBrowser(); }));

// ---------------------------------------------------------------------------
// Core: send ONE prompt to the chat UI and return the final reply text.
// Never throws — returns { output } on success or { error } on failure.
// ---------------------------------------------------------------------------
async function runPrompt(prompt, cfg) {
  const c = { ...DEFAULTS, ...(cfg || {}) };
  let context;
  try {
    const browser = await getBrowser(c.headless);
    const ctxOpts = {};
    if (c.storageStatePath && fs.existsSync(c.storageStatePath)) {
      ctxOpts.storageState = c.storageStatePath; // reuse an authenticated session
    }
    context = await browser.newContext(ctxOpts);
    const page = await context.newPage();
    page.setDefaultTimeout(c.navigationTimeoutMs);

    // --- navigate ---------------------------------------------------------
    await page.goto(c.url, { waitUntil: 'domcontentloaded', timeout: c.navigationTimeoutMs });

    // optional: start a fresh conversation
    if (c.newChatSelector) {
      const nc = page.locator(c.newChatSelector);
      if (await nc.count()) { await nc.first().click().catch(() => {}); }
    }

    // --- wait for the input to be interactive -----------------------------
    const input = page.locator(c.inputSelector).first();
    try {
      await input.waitFor({ state: 'visible', timeout: c.navigationTimeoutMs });
    } catch (e) {
      return fail(`input not found/visible: selector "${c.inputSelector}" (${e.message})`);
    }

    // baseline count of assistant bubbles BEFORE we send
    const bubbles = page.locator(c.responseBubbleSelector);
    const baseline = await bubbles.count();

    // --- type the prompt --------------------------------------------------
    await input.click({ timeout: 5000 }).catch(() => {});
    if (c.typeDelayMs > 0) {
      await input.pressSequentially(prompt, { delay: c.typeDelayMs }); // natural typing
    } else {
      await input.fill(prompt); // works for input/textarea AND contenteditable
    }

    // --- trigger send -----------------------------------------------------
    const method = resolveSubmit(c);
    if (method === 'click') {
      const btn = page.locator(c.sendButtonSelector).first();
      try {
        await btn.waitFor({ state: 'visible', timeout: 5000 });
        await btn.click();
      } catch (e) {
        log(`send button "${c.sendButtonSelector}" not clickable, falling back to Enter (${e.message})`);
        await input.press('Enter');
      }
    } else {
      await input.press('Enter');
    }

    // --- wait for a NEW assistant bubble to appear ------------------------
    const deadline = Date.now() + c.hardTimeoutMs;
    let appeared = false;
    while (Date.now() < deadline) {
      if ((await bubbles.count()) > baseline) { appeared = true; break; }
      await sleep(c.pollMs);
    }
    if (!appeared) {
      return fail(`no new assistant bubble matched "${c.responseBubbleSelector}" within ${c.hardTimeoutMs}ms ` +
                  `(check the response selector, or that the message was actually sent)`);
    }

    // --- observer loop: wait until the reply stops streaming --------------
    let lastText = '';
    let lastChange = Date.now();
    while (Date.now() < deadline) {
      const last = bubbles.last();
      let text = '';
      try { text = (await last.innerText()).trim(); } catch (_) { /* element re-rendering */ }

      if (text && text !== lastText) { lastText = text; lastChange = Date.now(); }

      let stillStreaming = false;
      if (c.streamingIndicatorSelector) {
        stillStreaming = (await page.locator(c.streamingIndicatorSelector).count()) > 0;
      }

      const stableLongEnough = text && (Date.now() - lastChange) >= c.stableMs;
      if (stableLongEnough && !stillStreaming) {
        log(`reply settled after ${Date.now() - (deadline - c.hardTimeoutMs)}ms, ${text.length} chars`);
        return { output: text };
      }
      await sleep(c.pollMs);
    }

    // hard timeout — return whatever we captured, flagged
    if (lastText) {
      log('hard timeout reached; returning last captured (possibly partial) text');
      return { output: lastText, metadata: { truncated: true, reason: 'hard_timeout' } };
    }
    return fail(`reply never produced text within ${c.hardTimeoutMs}ms`);
  } catch (e) {
    return fail(`unexpected error: ${e && e.message ? e.message : String(e)}`);
  } finally {
    if (context) { await context.close().catch(() => {}); }
  }
}

function resolveSubmit(c) {
  if (c.submitMethod === 'click') return 'click';
  if (c.submitMethod === 'enter') return 'enter';
  return c.sendButtonSelector ? 'click' : 'enter'; // auto
}

function fail(message) {
  log('FAIL:', message);
  return { error: `[BRIDGE ERROR] ${message}` };
}

// ===========================================================================
// 2. Promptfoo custom-provider interface.
//    Promptfoo constructs this with { id, config } and calls callApi per test.
// ===========================================================================
class ChatUiProvider {
  constructor(options = {}) {
    this.providerId = options.id || 'web-chat-ui';
    this.config = options.config || {};
  }
  id() { return this.providerId; }
  async callApi(prompt /*, context, options */) {
    const result = await runPrompt(prompt, this.config);
    // Promptfoo reads `output` for assertions, or surfaces `error`.
    return result;
  }
}

module.exports = ChatUiProvider;
// Also expose the raw function for custom harnesses/tests.
module.exports.runPrompt = runPrompt;
module.exports.closeBrowser = closeBrowser;

// ===========================================================================
// 3. CLI mode:  node automated_chat_bridge.js "my prompt"
//    or:        PROMPTFOO_PROMPT="my prompt" node automated_chat_bridge.js
// ===========================================================================
if (require.main === module) {
  (async () => {
    const prompt = process.argv.slice(2).join(' ') || process.env.PROMPTFOO_PROMPT || '';
    if (!prompt) {
      console.log('[BRIDGE ERROR] no prompt given (argv or PROMPTFOO_PROMPT)');
      process.exit(1);
    }
    const res = await runPrompt(prompt, {});
    await closeBrowser();
    if (res.error) {
      console.log(res.error); // failure log to stdout, as requested
      process.exit(1);
    }
    process.stdout.write(res.output + '\n'); // clean payload to stdout
    process.exit(0);
  })();
}
