"""Chat client for OpenAI-compatible APIs (Together, or vLLM on the pod): disk cache, retries,
cost log, budget stop.

Every uncached call appends a line to runs/costs.jsonl (vLLM models cost $0 here; GPU time is
logged separately by src/costs.py). Before each uncached call, the chunk's total so far is
checked against its cap in config.yaml; reaching it raises BudgetExceeded.
"""
import email.utils
import hashlib
import http.client
import json
import os
import random
import uuid
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT, load_env

COSTS_PATH = ROOT / "runs/costs.jsonl"
FAILURES_PATH = ROOT / "runs/api_failures.jsonl"  # every failed attempt: timeouts, retryable and other errors
MAX_RETRY_AFTER = 600  # seconds: the longest a 429's Retry-After may make us wait before one retry


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class RetryableError(LLMError):
    """Rate limit, server error, network error or a call past its hard timeout: worth another attempt.
    retry_after: seconds from a 429's Retry-After header, if it sent one."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class CallTimeout(RetryableError):
    pass


def retry_after_seconds(value, now=None):
    """A Retry-After header (seconds or an HTTP date) as seconds; None if absent or unreadable."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError):
        return None


def assemble_stream(lines):
    """A server-sent-events reply (OpenRouter, `stream: true`) as one non-streaming reply: the content deltas
    joined, the last finish_reason, usage and provider. Keep-alive comments are skipped. An error chunk, a
    finish_reason of "error" or a stream without a finish_reason is a RetryableError."""
    text, finish, usage, provider, error = [], None, {}, None, None
    for raw in lines:
        line = (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw).strip()
        if not line.startswith("data:"):
            continue  # blank separators and ": OPENROUTER PROCESSING" keep-alives
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        error = chunk.get("error") or error
        provider = chunk.get("provider") or provider
        usage = chunk.get("usage") or usage
        for c in chunk.get("choices") or []:
            text.append((c.get("delta") or {}).get("content") or "")
            finish = c.get("finish_reason") or finish
            error = c.get("error") or error
    if error or finish == "error":
        raise RetryableError(f"stream error: {str(error)[:300]}")
    if finish is None:
        raise RetryableError("stream ended without a finish_reason")
    return {"choices": [{"message": {"content": "".join(text)}, "finish_reason": finish}], "usage": usage,
            **({"provider": provider} if provider else {})}


def spent(chunk, path=COSTS_PATH):
    if not Path(path).exists():
        return 0.0
    with open(path) as f:
        return sum(r["usd"] for r in map(json.loads, f) if r["chunk"] == chunk)


class LLMClient:
    def __init__(self, cfg, chunk, cache_dir=None, costs_path=COSTS_PATH, post=None,
                 base_url=None, api_key_env="TOGETHER_API_KEY", run_id=None, extra_body=None, drop_params=(), limits=None,
                 stream=False):
        llm = cfg["llm"]
        # A host's fixed request fields (OpenRouter's provider pin) and the fields it must not get (seed);
        # both apply before the cache key, so the key is exactly what is sent.
        self.extra_body, self.drop_params = dict(extra_body or {}), tuple(drop_params)
        # Transport only: a streamed reply is assembled into the same reply (OpenRouter's gateway cuts
        # non-streaming requests off at about 300 s; chunk 5, D_s2).
        self.stream = stream
        self.base_url = (base_url or llm["base_url"]).rstrip("/")
        self.api_key_env = api_key_env
        self.run_id = run_id
        self.lock = threading.Lock()
        self.prices = llm["prices"]
        self.retries = llm["retries"]
        self.backoff = llm["backoff_seconds"]
        self.timeout = llm["timeout_seconds"]
        # Long calls (formalizer generations, reflection) get a longer hard timeout and fewer retries, so a
        # hung call costs at most (retries + 1) * timeout before it fails loudly.
        self.long_purposes = set(llm.get("long_purposes", []))
        self.long_timeout = llm.get("long_timeout_seconds", self.timeout)
        self.long_retries = llm.get("long_retries", self.retries)
        self.purpose_limits = llm.get("purpose_limits", {})  # per purpose, wins over the two above
        self.client_limits = limits  # per client (arm F, Deviation 3), wins over everything above
        self.chunk = chunk
        self.cap = cfg["budget"]["chunk_caps_usd"][chunk]
        self.cache_dir = Path(cache_dir or ROOT / llm["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.costs_path = Path(costs_path)
        self.failures_path = self.costs_path.parent / FAILURES_PATH.name
        self.post = post or self._post
        self.paid_calls = 0
        self.sleep = time.sleep  # tests replace it

    def chat(self, model, messages, purpose, temperature=0.0, max_tokens=2000, seed=0, sample=0, extra=None):
        """Return the reply text. Cached on every input that can change the reply."""
        return self.chat_full(model, messages, purpose, temperature, max_tokens, seed, sample, extra)["text"]

    def chat_full(self, model, messages, purpose, temperature=0.0, max_tokens=2000, seed=0, sample=0, extra=None):
        """{"text", "usage", "finish_reason"}; cached like chat()."""
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, "seed": seed, **(extra or {}), **self.extra_body}
        for k in self.drop_params:
            body.pop(k, None)
        if self.stream:
            body["stream"] = True
        key = hashlib.sha256(json.dumps({**body, "sample": sample}, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            return {"finish_reason": None, **cached}

        with self.lock:
            if spent(self.chunk, self.costs_path) >= self.cap:
                raise BudgetExceeded(f"chunk {self.chunk} reached its ${self.cap} cap")
        timeout, retries = self.limits(purpose)
        t0 = time.monotonic()
        data = self.with_retries(body, timeout, retries, purpose=purpose)
        seconds = time.monotonic() - t0
        choice = data["choices"][0]  # with_retries returns only replies that have choices
        out = {"text": choice["message"].get("content") or "", "usage": data.get("usage") or {},
               "finish_reason": choice.get("finish_reason")}
        usd = self.cost(model, out["usage"])
        with self.lock:
            self.paid_calls += 1
            self.costs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.costs_path, "a") as f:
                f.write(json.dumps({
                    "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chunk": self.chunk,
                    "run_id": self.run_id, "purpose": purpose, "model": model,
                    "prompt_tokens": out["usage"].get("prompt_tokens", 0),
                    "completion_tokens": out["usage"].get("completion_tokens", 0), "usd": usd,
                    "seconds": round(seconds, 1),
                    **({"provider": data["provider"]} if data.get("provider") else {}),  # OpenRouter: who served it
                }) + "\n")
        tmp = path.with_suffix(f".tmp{uuid.uuid4().hex}")  # unique: threads may write the same key
        tmp.write_text(json.dumps(out))
        tmp.replace(path)
        return out

    def cost(self, model, usage):
        if model not in self.prices:
            raise LLMError(f"no price for {model} in config.yaml")
        p = self.prices[model]
        return (usage.get("prompt_tokens", 0) * p["input"] + usage.get("completion_tokens", 0) * p["output"]) / 1e6

    def limits(self, purpose):
        """(hard timeout per attempt in seconds, retries) for a call made for `purpose`."""
        if self.client_limits:
            return self.client_limits["timeout_seconds"], self.client_limits["retries"]
        if purpose in self.purpose_limits:
            lim = self.purpose_limits[purpose]
            return lim["timeout_seconds"], lim["retries"]
        if purpose in self.long_purposes:
            return self.long_timeout, self.long_retries
        return self.timeout, self.retries

    def backoff_for(self, purpose):
        """Base wait in seconds before the first retry (it doubles each retry); per purpose if set."""
        if self.client_limits and "backoff_seconds" in self.client_limits:
            return self.client_limits["backoff_seconds"]
        return self.purpose_limits.get(purpose, {}).get("backoff_seconds", self.backoff)

    def retry_delay(self, attempt, purpose, error):
        """Exponential backoff with +-20% jitter, so parallel runs don't retry in step. A 429's
        Retry-After wins when it asks for longer, up to MAX_RETRY_AFTER."""
        delay = self.backoff_for(purpose) * 2**attempt * random.uniform(0.8, 1.2)
        after = getattr(error, "retry_after", None)
        return max(delay, min(after, MAX_RETRY_AFTER)) if after is not None else delay

    def log_failure(self, body, purpose, error, seconds):
        with self.lock:
            self.failures_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.failures_path, "a") as f:
                f.write(json.dumps({
                    "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chunk": self.chunk,
                    "run_id": self.run_id, "purpose": purpose, "model": body.get("model"),
                    "kind": "timeout" if isinstance(error, CallTimeout) else type(error).__name__,
                    "error": str(error)[:300], "seconds": round(seconds, 1),
                }) + "\n")

    def with_retries(self, body, timeout, retries, purpose=None):
        """At most retries + 1 attempts, each cut off after `timeout` seconds of wall clock however the
        server behaves. Every failed attempt is logged; exhausting them raises LLMError, which every
        caller treats as a failure."""
        last = None
        for attempt in range(retries + 1):
            t0 = time.monotonic()
            try:
                data = self.call_with_deadline(body, timeout)
                if not data.get("choices"):  # OpenRouter can send an error inside an HTTP 200 reply
                    raise RetryableError(f"reply without choices: {str(data.get('error'))[:300]}")
                return data
            except RetryableError as e:
                self.log_failure(body, purpose, e, time.monotonic() - t0)
                last = e
                if attempt < retries:
                    self.sleep(self.retry_delay(attempt, purpose, e))
            except LLMError as e:
                self.log_failure(body, purpose, e, time.monotonic() - t0)
                raise
        raise LLMError(f"gave up after {retries + 1} attempts: {last}")

    def call_with_deadline(self, body, timeout):
        """One attempt in a daemon thread; past the deadline it is abandoned and counts as a timeout."""
        box = {}

        def run():
            try:
                box["data"] = self._post(body, timeout) if self.post == self._post else self.post(body)
            except BaseException as e:  # handed to the caller below
                box["error"] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise CallTimeout(f"no reply within {timeout} s")
        if "error" in box:
            raise box["error"]
        return box["data"]

    def _post(self, body, timeout=None):
        load_env()
        headers = {"Content-Type": "application/json", "User-Agent": "gepa-lean-formalizers"}
        if self.api_key_env:
            headers["Authorization"] = f"Bearer {os.environ[self.api_key_env]}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return assemble_stream(resp) if body.get("stream") else json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (408, 429, 500, 502, 503, 504):
                after = retry_after_seconds(e.headers.get("Retry-After")) if e.code == 429 and e.headers else None
                raise RetryableError(f"HTTP {e.code}: {e.read()[:300]!r}", retry_after=after) from None
            raise LLMError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RetryableError(f"network error: {e}") from None
        except (http.client.HTTPException, json.JSONDecodeError) as e:  # a reply cut off mid-body (IncompleteRead)
            raise RetryableError(f"broken reply: {type(e).__name__}: {e}") from None
