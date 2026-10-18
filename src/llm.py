"""Chat client for OpenAI-compatible APIs (Together): disk cache, retries, cost log, budget stop.

Every paid call appends a line to runs/costs.jsonl. Before each uncached call, the chunk's total
so far is checked against its cap in config.yaml; reaching it raises BudgetExceeded.
"""
import hashlib
import json
import os
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


def spent(chunk, path=COSTS_PATH):
    if not Path(path).exists():
        return 0.0
    with open(path) as f:
        return sum(r["usd"] for r in map(json.loads, f) if r["chunk"] == chunk)


class LLMClient:
    def __init__(self, cfg, chunk, cache_dir=None, costs_path=COSTS_PATH, post=None):
        llm = cfg["llm"]
        self.base_url = llm["base_url"].rstrip("/")
        self.prices = llm["prices"]
        self.retries = llm["retries"]
        self.backoff = llm["backoff_seconds"]
        self.timeout = llm["timeout_seconds"]
        self.chunk = chunk
        self.cap = cfg["budget"]["chunk_caps_usd"][chunk]
        self.cache_dir = Path(cache_dir or ROOT / llm["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.costs_path = Path(costs_path)
        self.post = post or self._post
        self.paid_calls = 0

    def chat(self, model, messages, purpose, temperature=0.0, max_tokens=2000, seed=0, sample=0, extra=None):
        """Return the reply text. Cached on every input that can change the reply."""
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, "seed": seed, **(extra or {})}
        key = hashlib.sha256(json.dumps({**body, "sample": sample}, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())["text"]

        if spent(self.chunk, self.costs_path) >= self.cap:
            raise BudgetExceeded(f"chunk {self.chunk} reached its ${self.cap} cap")
        data = self.post(body)
        text = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        usd = self.cost(model, usage)
        self.paid_calls += 1
        self.costs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.costs_path, "a") as f:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chunk": self.chunk,
                "purpose": purpose, "model": model, "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0), "usd": usd,
            }) + "\n")
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps({"text": text, "usage": usage}))
        tmp.replace(path)
        return text

    def cost(self, model, usage):
        if model not in self.prices:
            raise LLMError(f"no price for {model} in config.yaml")
        p = self.prices[model]
        return (usage.get("prompt_tokens", 0) * p["input"] + usage.get("completion_tokens", 0) * p["output"]) / 1e6

    def _post(self, body):
        load_env()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {os.environ['TOGETHER_API_KEY']}",
                     "Content-Type": "application/json", "User-Agent": "gepa-lean-formalizers"},
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise LLMError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.retries:
                    raise LLMError(f"network error: {e}") from None
            time.sleep(self.backoff * 2**attempt)
