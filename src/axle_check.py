"""AXLE `check` wrapper: disk cache, retries, and outages kept apart from Lean errors.

Statuses:
  ok          compiles (AXLE `okay`). A `sorry` shows up in failed_declarations; that is fine.
  lean_error  Lean rejected the code.
  timeout     Lean ran past its time budget. A failure, counted separately.
  resource    Lean hit a resource cap (memory). A failure, counted separately.
  outage      AXLE itself failed after all retries. Never cached, never scored.
"""
import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import axle

from src.config import ROOT, load_env

OK, LEAN_ERROR, TIMEOUT, RESOURCE, OUTAGE = "ok", "lean_error", "timeout", "resource", "outage"

# AxleRuntimeError means "reached the executors but all of them crashed"; it is a server
# fault rather than a Lean verdict, so it counts as an outage too.
OUTAGE_ERRORS = (
    axle.AxleIsUnavailable,
    axle.AxleRateLimitedError,
    axle.AxleInternalError,
    axle.AxleRuntimeError,
)


@dataclass
class CheckResult:
    status: str
    errors: list[str] = field(default_factory=list)
    failed_declarations: list[str] = field(default_factory=list)

    @property
    def passed(self):
        return self.status == OK


@dataclass
class NormalizeResult:
    status: str
    errors: list[str] = field(default_factory=list)
    content: str | None = None


class AxleChecker:
    def __init__(self, cfg, client_factory=None, cache_dir=None):
        self.environment = cfg["environment"]
        self.timeout_seconds = cfg["timeout_seconds"]
        self.max_concurrency = cfg["max_concurrency"]
        self.outage_retries = cfg["outage_retries"]
        self.outage_backoff_seconds = cfg["outage_backoff_seconds"]
        self.cache_dir = Path(cache_dir or ROOT / cfg["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if client_factory is None:
            load_env()

            def client_factory():
                return axle.AxleClient(
                    max_concurrency=self.max_concurrency,
                    base_timeout_seconds=cfg["client_timeout_seconds"],
                )

        self.client_factory = client_factory
        self.api_calls = 0

    def cache_path(self, content, tool="check", options=None):
        key = {
            "tool": tool,
            "environment": self.environment,
            "content": content,
            "ignore_imports": True,
            "timeout_seconds": self.timeout_seconds,
        }
        if options:
            key["options"] = options
        key = json.dumps(key, sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def check(self, content):
        return self.check_many([content])[0]

    def check_many(self, contents, progress_every=0):
        return asyncio.run(self._run_many(contents, "check", None, progress_every))

    def normalize_many(self, contents, normalizations, progress_every=0):
        """AXLE `normalize` (failsafe on: content comes back unchanged if normalizing breaks it).

        Returns NormalizeResult per content; on timeout, resource or outage, `content` is None.
        """
        return asyncio.run(self._run_many(contents, "normalize", {"normalizations": normalizations}, progress_every))

    async def _run_many(self, contents, tool, options, progress_every):
        sem = asyncio.Semaphore(self.max_concurrency)
        done = 0
        async with self.client_factory() as client:

            async def one(content):
                nonlocal done
                async with sem:
                    result = await self._run_one(client, tool, content, options)
                done += 1
                if progress_every and done % progress_every == 0:
                    print(f"  {tool} {done}/{len(contents)}", flush=True)
                return result

            return await asyncio.gather(*(one(c) for c in contents))

    async def _call(self, client, tool, content, options):
        kwargs = dict(content=content, environment=self.environment, ignore_imports=True,
                      timeout_seconds=self.timeout_seconds)
        if tool == "check":
            resp = await client.check(**kwargs)
            status = OK if resp.okay else LEAN_ERROR
            return CheckResult(status, list(resp.lean_messages.errors), list(resp.failed_declarations))
        resp = await client.normalize(**kwargs, normalizations=options["normalizations"], failsafe=True)
        return NormalizeResult(OK, list(resp.lean_messages.errors), resp.content)

    async def _run_one(self, client, tool, content, options):
        result_cls = CheckResult if tool == "check" else NormalizeResult
        path = self.cache_path(content, tool, options)
        if path.exists():
            return result_cls(**json.loads(path.read_text()))

        result = None
        for attempt in range(self.outage_retries + 1):
            try:
                self.api_calls += 1
                result = await self._call(client, tool, content, options)
                break
            except axle.LeanTimeout as e:
                result = result_cls(TIMEOUT, [str(e)])
                break
            except axle.LeanResourceExceeded as e:
                result = result_cls(RESOURCE, [str(e)])
                break
            except OUTAGE_ERRORS as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < self.outage_retries:
                    await asyncio.sleep(self.outage_backoff_seconds * 2**attempt)

        if result is None:
            return result_cls(OUTAGE, [last_error])

        tmp = path.with_suffix(f".tmp{uuid.uuid4().hex}")  # unique: threads may write the same key
        tmp.write_text(json.dumps(asdict(result)))
        tmp.replace(path)
        return result
