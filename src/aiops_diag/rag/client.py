import json
import os
import threading
import time
from pathlib import Path

import httpx

from aiops_diag.data.common import save


class BudgetExceeded(RuntimeError):
    pass


class DeepSeekError(RuntimeError):
    pass


class DeepSeekJsonError(DeepSeekError):
    def __init__(self, message, usage):
        super().__init__(message)
        self.usage = usage


def _secret(env_name, file_env_name):
    direct = os.environ.get(env_name)
    if direct:
        return direct.strip()
    file_name = os.environ.get(file_env_name)
    if file_name:
        path = Path(file_name)
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return None


class BudgetLedger:
    _lock = threading.Lock()

    def __init__(self, path, budget):
        self.path = Path(path)
        self.budget = budget

    def read(self):
        if not self.path.exists():
            return {"schema_version": 1, "input_tokens": 0, "output_tokens": 0,
                    "estimated_cost_cny": 0.0, "calls": 0}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def reserve_check(self, reserved_output_tokens=0):
        state = self.read()
        if (state["input_tokens"] + state["output_tokens"] + int(reserved_output_tokens)
                > self.budget["max_total_tokens"]):
            raise BudgetExceeded("Token budget has been exhausted")
        reserved_cost = (int(reserved_output_tokens)
                         * self.budget["output_cny_per_million"] / 1_000_000)
        if state["estimated_cost_cny"] + reserved_cost > self.budget["max_cost_cny"]:
            raise BudgetExceeded("Cost budget has been exhausted")

    def record(self, input_tokens, output_tokens):
        with self._lock:
            state = self.read()
            state["input_tokens"] += int(input_tokens)
            state["output_tokens"] += int(output_tokens)
            state["calls"] += 1
            state["estimated_cost_cny"] = round(
                state["input_tokens"] * self.budget["input_cny_per_million"] / 1_000_000
                + state["output_tokens"] * self.budget["output_cny_per_million"] / 1_000_000,
                8,
            )
            if state["input_tokens"] + state["output_tokens"] > self.budget["max_total_tokens"]:
                raise BudgetExceeded("API usage crossed the token budget")
            if state["estimated_cost_cny"] > self.budget["max_cost_cny"]:
                raise BudgetExceeded("API usage crossed the cost budget")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            save(self.path, state)
            return state


class DeepSeekClient:
    def __init__(self, cfg, transport=None):
        provider = cfg["provider"]
        self.cfg = cfg
        self.api_key = _secret(provider["api_key_env"], provider["api_key_file_env"])
        self.tracking_id = _secret(provider["tracking_id_env"], provider["tracking_id_file_env"])
        self.ledger = BudgetLedger(cfg["paths"]["budget_ledger"], cfg["budget"])
        self.http = httpx.Client(base_url=provider["base_url"].rstrip("/"),
                                 timeout=provider["timeout_seconds"], transport=transport,
                                 trust_env=False)

    @property
    def configured(self):
        return bool(self.api_key)

    def close(self):
        self.http.close()

    def complete_json(self, messages):
        if not self.api_key:
            raise DeepSeekError("DeepSeek API key is not configured")
        provider = self.cfg["provider"]
        self.ledger.reserve_check(provider["max_tokens"])
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": provider["model"], "messages": messages,
                   "response_format": {"type": "json_object"},
                   "thinking": {"type": "disabled"},
                   "reasoning_effort": "none",
                   "temperature": provider["temperature"],
                   "max_tokens": provider["max_tokens"], "stream": False}
        started = time.monotonic()
        response = None
        for attempt in range(3):
            try:
                response = self.http.post("/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 or status >= 500:
                    if attempt < 2 and time.monotonic() - started < provider["overall_timeout_seconds"]:
                        retry_after = exc.response.headers.get("Retry-After")
                        delay = min(float(retry_after), 2.0) if retry_after else 0.5 * (2 ** attempt)
                        time.sleep(max(0.0, delay))
                        continue
                try:
                    error_code = exc.response.json().get("error", {}).get("code")
                except (ValueError, AttributeError):
                    error_code = None
                suffix = f" ({error_code})" if error_code else ""
                raise DeepSeekError(f"DeepSeek API HTTP {status}{suffix}") from exc
            except httpx.RequestError as exc:
                if attempt < 2 and time.monotonic() - started < provider["overall_timeout_seconds"]:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise DeepSeekError(f"DeepSeek network failure: {type(exc).__name__}") from exc
        if response is None:
            raise DeepSeekError("DeepSeek request did not produce a response")
        try:
            data = response.json()
            if time.monotonic() - started > provider["overall_timeout_seconds"]:
                raise DeepSeekError("DeepSeek request exceeded the overall time limit")
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            self.ledger.record(input_tokens, output_tokens)
            call_cost = (input_tokens * self.cfg["budget"]["input_cny_per_million"]
                         + output_tokens * self.cfg["budget"]["output_cny_per_million"]) / 1_000_000
            usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                     "estimated_cost_cny": round(call_cost, 8)}
        except (KeyError, TypeError, ValueError) as exc:
            raise DeepSeekError(f"DeepSeek JSON request failed: {type(exc).__name__}") from exc
        try:
            return json.loads(content), usage
        except json.JSONDecodeError as exc:
            raise DeepSeekJsonError("DeepSeek returned invalid or truncated JSON", usage) from exc
