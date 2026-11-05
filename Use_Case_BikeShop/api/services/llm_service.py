"""
The CONNECTION to the AI (SPEC §13.2). This is the only file that knows which AI you use.

You pick the AI in .env (ASSISTANT_PROVIDER=...); the default is BFH inference.
Everything else stays the same: the tools in assistant_tools.py don't
change, and neither does the loop in scripts/assistant_step3_chat.py.

There are only two "dialects" of tool calling out there:

  1. Anthropic style  (Claude)
  2. OpenAI style     (BFH inference, ChatGPT, Gemini, Mistral, Ollama ... they copied it)

So this file has two small translators that turn both dialects into the same
simple answer:  reply.text  and  reply.tool_calls  (each with .id, .name, .input).
"""
import json
import os
from dataclasses import dataclass, field

from ..config import ASSISTANT_MODEL, ASSISTANT_PROVIDER
from .inference_service import InferenceService

# name: (dialect, server address, name of the key in .env, default model)
# Model names change often. If one stops working, set ASSISTANT_MODEL=... in .env.
PROVIDERS = {
    "bfh":       ("openai", None, None, None),  # client AND model from InferenceService (MLMP_*, SPEC §8.1)
    "anthropic": ("anthropic", None, "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
    "openai":    ("openai", None, "OPENAI_API_KEY", "gpt-5-mini"),
    "gemini":    ("openai", "https://generativelanguage.googleapis.com/v1beta/openai/",
                  "GEMINI_API_KEY", "gemini-flash-latest"),
    "mistral":   ("openai", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest"),
    "ollama":    ("openai", "http://localhost:11434/v1", None, "llama3.2"),  # free, runs on your laptop
    "other":     ("openai", os.getenv("ASSISTANT_BASE_URL"), "ASSISTANT_API_KEY", None),  # any OpenAI-compatible server
}

BUSY_MESSAGE = "The assistant is busy, try again in a minute."


class NotConfigured(Exception):
    """The AI can't be set up: unknown provider, missing key or model, package not installed.
    str() says what to fix in .env. Not an AIError, so it never reaches a customer as an answer:
    the terminal scripts print it and stop, and in the worker the job fails."""


class AIError(Exception):
    """The AI service failed in a way the customer or the lecturer can act on. str() says how."""


class Busy(AIError):
    """The AI service said 429: too many requests (BFH allows 30 a minute)."""

    def __init__(self):
        super().__init__(BUSY_MESSAGE)


def _readable(sdk, error, model):
    """Turn the SDK's error into an AIError with a sentence, or None to let it crash."""
    if isinstance(error, sdk.RateLimitError):
        return Busy()
    if isinstance(error, sdk.APITimeoutError):     # a kind of connection error: test it first
        return AIError("The AI service took too long to answer. Please try again.")
    if isinstance(error, sdk.APIConnectionError):
        return AIError("Can't reach the AI service. Check the internet connection, or that the "
                       "service (e.g. Ollama) is running.")
    if isinstance(error, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
        return AIError("The AI service refused the key. Check the key in .env (MLMP keys expire after 180 days).")
    if isinstance(error, sdk.NotFoundError):
        return AIError(f"The AI service doesn't know the model '{model}'. Set MLMP_MODEL=... in .env (BFH) "
                       "or ASSISTANT_MODEL=... (other providers).")
    return None


@dataclass
class ToolCall:
    id: str      # which request this is (the result must be sent back with the same id)
    name: str    # which tool the AI wants
    input: dict  # with which inputs


@dataclass
class Reply:
    text: str
    tool_calls: list = field(default_factory=list)
    raw: object = None  # the reply exactly as the provider sent it (to look at in step 2)
    reasoning: str = ""  # a thinking model's reasoning, if the provider returns it
    tokens: int = 0      # tokens this call used, if the provider says


# =============================================================================
# Dialect 1: Anthropic (Claude)
# =============================================================================

class AnthropicChat:
    def __init__(self, model, key, system, tools):
        try:
            import anthropic
        except ImportError:
            raise NotConfigured("ASSISTANT_PROVIDER=anthropic needs the anthropic package: "
                                "uv pip install anthropic")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key)
        self.model, self.system, self.tools = model, system, tools  # the menu is already in this format

    def ask(self, messages):
        try:
            r = self.client.messages.create(model=self.model, max_tokens=1024, system=self.system,
                                            tools=self.tools, messages=messages)
        except self.anthropic.APIError as e:
            raise _readable(self.anthropic, e, self.model) or e
        return Reply(text="".join(b.text for b in r.content if b.type == "text"),
                     tool_calls=[ToolCall(b.id, b.name, b.input)
                                 for b in r.content if b.type == "tool_use"],
                     raw=r.content)

    def assistant_message(self, reply):
        return [{"role": "assistant", "content": reply.raw}]

    def tool_result_messages(self, tool_calls, results):
        # Anthropic: ALL results together in ONE "user" message
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(r, default=str)}
            for c, r in zip(tool_calls, results)]}]


# =============================================================================
# Dialect 2: OpenAI (BFH inference, ChatGPT, Gemini, Mistral, Ollama, ...)
# =============================================================================

class OpenAIChat:
    def __init__(self, client, model, system, tools):
        self.client, self.model, self.system = client, model, system
        self.max_tokens = None   # a feature can cap the reply, e.g. the Workshop (SPEC §14.10)
        # Same menu, different wrapping: "input_schema" is called "parameters" here
        self.tools = openai_tools(tools)

    def ask(self, messages):
        import openai
        try:
            limit = {"max_tokens": self.max_tokens} if self.max_tokens else {}
            r = self.client.chat.completions.create(
                model=self.model, tools=self.tools,
                messages=[{"role": "system", "content": self.system}, *messages], **limit)
        except openai.APIError as e:
            raise _readable(openai, e, self.model) or e
        msg = r.choices[0].message
        extra = getattr(msg, "model_extra", None) or {}   # thinking models add their own fields
        usage = getattr(r, "usage", None)
        return Reply(text=msg.content or "",
                     tool_calls=[ToolCall(c.id, c.function.name, json.loads(c.function.arguments or "{}"))
                                 for c in msg.tool_calls or []],
                     raw=msg,
                     reasoning=extra.get("reasoning_content") or extra.get("reasoning") or "",
                     tokens=getattr(usage, "total_tokens", 0) or 0)

    def assistant_message(self, reply):
        message = {"role": "assistant", "content": reply.text}
        if reply.tool_calls:
            message["tool_calls"] = [{"id": c.id, "type": "function",
                                      "function": {"name": c.name, "arguments": json.dumps(c.input)}}
                                     for c in reply.tool_calls]
        return [message]

    def tool_result_messages(self, tool_calls, results):
        # OpenAI: ONE "tool" message PER result
        return [{"role": "tool", "tool_call_id": c.id, "content": json.dumps(r, default=str)}
                for c, r in zip(tool_calls, results)]


def openai_tools(tools):
    """The Anthropic-format menu, rewrapped for OpenAI-style AIs."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}} for t in tools]


# =============================================================================
# Pick the AI from .env
# =============================================================================

def connect(system, tools, provider=ASSISTANT_PROVIDER, model=None):
    """The chat object for `provider`, with .ask(), .provider and .model.
    `model` picks another BFH model for one feature, e.g. the Workshop (SPEC §14.10);
    without it nothing changes. Raises NotConfigured if .env is missing something; prints nothing."""
    if provider not in PROVIDERS:
        raise NotConfigured(f"Unknown ASSISTANT_PROVIDER '{provider}' in .env. Choose one of: {', '.join(PROVIDERS)}")
    dialect, base_url, key_name, default_model = PROVIDERS[provider]

    if provider == "bfh":
        # Client and model both come from InferenceService, so the assistant uses exactly
        # the model /health checks. ASSISTANT_MODEL is ignored here (SPEC §13.2).
        inference = InferenceService()
        try:
            client = inference.get_client()
        except RuntimeError as e:
            raise NotConfigured(str(e))
        chat = OpenAIChat(client, model or inference.model, system, tools)
    else:
        model = ASSISTANT_MODEL or default_model
        if not model:
            raise NotConfigured("Set ASSISTANT_MODEL=... in your .env file.")
        key = os.getenv(key_name) if key_name else None
        if key_name and not key:
            raise NotConfigured(f"ASSISTANT_PROVIDER={provider} needs {key_name}=... in your .env file.")
        if dialect == "anthropic":
            chat = AnthropicChat(model, key, system, tools)
        else:
            import openai
            chat = OpenAIChat(openai.OpenAI(api_key=key or "not-needed", base_url=base_url), model, system, tools)
    chat.provider = provider
    return chat
