# RTPS QAP Portal

A working prototype of the **Quality Assurance Portal for Right to Public
Services**: application entry, QAP verification against a weighted checklist,
corrections, a four-level approval chain, lock/unlock, reports, audit trail,
notifications, documents and analytics. All 18 screens of the
[blueprint](docs/BLUEPRINT.md) are here, behind role-based access for 8 roles.

## Run it

Prerequisite: [`uv`](https://docs.astral.sh/uv/).

```
uv sync
uv run streamlit run streamlit_app.py
```

The first run creates `rtps_qap.db` and fills it with demo data. Delete the file
to start again.

## Sign in

Every demo account uses the password `Rtps@2026`. The one-time passcode is
stubbed: any six digits.

| Username | Role | What it can do |
|---|---|---|
| `superadmin` | Super Admin | Everything, every district |
| `stateadmin` | State Admin | State review and final approval, unlock approval, masters, settings |
| `divadmin.patna` | Division Admin | Monitors the Patna division |
| `distadmin.patna` | District Admin | District approval, lock, unlock request, corrections |
| `reviewer.patna` | Reviewer | District Reviewer approval level |
| `verifier.patna` | Verifier | QAP verification, raising corrections |
| `operator.patna` | Operator | Entry, submission, bulk upload, correction response |
| `readonly` | Read Only | Views records and reports |

Swap `patna` for any district in lower case (`verifier.gaya`,
`operator.eastchamparan`) to work in another district.

**A full pass through the workflow:** create and submit as `operator.patna` →
verify as `verifier.patna` → approve as `reviewer.patna`, then
`distadmin.patna`, then twice as `stateadmin` → lock as `distadmin.patna`.

## Test

```
uv run pytest
```

Every screen is rendered as every role that can open it, plus the login,
permission gate and the workflow end to end.

## Layout

```
streamlit_app.py      Login gate (screen 01) and navigation
app/navigation.py     Screen inventory with the permissions that open each one
app/views/            The 17 other screens
app/workflow.py       The status machine: verification, corrections, approvals, locks
app/auth.py           Sign-in, permissions, data scope
app/audit.py          The one audit helper every write calls
app/notify.py         Notification events
app/db.py, seed.py    SQLite schema (mirrors the blueprint's tables) and demo data
app/ui.py, charts.py  Shared page pieces and charts
app/theme.py          Every colour, spacing step and status badge, in one place
docs/                 The blueprint and how this prototype maps to it
```

The production stack in the blueprint is .NET Core with SQL Server and Azure AD;
[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) says what carries over and what
the prototype stubs.
