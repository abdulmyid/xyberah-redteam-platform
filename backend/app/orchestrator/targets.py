"""Target model definitions and their translation to Promptfoo providers.

API keys are never stored with campaigns: Promptfoo, garak and PyRIT read them
from the container environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...), and
custom endpoints reference secrets as {{env.NAME}} in their headers.
"""
import os
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "google": "GOOGLE_API_KEY", "azure": "AZURE_API_KEY",
           "huggingface": "HF_API_TOKEN"}


class HttpTarget(BaseModel):
    url: str
    method: Literal["POST", "GET"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    # JSON body; the string {{prompt}} is replaced with the attack prompt
    body: dict[str, Any] = Field(default_factory=lambda: {"message": "{{prompt}}"})
    # Dot path to the reply in the JSON response, e.g. "choices.0.message.content"
    response_path: str = "reply"


class BrowserStep(BaseModel):
    """One action in a login/setup macro (Burp-style recorded login)."""

    action: str  # goto | fill | type | click | press | waitForSelector | waitForURL | waitForLoadState | sleep
    selector: str = ""
    value: str = ""   # may reference {{secret.NAME}} — resolved from backend env, never stored
    url: str = ""
    ms: int = 0


class McpServer(BaseModel):
    """A remote MCP server the agent-under-test can call (HTTP/SSE transport)."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class McpTarget(BaseModel):
    """An LLM agent wired to one or more MCP servers. Red-team plugins then test
    whether the agent misuses its tools (excessive agency, injection via tool
    results, unauthorized actions, etc.)."""

    base_provider: str = "openai"  # openai | anthropic | google | azure | ollama | bedrock
    servers: list[McpServer] = Field(default_factory=list)


class BrowserTarget(BaseModel):
    """A model reachable only through a web chat UI, driven by the Playwright
    bridge (engine/providers/automated_chat_bridge.js)."""

    url: str
    input_selector: str = "textarea[data-testid='chat-input']"
    send_button_selector: str = "button[data-testid='send-button']"
    response_bubble_selector: str = "[data-message-author-role='assistant']"
    streaming_indicator_selector: str = "button[aria-label='Stop generating']"
    new_chat_selector: str = ""
    setup_steps: list[BrowserStep] = []  # login macro, runs once
    session_id: Optional[int] = None     # saved authenticated session (storageState)
    hard_timeout_ms: int = 30000
    stable_ms: int = 1200


class Target(BaseModel):
    type: Literal["openai", "anthropic", "ollama", "http", "demo", "browser",
                  "google", "azure", "bedrock", "huggingface", "mcp"]
    label: str = ""
    model: str = ""
    base_url: Optional[str] = None  # OpenAI-compatible gateways, Ollama host
    system_prompt: str = ""
    http: Optional[HttpTarget] = None
    browser: Optional[BrowserTarget] = None
    mcp: Optional[McpTarget] = None

    @model_validator(mode="after")
    def _check(self) -> "Target":
        if self.type == "demo" and not self.http:
            # Built-in vulnerable demo chatbot (no API key needed)
            from ..config import get_settings
            self.http = HttpTarget(url=get_settings().demo_url,
                                   body={"message": "{{prompt}}"}, response_path="reply")
        if self.type == "http" and not self.http:
            raise ValueError("http target needs http settings")
        if self.type == "browser" and not self.browser:
            raise ValueError("browser target needs browser settings")
        if self.type == "mcp":
            if not self.mcp or not self.mcp.servers:
                raise ValueError("mcp target needs at least one MCP server")
            if not self.model:
                raise ValueError("mcp target needs a base model")
        elif self.type not in ("http", "demo", "browser") and not self.model:
            raise ValueError("model is required")
        return self

    @property
    def is_http_like(self) -> bool:
        return self.type in ("http", "demo")

    @property
    def display(self) -> str:
        if self.label:
            return self.label
        if self.type == "demo":
            return "Built-in demo target"
        if self.type == "browser" and self.browser:
            return f"browser: {self.browser.url}"
        if self.type == "mcp" and self.mcp:
            return f"mcp agent ({self.mcp.base_provider}:{self.model}, {len(self.mcp.servers)} server(s))"
        return self.http.url if self.is_http_like and self.http else f"{self.type}:{self.model}"


def missing_keys(target: Target) -> list[str]:
    if target.type in ("demo", "browser"):
        return []
    kind = target.mcp.base_provider if target.type == "mcp" and target.mcp else target.type
    env = KEY_ENV.get(kind)
    return [env] if env and not os.getenv(env) else []


def _js_path(path: str) -> str:
    parts = [p for p in path.split(".") if p]
    return "json" + "".join(f"[{p}]" if p.isdigit() else f"[{p!r}]" for p in parts)


def _model_pid(kind: str, model: str, base_url: Optional[str]) -> tuple[str, dict[str, Any]]:
    """(provider id, config) for a standard model provider kind."""
    config: dict[str, Any] = {}
    if kind == "openai":
        pid = f"openai:chat:{model}"
        if base_url:
            config["apiBaseUrl"] = base_url
    elif kind == "anthropic":
        pid = f"anthropic:messages:{model}"
    elif kind == "ollama":
        pid = f"ollama:chat:{model}"
    elif kind == "google":
        pid = f"google:{model}"
    elif kind == "azure":
        pid = f"azure:chat:{model}"
        if base_url:
            config["apiHost"] = base_url
    elif kind == "bedrock":
        pid = f"bedrock:{model}"
    elif kind == "huggingface":
        pid = f"huggingface:text-generation:{model}"
    else:
        pid = f"{kind}:{model}"
    return pid, config


def promptfoo_provider(target: Target) -> dict[str, Any]:
    """Provider entry for promptfooconfig.yaml `targets:`."""
    config: dict[str, Any] = {}
    if target.type == "mcp":
        m = target.mcp
        assert m
        pid, config = _model_pid(m.base_provider, target.model, target.base_url)
        config["mcp"] = {"enabled": True,
                         "servers": [{"url": sv.url, **({"headers": sv.headers} if sv.headers else {})}
                                     for sv in m.servers]}
        return {"id": pid, "label": target.display, "config": config}
    if target.type == "browser":
        from ..config import get_settings
        b = target.browser
        assert b
        bridge = get_settings().engine_dir / "providers" / "automated_chat_bridge.js"
        return {
            "id": f"file://{bridge}",
            "label": target.display,
            "config": {
                "url": b.url, "headless": True,
                "inputSelector": b.input_selector,
                "sendButtonSelector": b.send_button_selector,
                "responseBubbleSelector": b.response_bubble_selector,
                "streamingIndicatorSelector": b.streaming_indicator_selector,
                "newChatSelector": b.new_chat_selector,
                "setupSteps": [s.model_dump() for s in b.setup_steps],
                "hardTimeoutMs": b.hard_timeout_ms, "stableMs": b.stable_ms,
            },
        }
    if target.type == "openai":
        pid = f"openai:chat:{target.model}"
        if target.base_url:
            config["apiBaseUrl"] = target.base_url
    elif target.type == "anthropic":
        pid = f"anthropic:messages:{target.model}"
    elif target.type == "ollama":
        pid = f"ollama:chat:{target.model}"
    elif target.type == "google":
        pid = f"google:{target.model}"
    elif target.type == "azure":
        pid = f"azure:chat:{target.model}"  # model = Azure deployment name
        if target.base_url:
            config["apiHost"] = target.base_url  # e.g. your-resource.openai.azure.com
    elif target.type == "bedrock":
        pid = f"bedrock:{target.model}"
    elif target.type == "huggingface":
        pid = f"huggingface:text-generation:{target.model}"
    else:  # http or demo
        h = target.http
        assert h
        pid = "http"
        config = {
            "url": h.url,
            "method": h.method,
            "headers": {"Content-Type": "application/json", **h.headers},
            "body": h.body,
            "transformResponse": _js_path(h.response_path),
        }
    entry: dict[str, Any] = {"id": pid, "label": target.display}
    if config:
        entry["config"] = config
    return entry


def target_env(target: Target) -> dict[str, str]:
    """Extra environment for tool subprocesses."""
    env: dict[str, str] = {}
    if target.type == "ollama" and target.base_url:
        env["OLLAMA_BASE_URL"] = target.base_url
    return env
