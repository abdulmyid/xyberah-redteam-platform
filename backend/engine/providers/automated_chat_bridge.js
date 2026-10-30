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
 *            config: { url: "...", inputSelector: "...", setupSteps: [...] }
 *
 *   2) As a CLI script (handy for debugging selectors / a login macro):
 *        node automated_chat_bridge.js "What is the capital of France?"
 *        PROMPTFOO_PROMPT="hi" node automated_chat_bridge.js
 *
 * AUTHENTICATED TARGETS (Burp-style login macro):
 *   Provide `setupSteps`: an ordered list of browser actions that LOG IN and reach
 *   the chat. They run ONCE in a shared context; every prompt then replays against
 *   that logged-in session. Passwords are referenced as {{secret.NAME}} and read
 *   from environment variables at run time — never stored.
 *
 *     setupSteps:
 *       - { action: goto,            url: "https://app/login" }
 *       - { action: fill,            selector: "#email",    value: "{{secret.CHAT_USER}}" }
 *       - { action: fill,            selector: "#password", value: "{{secret.CHAT_PASS}}" }
 *       - { action: click,           selector: "button[type=submit]" }
 *       - { action: waitForSelector, selector: "textarea[name=prompt]" }
 *
 *   Supported actions: goto, fill, type, click, press, waitForSelector,
 *   waitForURL, waitForLoadState, sleep.
 *
 * Everything is wrapped so a selector/timeout failure returns a clean error string
 * instead of crashing the pipeline.
 * ----------------------------------------------------------------------------
 */

'use strict';

const { chromium } = require('playwright');
const fs = require('fs');

function parseJsonEnv(s) { if (!s) return null; try { return JSON.parse(s); } catch { return null; } }

// ===========================================================================
// DOM SELECTORS & behaviour — overridable per-provider in config: or via ENV.
// ===========================================================================
const DEFAULTS = {
  url: process.env.CHAT_URL || 'http://localhost:3000/chat',
  inputSelector: process.env.CHAT_INPUT_SELECTOR || "textarea[data-testid='chat-input']",
  sendButtonSelector: process.env.CHAT_SEND_SELECTOR || "button[data-testid='send-button']",
  responseBubbleSelector: process.env.CHAT_RESPONSE_SELECTOR || "[data-message-author-role='assistant']",
  streamingIndicatorSelector: process.env.CHAT_STREAMING_SELECTOR || "button[aria-label='Stop generating']",

  // Login macro (runs once) + optional "start a new conversation" steps (per prompt).
  setupSteps: parseJsonEnv(process.env.CHAT_SETUP_STEPS) || [],
  newChatSteps: parseJsonEnv(process.env.CHAT_NEWCHAT_STEPS) || [],
  newChatSelector: process.env.CHAT_NEWCHAT_SELECTOR || '',

  // Optional pre-captured authenticated session (Playwright storageState JSON).
  storageStatePath: process.env.CHAT_STORAGE_STATE || '',

  headless: (process.env.CHAT_HEADLESS || 'true') !== 'false',
  submitMethod: process.env.CHAT_SUBMIT_METHOD || 'auto', // auto | click | enter
  typeDelayMs: parseInt(process.env.CHAT_TYPE_DELAY_MS || '0', 10),
  navigationTimeoutMs: parseInt(process.env.CHAT_NAV_TIMEOUT_MS || '30000', 10),
  hardTimeoutMs: parseInt(process.env.CHAT_HARD_TIMEOUT_MS || '30000', 10),
  stableMs: parseInt(process.env.CHAT_STABLE_MS || '1200', 10),
  pollMs: 300,
};

const log = (...a) => console.error(`[bridge ${new Date().toISOString()}]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Replace {{secret.NAME}} / {{env.NAME}} with process.env.NAME (never logged).
function resolveSecrets(str) {
  if (typeof str !== 'string') return str;
  return str.replace(/\{\{\s*(?:secret|env)\.([A-Z0-9_]+)\s*\}\}/gi, (_, name) => {
    const v = process.env[name];
    if (v === undefined) { log(`WARNING: secret/env "${name}" is not set`); return ''; }
    return v;
  });
}

// ---------------------------------------------------------------------------
// Shared browser (launched once) and shared AUTHENTICATED context (login once).
// ---------------------------------------------------------------------------
let _browserPromise = null;
function getBrowser(headless) {
  if (!_browserPromise) {
    log('launching chromium (headless=' + headless + ')');
    _browserPromise = chromium.launch({ headless, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  }
  return _browserPromise;
}

let _authCtxPromise = null;
function getAuthContext(c) {
  if (!_authCtxPromise) {
    _authCtxPromise = (async () => {
      const browser = await getBrowser(c.headless);
      const ctx = await browser.newContext(storageOpts(c));
      if (c.setupSteps && c.setupSteps.length) {
        log(`running login macro (${c.setupSteps.length} steps)`);
        const page = await ctx.newPage();
        page.setDefaultTimeout(c.navigationTimeoutMs);
        await runSteps(page, c.setupSteps, c);
        await page.close();
        log('login macro complete');
      }
      return ctx;
    })();
  }
  return _authCtxPromise;
}

function storageOpts(c) {
  return (c.storageStatePath && fs.existsSync(c.storageStatePath)) ? { storageState: c.storageStatePath } : {};
}

async function closeBrowser() {
  if (_authCtxPromise) { try { (await _authCtxPromise).close(); } catch (_) {} _authCtxPromise = null; }
  if (_browserPromise) { try { (await _browserPromise).close(); } catch (_) {} _browserPromise = null; }
}
['SIGINT', 'SIGTERM', 'exit'].forEach((sig) => process.on(sig, () => { closeBrowser(); }));

// ---------------------------------------------------------------------------
// Run an ordered list of actions (login macro / new-chat steps).
// ---------------------------------------------------------------------------
async function runSteps(page, steps, c) {
  for (const raw of steps) {
    const step = raw || {};
    const action = String(step.action || '').toLowerCase();
    const sel = step.selector;
    const val = step.value != null ? resolveSecrets(String(step.value)) : undefined;
    const url = step.url ? resolveSecrets(step.url) : undefined;
    const to = step.timeout || c.navigationTimeoutMs;
    try {
      switch (action) {
        case 'goto': await page.goto(url, { waitUntil: 'domcontentloaded', timeout: to }); break;
        case 'fill': await page.locator(sel).first().fill(val ?? ''); break;
        case 'type': await page.locator(sel).first().pressSequentially(val ?? '', { delay: c.typeDelayMs || 20 }); break;
        case 'click': await page.locator(sel).first().click({ timeout: to }); break;
        case 'press': await page.locator(sel).first().press(val || 'Enter'); break;
        case 'waitforselector': case 'wait':
          await page.locator(sel).first().waitFor({ state: 'visible', timeout: to }); break;
        case 'waitforurl': await page.waitForURL(url || val, { timeout: to }); break;
        case 'waitforloadstate': await page.waitForLoadState(val || 'networkidle', { timeout: to }); break;
        case 'sleep': case 'waitfortimeout': await sleep(step.ms || 1000); break;
        default: log(`unknown step action: "${step.action}" (skipped)`);
      }
    } catch (e) {
      throw new Error(`login/setup step failed [${action}${sel ? ' ' + sel : ''}]: ${e.message}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Core: send ONE prompt to the chat UI and return the final reply text.
// Never throws — returns { output } on success or { error } on failure.
// ---------------------------------------------------------------------------
async function runPrompt(prompt, cfg) {
  const c = { ...DEFAULTS, ...(cfg || {}) };
  const authed = (c.setupSteps && c.setupSteps.length) || storageOpts(c).storageState;
  let context, page, ownContext = false;
  try {
    if (authed) {
      context = await getAuthContext(c);
    } else {
      const browser = await getBrowser(c.headless);
      context = await browser.newContext(storageOpts(c));
      ownContext = true;
    }
    page = await context.newPage();
    page.setDefaultTimeout(c.navigationTimeoutMs);

    // Navigate to the chat (authenticated cookies carry over from the macro).
    await page.goto(c.url, { waitUntil: 'domcontentloaded', timeout: c.navigationTimeoutMs });

    // Start a fresh conversation if configured.
    if (c.newChatSteps && c.newChatSteps.length) {
      await runSteps(page, c.newChatSteps, c);
    } else if (c.newChatSelector) {
      const nc = page.locator(c.newChatSelector);
      if (await nc.count()) await nc.first().click().catch(() => {});
    }

    const input = page.locator(c.inputSelector).first();
    try {
      await input.waitFor({ state: 'visible', timeout: c.navigationTimeoutMs });
    } catch (e) {
      return fail(`input not found/visible: selector "${c.inputSelector}" (${e.message})`);
    }

    const bubbles = page.locator(c.responseBubbleSelector);
    const baseline = await bubbles.count();

    await input.click({ timeout: 5000 }).catch(() => {});
    if (c.typeDelayMs > 0) await input.pressSequentially(prompt, { delay: c.typeDelayMs });
    else await input.fill(prompt);

    const method = c.submitMethod === 'click' ? 'click'
      : c.submitMethod === 'enter' ? 'enter'
        : (c.sendButtonSelector ? 'click' : 'enter');
    if (method === 'click') {
      const btn = page.locator(c.sendButtonSelector).first();
      try { await btn.waitFor({ state: 'visible', timeout: 5000 }); await btn.click(); }
      catch (e) { log(`send button not clickable, using Enter (${e.message})`); await input.press('Enter'); }
    } else {
      await input.press('Enter');
    }

    const deadline = Date.now() + c.hardTimeoutMs;
    let appeared = false;
    while (Date.now() < deadline) {
      if ((await bubbles.count()) > baseline) { appeared = true; break; }
      await sleep(c.pollMs);
    }
    if (!appeared) {
      return fail(`no new assistant bubble matched "${c.responseBubbleSelector}" within ${c.hardTimeoutMs}ms`);
    }

    let lastText = '';
    let lastChange = Date.now();
    while (Date.now() < deadline) {
      let text = '';
      try { text = (await bubbles.last().innerText()).trim(); } catch (_) {}
      if (text && text !== lastText) { lastText = text; lastChange = Date.now(); }
      let streaming = false;
      if (c.streamingIndicatorSelector) {
        streaming = (await page.locator(c.streamingIndicatorSelector).count()) > 0;
      }
      if (text && (Date.now() - lastChange) >= c.stableMs && !streaming) {
        return { output: text };
      }
      await sleep(c.pollMs);
    }
    if (lastText) return { output: lastText, metadata: { truncated: true, reason: 'hard_timeout' } };
    return fail(`reply never produced text within ${c.hardTimeoutMs}ms`);
  } catch (e) {
    return fail(`unexpected error: ${e && e.message ? e.message : String(e)}`);
  } finally {
    if (page) { await page.close().catch(() => {}); }
    if (ownContext && context) { await context.close().catch(() => {}); }
  }
}

function fail(message) { log('FAIL:', message); return { error: `[BRIDGE ERROR] ${message}` }; }

// ===========================================================================
// Promptfoo custom-provider interface.
// ===========================================================================
class ChatUiProvider {
  constructor(options = {}) {
    this.providerId = options.id || 'web-chat-ui';
    this.config = options.config || {};
  }
  id() { return this.providerId; }
  async callApi(prompt) { return runPrompt(prompt, this.config); }
}

module.exports = ChatUiProvider;
module.exports.runPrompt = runPrompt;
module.exports.closeBrowser = closeBrowser;

// ===========================================================================
// CLI mode
// ===========================================================================
if (require.main === module) {
  (async () => {
    const prompt = process.argv.slice(2).join(' ') || process.env.PROMPTFOO_PROMPT || '';
    if (!prompt) { console.log('[BRIDGE ERROR] no prompt given (argv or PROMPTFOO_PROMPT)'); process.exit(1); }
    const res = await runPrompt(prompt, {});
    await closeBrowser();
    if (res.error) { console.log(res.error); process.exit(1); }
    process.stdout.write(res.output + '\n');
    process.exit(0);
  })();
}
