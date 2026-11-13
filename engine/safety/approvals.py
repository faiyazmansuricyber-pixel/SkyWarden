from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import Lock
from typing import Protocol


class ApprovalProvider(Protocol):
    def approve(self, context: Mapping[str, object]) -> bool: ...


class CliApprovalProvider:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], object] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn
        self._approved_plans: set[str] = set()
        self._lock = Lock()

    def approve(self, context: Mapping[str, object]) -> bool:
        plan_id = context.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            return False
        with self._lock:
            if plan_id in self._approved_plans:
                return True
            self._output(f"R2 approval required for plan {plan_id}.")
            try:
                answer = self._input("Approve this financial test? Type 'approve': ")
            except EOFError:
                return False
            if answer.strip().lower() != "approve":
                return False
            self._approved_plans.add(plan_id)
            return True


class TestApprovalProvider:
    def __init__(self, approved_plan_ids: set[str] | None = None) -> None:
        self._approved_plans = set(approved_plan_ids or ())
        self._lock = Lock()

    def approve(self, context: Mapping[str, object]) -> bool:
        plan_id = context.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            return False
        with self._lock:
            return plan_id in self._approved_plans

    def approve_plan(self, plan_id: str) -> None:
        if not plan_id:
            raise ValueError("plan_id must be non-empty.")
        with self._lock:
            self._approved_plans.add(plan_id)
