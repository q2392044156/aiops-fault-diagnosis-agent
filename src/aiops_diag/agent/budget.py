import json
import threading
from pathlib import Path

from aiops_diag.rag.client import BudgetExceeded


class DatabaseBudgetLedger:
    """SQLite-backed process-safe adapter for the existing DeepSeek client."""

    def __init__(self, database, provider, budget, legacy_path=None, scope="shared"):
        self.database = database
        self.provider = provider
        self.budget = budget
        self.scope = scope
        self.local = threading.local()
        self.database.settle_provider_reservations_conservatively(provider, scope)
        legacy = {}
        if legacy_path and Path(legacy_path).is_file():
            legacy = json.loads(Path(legacy_path).read_text(encoding="utf-8"))
        self.database.import_provider_usage(provider, legacy)

    def read(self):
        return self.database.provider_usage(self.provider)

    def reserve_check(self, reserved_output_tokens=0):
        self.close()
        output = int(reserved_output_tokens)
        reserved_input = int(self.budget.get("max_input_tokens_per_call", 10000))
        tokens = output + reserved_input
        cost = (reserved_input * self.budget["input_cny_per_million"]
                + output * self.budget["output_cny_per_million"]) / 1_000_000
        try:
            reservation = self.database.reserve_provider_usage(
                self.provider, self.scope, tokens, cost,
                self.budget["max_total_tokens"], self.budget["max_cost_cny"])
        except RuntimeError as exc:
            raise BudgetExceeded(str(exc)) from exc
        self.local.reservation = reservation

    def close(self):
        reservation = getattr(self.local, "reservation", None)
        if reservation:
            self.database.settle_provider_reservations_conservatively(
                self.provider, self.scope, reservation)
            self.local.reservation = None

    def record(self, input_tokens, output_tokens):
        reservation = getattr(self.local, "reservation", None)
        if not reservation:
            raise BudgetExceeded("Provider request has no budget reservation")
        state = self.database.settle_provider_usage(
            reservation, input_tokens, output_tokens,
            self.budget["input_cny_per_million"],
            self.budget["output_cny_per_million"],
        )
        self.local.reservation = None
        if (state["input_tokens"] + state["output_tokens"]
                > self.budget["max_total_tokens"]):
            raise BudgetExceeded("API usage crossed the token budget")
        if state["estimated_cost_cny"] > self.budget["max_cost_cny"]:
            raise BudgetExceeded("API usage crossed the cost budget")
        return state
