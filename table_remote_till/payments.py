"""Payment provider boundary. Only Sandbox is implemented for development."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import frappe


@dataclass(frozen=True)
class Intent:
	provider: str
	status: str
	provider_reference: str | None = None
	checkout_url: str | None = None


class PaymentProvider(Protocol):
	name: str

	def create_intent(self, *, amount: float, currency: str, key: str) -> Intent: ...
	def capture(self, *, reference: str | None, amount: float, currency: str) -> str: ...


class SandboxProvider:
	name = "Sandbox"

	def create_intent(self, *, amount: float, currency: str, key: str) -> Intent:
		if amount <= 0 or not currency or not key:
			frappe.throw("Valid sandbox payment amount and key required")
		return Intent(provider=self.name, status="Pending", provider_reference=key)

	def capture(self, *, reference: str | None, amount: float, currency: str) -> str:
		if not reference or amount <= 0:
			frappe.throw("Invalid sandbox capture")
		return "Captured"


def configured_provider(outlet) -> PaymentProvider:
	if outlet.online_provider == "Sandbox" and outlet.allow_sandbox_payments and frappe.conf.developer_mode:
		return SandboxProvider()
	frappe.throw("Online payment provider is not configured for this outlet")
