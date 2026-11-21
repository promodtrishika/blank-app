"""Set up the SharePoint site for the portal.

    uv run python -m app.sharepoint.provision
        Create the lists and libraries, and load the reference data (roles,
        permissions, divisions, districts, blocks, offices, departments,
        services) if the site has none.

    uv run python -m app.sharepoint.provision --migrate rtps_qap.db
        Also copy every record of an existing portal database into SharePoint.

    uv run python -m app.sharepoint.provision --seed-demo
        Also load the demo data set (157 users, 430 applications).

The connection is read from .streamlit/secrets.toml [sharepoint], or from
RTPS_SP_* environment variables (see docs/SHAREPOINT.md). Run it once, from
the project root; running it again only adds what is missing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from app.db import DEFAULT_SETTINGS, SCHEMA
from app.seed import seed_all
from app.sharepoint import config as sp_config
from app.sharepoint.graph import GraphClient, GraphError
from app.sharepoint.store import SharePointStore

REFERENCE_TABLES = [
    "tblRoles", "tblPermissions", "tblRolePermissions", "tblDivisionMaster",
    "tblDistrictMaster", "tblBlockMaster", "tblOfficeMaster",
    "tblDepartmentMaster", "tblServiceMaster", "tblSettings",
]


def demo_database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    seed_all(conn)
    conn.executemany("INSERT OR IGNORE INTO tblSettings(setting_key, setting_value, label)"
                     " VALUES (?,?,?)", DEFAULT_SETTINGS)
    conn.commit()
    return conn


def run(argv: list[str] | None = None, session=None, sleep=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--migrate", metavar="DATABASE",
                       help="copy every record of this portal database into SharePoint")
    group.add_argument("--seed-demo", action="store_true", help="load the demo data set")
    ap.add_argument("--force", action="store_true",
                    help="copy even into lists that already hold items (duplicates them)")
    args = ap.parse_args(argv)

    cfg = sp_config.load()
    if cfg is None:
        print("SharePoint is not enabled. Fill in [sharepoint] in .streamlit/secrets.toml "
              "with enabled = true, or set RTPS_SP_ENABLED=1 and the RTPS_SP_* variables.")
        return 2
    kwargs = {"session": session} if session else {}
    if sleep:
        kwargs["sleep"] = sleep
    client = GraphClient(cfg, **kwargs)
    store = SharePointStore(sqlite3.connect(":memory:"), client, cfg, SCHEMA)
    try:
        print(f"Site: {cfg.site_url}")
        client.site_id()
        made = store.provision()
        print("Created: " + (", ".join(made) if made else "nothing — everything was there"))

        if args.migrate:
            source = sqlite3.connect(args.migrate)
            source.row_factory = sqlite3.Row
            print(f"Copying {args.migrate} into SharePoint:")
            total = store.migrate_from(source, force=args.force)
            print(f"Copied {total:,} records.")
        elif args.seed_demo:
            print("Loading the demo data:")
            total = store.migrate_from(demo_database(), force=args.force)
            print(f"Loaded {total:,} records. Demo users sign in with Microsoft 365 "
                  "only if their email matches a real account; add your own in "
                  "User Management.")
        else:
            roles = client.get(f"{store._items_path('tblRoles')}",
                               params={"$top": "1", "$select": "id"})
            if roles.get("value"):
                print("Reference data: already there.")
            else:
                print("Loading the reference data:")
                total = store.migrate_from(demo_database(), tables=REFERENCE_TABLES)
                print(f"Loaded {total:,} records.")
        print("\nDone. Start the portal with: uv run streamlit run streamlit_app.py")
        if cfg.bootstrap_admin_email:
            print(f"Sign in first as {cfg.bootstrap_admin_email}: that account becomes "
                  "the Super Admin.")
        return 0
    except (GraphError, RuntimeError) as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        if isinstance(exc, GraphError) and exc.status in (401, 403):
            print("Check the app registration's client secret and that it has been "
                  "granted access to this site (docs/SHAREPOINT.md, step 2).",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
