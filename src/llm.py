"""Chat client for OpenAI-compatible APIs (Together, or vLLM on the pod): disk cache, retries,
cost log, budget stop.

Every uncached call appends a line to runs/costs.jsonl (vLLM models cost $0 here; GPU time is
logged separately by src/costs.py). Before each uncached call, the chunk's total so far is
checked against its cap in config.yaml; reaching it raises BudgetExceeded.
"""
import hashlib
import json
import os
import uuid
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT, load_env

COSTS_PATH = ROOT / "runs/costs.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class RetryableError(LLMError):
    """Rate limit, server error, network error or a call past its hard timeout: worth another attempt."""


class CallTimeout(RetryableError):
    pass


def spent(chunk, path=COSTS_PATH):
    if not Path(path).exists():
        return 0.0
    with open(path) as f:
        return sum(r["usd"] for r in map(json.loads, f) if r["chunk"] == chunk)


class LLMClient:
    def __init__(self, cfg, chunk, cache_dir=None, costs_path=COSTS_PATH, post=None,
                 base_url=None, api_key_env="TOGETHER_API_KEY", run_id=None):
        llm = cfg["llm"]
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
        self.chunk = chunk
        self.cap = cfg["budget"]["chunk_caps_usd"][chunk]
        self.cache_dir = Path(cache_dir or ROOT / llm["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.costs_path = Path(costs_path)
        self.post = post or self._post
        self.paid_calls = 0

    def chat(self, model, messages, purpose, temperature=0.0, max_tokens=2000, seed=0, sample=0, extra=None):
        """Return the reply text. Cached on every input that can change the reply."""
        return self.chat_full(model, messages, purpose, temperature, max_tokens, seed, sample, extra)["text"]

    def chat_full(self, model, messages, purpose, temperature=0.0, max_tokens=2000, seed=0, sample=0, extra=None):
        """{"text", "usage", "finish_reason"}; cached like chat()."""
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, "seed": seed, **(extra or {})}
        key = hashlib.sha256(json.dumps({**body, "sample": sample}, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            return {"finish_reason": None, **cached}

        with self.lock:
            if spent(self.chunk, self.costs_path) >= self.cap:
                raise BudgetExceeded(f"chunk {self.chunk} reached its ${self.cap} cap")
        long = purpose in self.long_purposes
        data = self.with_retries(body, self.long_timeout if long else self.timeout, self.long_retries if long else self.retries)
        choice = data["choices"][0]
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

    def with_retries(self, body, timeout, retries):
        """At most retries + 1 attempts, each cut off after `timeout` seconds of wall clock however the
        server behaves. Exhausting them raises LLMError, which every caller treats as a failure."""
        last = None
        for attempt in range(retries + 1):
            try:
                return self.call_with_deadline(body, timeout)
            except RetryableError as e:
                last = e
                if attempt < retries:
                    time.sleep(self.backoff * 2**attempt)
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
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                raise RetryableError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
            raise LLMError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RetryableError(f"network error: {e}") from None
