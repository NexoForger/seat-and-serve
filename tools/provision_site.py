"""Create a separate Frappe site/database for one business.

Run from the app repository inside a configured bench container. Required
passwords are read from environment and never printed by this script.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path


BENCH = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="DNS hostname for one business site")
    parser.add_argument("--db-host", default=os.getenv("TRT_DB_HOST"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,120}", args.site) or ".." in args.site:
        parser.error("Use a lowercase DNS hostname")
    if (BENCH / "sites" / args.site).exists():
        parser.error("Site already exists; provisioning will not overwrite it")
    root_password = os.getenv("TRT_DB_ROOT_PASSWORD")
    admin_password = os.getenv("TRT_SITE_ADMIN_PASSWORD")
    if not args.dry_run and (not root_password or not admin_password):
        parser.error("Set TRT_DB_ROOT_PASSWORD and TRT_SITE_ADMIN_PASSWORD")
    command = ["bench", "new-site", args.site,
        "--install-app", "erpnext", "--install-app", "hrms",
        "--install-app", "table_remote_till"]
    if args.db_host:
        command.extend(["--db-host", args.db_host])
    if args.dry_run:
        print("Will create one site and database and install ERPNext, HRMS, and S&S (Seat & Serve):")
        print(" ".join(command))
        return
    command.extend(["--db-root-password", root_password,
        "--admin-password", admin_password])
    subprocess.run(command, cwd=BENCH, check=True)
    print(f"Site {args.site} is ready. Complete ERPNext setup and visit /onboarding.")


if __name__ == "__main__":
    main()
