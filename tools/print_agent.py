#!/usr/bin/env python3
"""Poll a remote ERP over HTTPS and print locally. No inbound listener is needed."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from table_remote_till.printing import PrintError, send, target


class NoRedirect(HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		return None


def remote(site, token):
	url = urlsplit(site)
	if not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
		raise ValueError("Use the ERP site's base URL")
	if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")):
		raise ValueError("Remote ERP connections require HTTPS")
	if ":" not in token:
		raise ValueError("Set TRT_PRINT_AGENT_TOKEN to the dedicated Frappe user's API key:secret")
	opener = build_opener(NoRedirect)
	def call(method, args):
		request = Request(site.rstrip("/") + "/api/method/table_remote_till.print_jobs." + method,
			data=json.dumps(args).encode(), method="POST",
			headers={"Authorization": "token " + token, "Content-Type": "application/json"})
		with opener.open(request, timeout=20) as response:
			result = json.load(response)
		if "message" not in result or result.get("exc"):
			raise RuntimeError("ERP rejected the print-agent request")
		return result["message"]
	return call


def open_journal(path):
	path = Path(path).expanduser()
	path.parent.mkdir(parents=True, exist_ok=True)
	journal = sqlite3.connect(path)
	journal.execute("PRAGMA journal_mode=WAL")
	journal.execute("""CREATE TABLE IF NOT EXISTS jobs (
		name TEXT PRIMARY KEY, claim_token TEXT NOT NULL, status TEXT NOT NULL,
		error TEXT NOT NULL DEFAULT '', acknowledged INTEGER NOT NULL DEFAULT 0)""")
	journal.commit()
	return journal


def run_once(call, journal, outlet, agent, usb_queues, lan_addresses):
	# Retry acknowledgement only. A dispatch reserved before a crash is unknown,
	# and must never be printed/opened again automatically.
	journal.execute("UPDATE jobs SET status='Unknown', error='Agent restarted during dispatch; check physical result' WHERE status='Dispatching'")
	journal.commit()
	def acknowledge():
		for name, token, status, error in journal.execute(
			"SELECT name, claim_token, status, error FROM jobs WHERE acknowledged=0").fetchall():
			call("acknowledge", {"job_name": name, "claim_token": token, "status": status, "error": error})
			journal.execute("UPDATE jobs SET acknowledged=1 WHERE name=?", (name,))
			journal.commit()
	acknowledge()
	jobs = call("claim", {"outlet": outlet, "agent": agent})
	received_at = time.monotonic()
	for job in jobs:
		prior = journal.execute("SELECT name FROM jobs WHERE name=?", (job["name"],)).fetchone()
		if prior:
			continue
		journal.execute("INSERT INTO jobs(name,claim_token,status) VALUES (?,?, 'Dispatching')", (job["name"], job["claim_token"]))
		journal.commit()  # Durable before hardware I/O, including an uncertain process exit.
		try:
			remaining = job.get("expires_in")
			if ((remaining is not None and time.monotonic() - received_at >= remaining)
				or (remaining is None and job.get("expires_unix") and job["expires_unix"] <= time.time())):
				raise PrintError("Drawer action expired; no pulse sent")
			device = SimpleNamespace(**job["target"])
			driver, destination = target(device)
			if driver == "escpos_usb" and destination not in usb_queues:
				raise PrintError("USB queue is not in this agent's allowlist")
			if driver == "escpos_tcp" and f"{destination[0]}:{destination[1]}" not in lan_addresses:
				raise PrintError("LAN printer is not in this agent's allowlist")
			payload = base64.b64decode(job["payload"], validate=True)
			if not payload or len(payload) > 4_000_000:
				raise PrintError("Invalid print payload size")
			result = send(device, payload)
			status, error = result["status"], ""
		except Exception as failure:
			status, error = "Unknown", str(failure)[:500]
			logging.warning("Job %s: %s", job["name"], error)
		journal.execute("UPDATE jobs SET status=?,error=? WHERE name=?", (status, error, job["name"]))
		journal.commit()
	acknowledge()
	return len(jobs)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--site", required=True, help="HTTPS ERP site URL")
	parser.add_argument("--outlet", required=True)
	parser.add_argument("--agent", required=True, help="Agent name configured on the receipt device")
	parser.add_argument("--allow-usb", action="append", default=[], help="Allowed OS printer queue; repeat for more queues")
	parser.add_argument("--allow-lan", action="append", default=[], help="Allowed local printer IP:port; repeat for more printers")
	parser.add_argument("--journal", default="~/.local/share/seat-and-serve/print-agent.sqlite")
	parser.add_argument("--interval", type=float, default=2)
	parser.add_argument("--once", action="store_true")
	args = parser.parse_args()
	if not args.allow_usb and not args.allow_lan:
		parser.error("Allow at least one local USB queue or LAN printer")
	if args.interval < 1:
		parser.error("Polling interval must be at least one second")
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	call = remote(args.site, os.environ.get("TRT_PRINT_AGENT_TOKEN", ""))
	journal = open_journal(args.journal)
	try:
		while True:
			try:
				run_once(call, journal, args.outlet, args.agent, set(args.allow_usb), set(args.allow_lan))
			except Exception as error:
				logging.warning("ERP connection/acknowledgement failed: %s", error)
				if args.once:
					raise
			if args.once:
				break
			time.sleep(args.interval)
	except KeyboardInterrupt:
		pass
	finally:
		journal.close()


if __name__ == "__main__":
	main()
