"""The screen inventory: every page, its icon, its group, and the permission
codes that may open it. The entry point builds navigation from this list and
the tests walk it, so a screen cannot exist without an access rule.
"""

from __future__ import annotations

PAGES = [
    # (path, title, icon, permission codes that may open it, group)
    ("app/views/dashboard.py", "Dashboard", ":material/space_dashboard:",
     ("app.view",), "Monitoring"),
    ("app/views/analytics.py", "Analytics", ":material/insights:",
     ("analytics.view",), "Monitoring"),
    ("app/views/application_entry.py", "Application Entry", ":material/note_add:",
     ("app.create",), "Applications"),
    ("app/views/submissions.py", "Submission List", ":material/list_alt:",
     ("app.view",), "Applications"),
    ("app/views/application_details.py", "Application Details",
     ":material/description:", ("app.view",), "Applications"),
    ("app/views/documents.py", "Document Repository", ":material/folder_open:",
     ("doc.view",), "Applications"),
    ("app/views/verification.py", "QAP Verification", ":material/fact_check:",
     ("verify.perform",), "Quality assurance"),
    ("app/views/corrections.py", "Corrections", ":material/build:",
     ("correction.raise", "correction.respond", "correction.assign"),
     "Quality assurance"),
    ("app/views/approvals.py", "Approvals", ":material/approval:",
     ("approve.district_review", "approve.district_approve",
      "approve.state_review", "approve.state_approve"), "Quality assurance"),
    ("app/views/lock_unlock.py", "Lock / Unlock", ":material/lock:",
     ("lock.apply", "unlock.request", "unlock.approve"), "Quality assurance"),
    ("app/views/reports.py", "Reports", ":material/summarize:",
     ("report.view",), "Records"),
    ("app/views/audit_log.py", "Audit Log", ":material/history:",
     ("audit.view",), "Records"),
    ("app/views/notifications.py", "Notification Centre",
     ":material/notifications:", ("notify.view",), "Records"),
    ("app/views/users.py", "User Management", ":material/group:",
     ("user.manage",), "Administration"),
    ("app/views/roles.py", "Role Management", ":material/admin_panel_settings:",
     ("role.manage",), "Administration"),
    ("app/views/masters.py", "Master Management", ":material/database:",
     ("master.manage",), "Administration"),
    ("app/views/settings.py", "Settings", ":material/settings:",
     ("settings.manage",), "Administration"),
]
