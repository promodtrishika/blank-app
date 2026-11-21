# RTPS QAP Portal — Implementation map

How the prototype in this repository realises [BLUEPRINT.md](BLUEPRINT.md), and
every place it departs from it. The prototype runs the whole workflow end to
end; the departures are all about the production stack and live integrations.

## Stack: prototype vs blueprint

| Layer | Blueprint | This prototype | Moving to production |
|---|---|---|---|
| Frontend | React / Angular | Streamlit (Python) | Screens and flows carry over one-for-one; `app/navigation.py` is the route + permission table |
| API | .NET Core, 11 APIs | Python modules called in-process | `app/workflow.py`, `app/auth.py`, `app/audit.py`, `app/notify.py` are the service layer to port; each public function is one API operation |
| Database | SQL Server | SQLite, same table names and columns — or **SharePoint lists** as the system of record (`app/sharepoint/`, [SHAREPOINT.md](SHAREPOINT.md)) | `app/db.py` `SCHEMA` is the DDL reference; types map directly (`TEXT`→`NVARCHAR`, `REAL`→`DECIMAL`, `BLOB`→`VARBINARY(MAX)`) |
| Identity | Azure AD SSO + MFA + JWT | **Microsoft 365 / Entra ID sign-in** (OpenID Connect) mapped to portal users by email; local passwords only in local mode | Same Entra ID registration; keep the role → permission → scope model |
| Email / SMS | Live delivery | Recorded in `tblNotifications` with a channel, not sent | Put a sender behind `notify.send` |
| Power BI | Integration | Not connected | Every report exports CSV/Excel, and the schema is ready for a Power BI dataset |
| File storage | File storage service | SharePoint mode: the **RTPS Documents** library, a folder per application, SharePoint version history; local mode: BLOBs in `tblDocuments` | Already a storage reference (`sp_item_id`, `sp_version_id`, `web_url`) |

## Modules

| # | Blueprint module | Screen(s) | Code |
|---|---|---|---|
| 1 | Login & Security | Login (entry point), Settings | `streamlit_app.py`, `app/auth.py`, `app/views/settings.py` |
| 2 | Dashboard | Dashboard | `app/views/dashboard.py` |
| 3 | Application Management | Application Entry, Submission List, Application Details | `app/views/application_entry.py`, `submissions.py`, `application_details.py` |
| 4 | QAP Verification | QAP Verification | `app/views/verification.py`, `workflow.record_verification` |
| 5 | Correction Management | Corrections | `app/views/corrections.py`, `workflow.raise_/respond_/close_correction` |
| 6 | Approval Workflow | Approvals | `app/views/approvals.py`, `workflow.decide` |
| 7 | Lock / Unlock | Lock / Unlock | `app/views/lock_unlock.py`, `workflow.lock / request_unlock / decide_unlock / relock` |
| 8 | User Management | User Management, Role Management | `app/views/users.py`, `roles.py` |
| 9 | Master Management | Master Management | `app/views/masters.py` |
| 10 | Reporting | Reports | `app/views/reports.py` — all nine reports, PDF / Excel / CSV |
| 11 | Audit Trail | Audit Log | `app/audit.py` (the one helper every write calls), `app/views/audit_log.py` |
| 12 | Notification Engine | Notification Centre | `app/notify.py`, `app/views/notifications.py` |
| 13 | Document Management | Document Repository | `app/views/documents.py` — upload, view, download, versions, attachment check |
| 14 | Analytics | Analytics | `app/views/analytics.py` |

All 18 screens of the inventory exist; screen 01 is the login gate in
`streamlit_app.py`.

## Decisions the blueprint left open

- **Verification → approval.** A pass moves the record to *Under Verification*
  at the first approval level (District Reviewer); a fail raises a correction
  assigned to the operator who filed it. An answered correction returns as
  *Under Verification* with no level, which puts it back in the verifier's queue.
- **Approval actions.** *Approve* moves to the next level (the last one sets
  *Approved*); *Reject* ends it; *Send Back* raises a correction; *Hold* keeps
  it at the level with the reason recorded; *Escalate* skips one level. Anything
  but Approve needs a remark.
- **Scoring.** Eight weighted checklist items (weights total 100). The score is
  the weight of the items that pass; any failed item fails the verification.
- **District / Division performance %.** The share of decided records disposed
  within the service's SLA. RTPS is a timeliness law, and approval rate alone
  barely separates districts.
- **Data scope.** State roles and Read Only see every district; Division Admin
  sees its division; District Admin, Reviewer, Verifier and Operator see their
  district. User Management never lets you create or edit a role above your own.

## SharePoint mode

When `[sharepoint]` is configured, each of the 24 tables is a SharePoint list
and the SQLite file becomes a cache the portal rebuilds from SharePoint.
Triggers queue every write; the queue is sent through Graph `$batch` at the end
of each page; delta queries bring back changes made in SharePoint itself. The
design, its limits (one portal instance per site; direct list edits bypass the
workflow) and the setup steps are in [SHAREPOINT.md](SHAREPOINT.md).

## Additions to the blueprint's table list

- `tblRolePermissions` — the join between roles and permissions the RBAC needs.
- `tblSettings` — portal settings (session timeout, MFA switch, channels,
  QAP pass score, SLA warning).

## Not done in this prototype

- Live email, SMS, WhatsApp and Power BI integrations (above). Microsoft 365
  sign-in and SharePoint storage are built, and tested against a fake Graph and
  a fake OpenID provider; they have not yet run against a real tenant.
- Device tracking beyond the IP address and browser recorded in the audit trail.
- Encryption at rest and disaster recovery: infrastructure concerns for the
  production SQL Server, not the app.
- Phase 2 items (mobile app, OCR, AI validation, predictive analytics).

## Demo data

`app/seed.py` builds a deterministic dataset on first run: Bihar's 9 divisions
and 38 districts, 10 RTPS services across 6 departments, 157 users (every
district staffed with an operator, verifier, reviewer and district admin),
430 applications in every status, with their verification, correction,
approval, lock, document, notification and audit history. Blocks and offices
are a representative sample per district, not the official list. Delete
`rtps_qap.db` to start fresh.
