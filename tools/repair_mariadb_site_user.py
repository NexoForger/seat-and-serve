"""Repair a Frappe site's MariaDB login after its Docker container IP changes.

Run inside the Frappe container. This creates or updates only the site's
MariaDB user at host %, then grants access to its existing database. It does
not create, drop, or modify site tables.
"""

import argparse
import getpass
import json
import re
from pathlib import Path


BENCH = Path(__file__).resolve().parents[2]


def load_config(site):
    site_config = BENCH / "sites" / site / "site_config.json"
    common_config = BENCH / "sites" / "common_site_config.json"
    if not site_config.is_file():
        raise ValueError(f"Site {site} does not exist in this bench")
    config = json.loads(common_config.read_text()) if common_config.is_file() else {}
    config.update(json.loads(site_config.read_text()))
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="Existing Frappe site hostname")
    parser.add_argument("--apply", action="store_true", help="Create/update the network-wide site user")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,120}", args.site) or ".." in args.site:
        parser.error("Use a lowercase site hostname")
    try:
        config = load_config(args.site)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))

    db_name = config.get("db_name")
    db_user = config.get("db_user") or db_name
    db_password = config.get("db_password")
    db_host = config.get("db_host")
    if config.get("db_type", "mariadb") != "mariadb" or not db_host:
        parser.error("This repair supports a MariaDB site with db_host configured")
    if not all(isinstance(value, str) and value for value in (db_name, db_user, db_password)):
        parser.error("Site config needs db_name, db_user and db_password")
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
        parser.error("Unexpected database name; no changes made")

    import MySQLdb

    root_password = getpass.getpass("MariaDB root password: ")
    try:
        root = MySQLdb.connect(
            host=db_host,
            port=int(config.get("db_port") or 3306),
            user="root",
            passwd=root_password,
            charset="utf8mb4",
        )
        try:
            with root.cursor() as cursor:
                cursor.execute(
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=%s",
                    (db_name,),
                )
                if not cursor.fetchone():
                    raise ValueError(f"Database {db_name} is missing; no changes made")
                cursor.execute("SELECT Host FROM mysql.user WHERE User=%s ORDER BY Host", (db_user,))
                hosts = [row[0] for row in cursor.fetchall()]
                print(f"Site: {args.site}; database: {db_name}; user hosts: {', '.join(hosts) or '(none)'}")
                if not args.apply:
                    print("Inspection only. Rerun with --apply to repair the site user.")
                    return
                cursor.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (db_user, "%", db_password))
                cursor.execute("ALTER USER %s@%s IDENTIFIED BY %s", (db_user, "%", db_password))
                cursor.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO %s@%s", (db_user, "%"))
            root.commit()
        finally:
            root.close()
        site_connection = MySQLdb.connect(
            host=db_host,
            port=int(config.get("db_port") or 3306),
            user=db_user,
            passwd=db_password,
            db=db_name,
        )
        site_connection.close()
        print("Site database login verified. Restart the Frappe container and retry the page.")
    except (MySQLdb.Error, ValueError) as error:
        if isinstance(error, MySQLdb.Error):
            code = error.args[0] if error.args and isinstance(error.args[0], int) else "unknown"
            raise SystemExit(f"MariaDB operation failed (code {code}); no site tables were changed.") from None
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
