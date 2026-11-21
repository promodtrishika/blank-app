"""Deterministic demo data for the RTPS QAP prototype.

Masters follow Bihar's RTPS geography (9 divisions, 38 districts) and the
service catalogue of the Right to Public Services Act. Blocks and offices are
a representative sample per district, not the full official list.
"""

from __future__ import annotations

import random
import sqlite3
import uuid
from datetime import datetime, timedelta

from app.db import hash_password

DEMO_PASSWORD = "Rtps@2026"

DIVISIONS = ["Patna", "Tirhut", "Saran", "Darbhanga", "Kosi", "Purnia",
             "Bhagalpur", "Munger", "Magadh"]

DISTRICTS = {
    "Patna": ["Patna", "Nalanda", "Bhojpur", "Buxar", "Rohtas", "Kaimur"],
    "Tirhut": ["Muzaffarpur", "Sitamarhi", "Sheohar", "Vaishali",
               "East Champaran", "West Champaran"],
    "Saran": ["Saran", "Siwan", "Gopalganj"],
    "Darbhanga": ["Darbhanga", "Madhubani", "Samastipur"],
    "Kosi": ["Saharsa", "Supaul", "Madhepura"],
    "Purnia": ["Purnia", "Katihar", "Araria", "Kishanganj"],
    "Bhagalpur": ["Bhagalpur", "Banka"],
    "Munger": ["Munger", "Jamui", "Khagaria", "Lakhisarai", "Begusarai",
               "Sheikhpura"],
    "Magadh": ["Gaya", "Jehanabad", "Arwal", "Aurangabad", "Nawada"],
}

DEPARTMENTS = ["Revenue & Land Reforms", "General Administration", "Home",
               "Social Welfare", "Health", "Planning & Development"]

SERVICES = [
    ("Income Certificate", "Revenue & Land Reforms", 10),
    ("Residence Certificate", "Revenue & Land Reforms", 10),
    ("Caste Certificate", "Revenue & Land Reforms", 10),
    ("Land Possession Certificate", "Revenue & Land Reforms", 15),
    ("Birth Certificate", "Health", 7),
    ("Death Certificate", "Health", 7),
    ("Character Certificate", "Home", 21),
    ("OBC / EBC Non-Creamy-Layer Certificate", "Social Welfare", 21),
    ("Ration Card Issuance", "Social Welfare", 30),
    ("Marriage Registration", "General Administration", 30),
]

ROLES = [
    ("Super Admin", 1, "state", "Full control of the portal and its configuration"),
    ("State Admin", 2, "state", "State-wide monitoring, final approval and administration"),
    ("Division Admin", 3, "division", "Monitors every district of one division"),
    ("District Admin", 4, "district", "Owns one district's records and district-level approval"),
    ("Reviewer", 5, "district", "First approval level inside a district"),
    ("Verifier", 6, "district", "Runs QAP verification against the checklist"),
    ("Operator", 7, "district", "Enters, submits and corrects applications"),
    ("Read Only", 8, "none", "Views records and reports; changes nothing"),
]

PERMISSIONS = [
    ("app.view", "Application Management", "See applications in scope"),
    ("app.create", "Application Management", "Create a new application"),
    ("app.edit", "Application Management", "Edit an unlocked application"),
    ("app.delete_draft", "Application Management", "Delete a draft"),
    ("app.submit", "Application Management", "Submit for verification"),
    ("app.bulk_upload", "Application Management", "Bulk upload applications"),
    ("verify.perform", "QAP Verification", "Run verification and score"),
    ("correction.raise", "Correction Management", "Raise a correction"),
    ("correction.assign", "Correction Management", "Assign a correction"),
    ("correction.respond", "Correction Management", "Respond and resubmit"),
    ("approve.district_review", "Approval Workflow", "Act at District Reviewer level"),
    ("approve.district_approve", "Approval Workflow", "Act at District Approver level"),
    ("approve.state_review", "Approval Workflow", "Act at State Reviewer level"),
    ("approve.state_approve", "Approval Workflow", "Act at State Approval level"),
    ("lock.apply", "Lock / Unlock", "Lock an approved record"),
    ("unlock.request", "Lock / Unlock", "Request an unlock"),
    ("unlock.approve", "Lock / Unlock", "Approve or reject an unlock request"),
    ("user.manage", "User Management", "Create and edit users in scope"),
    ("role.manage", "User Management", "Change roles and permissions"),
    ("master.manage", "Master Management", "Maintain master data"),
    ("report.view", "Reporting", "Run and export reports"),
    ("audit.view", "Audit Trail", "Read the audit trail"),
    ("analytics.view", "Analytics", "Open the analytics dashboard"),
    ("doc.upload", "Document Management", "Upload documents"),
    ("doc.view", "Document Management", "View and download documents"),
    ("notify.view", "Notification Engine", "Open the notification centre"),
    ("settings.manage", "Settings", "Change portal settings"),
]

ROLE_PERMISSIONS = {
    "Super Admin": [c for c, _, _ in PERMISSIONS],
    "State Admin": [
        "app.view", "approve.state_review", "approve.state_approve",
        "lock.apply", "unlock.approve", "user.manage", "master.manage",
        "report.view", "audit.view", "analytics.view", "doc.view",
        "notify.view", "settings.manage",
    ],
    "Division Admin": [
        "app.view", "user.manage", "report.view", "audit.view",
        "analytics.view", "doc.view", "notify.view",
    ],
    "District Admin": [
        "app.view", "app.create", "app.edit", "approve.district_approve",
        "correction.raise", "correction.assign", "lock.apply",
        "unlock.request", "user.manage", "report.view", "audit.view",
        "analytics.view", "doc.upload", "doc.view", "notify.view",
    ],
    "Reviewer": [
        "app.view", "approve.district_review", "correction.raise",
        "report.view", "analytics.view", "doc.view", "notify.view",
    ],
    "Verifier": [
        "app.view", "verify.perform", "correction.raise", "report.view",
        "doc.view", "notify.view",
    ],
    "Operator": [
        "app.view", "app.create", "app.edit", "app.delete_draft",
        "app.submit", "app.bulk_upload", "correction.respond",
        "doc.upload", "doc.view", "notify.view", "report.view",
    ],
    "Read Only": [
        "app.view", "report.view", "analytics.view", "doc.view", "notify.view",
    ],
}

CHECKLIST = [
    ("QAP-01", "Applicant identity matches the supporting document", 15),
    ("QAP-02", "Service selected matches the request made", 10),
    ("QAP-03", "District, block and office are correctly recorded", 15),
    ("QAP-04", "All mandatory fields are complete and legible", 15),
    ("QAP-05", "Supporting documents attached and readable", 15),
    ("QAP-06", "No duplicate application exists for the applicant", 10),
    ("QAP-07", "Decision recorded within the service SLA", 10),
    ("QAP-08", "Digital signature / counter-signature present", 10),
]

FIRST_NAMES = ["Amit", "Sunita", "Rakesh", "Pooja", "Manoj", "Kiran", "Vijay",
               "Anita", "Ramesh", "Shalini", "Dinesh", "Rekha", "Ashok",
               "Nisha", "Santosh", "Geeta", "Pankaj", "Meena", "Satish",
               "Kavita", "Birendra", "Archana", "Nitish", "Sarita"]
LAST_NAMES = ["Kumar", "Devi", "Singh", "Prasad", "Sharma", "Yadav", "Jha",
              "Mishra", "Verma", "Paswan", "Thakur", "Rai", "Chaudhary",
              "Mahto", "Sahni"]

CORRECTION_REASONS = [
    "Applicant name does not match the supporting document",
    "Supporting document is illegible",
    "Block and office mismatch for the recorded district",
    "Mandatory field left blank in the application form",
    "Duplicate application found for the same applicant and service",
    "Service selected does not match the request made",
    "Attachment missing for the declared annexure",
]

QUALITY = ["Excellent", "Good", "Satisfactory", "Needs Improvement", "Poor"]


def _now_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed_all(conn: sqlite3.Connection) -> None:
    rng = random.Random(20261121)
    now = datetime(2026, 11, 21, 10, 30, 0)
    cur = conn.cursor()

    # --- roles and permissions -----------------------------------------
    for name, level, scope, desc in ROLES:
        cur.execute(
            "INSERT INTO tblRoles(role_name, role_level, scope, description)"
            " VALUES (?,?,?,?)", (name, level, scope, desc))
    for code, module, desc in PERMISSIONS:
        cur.execute(
            "INSERT INTO tblPermissions(permission_code, module, description)"
            " VALUES (?,?,?)", (code, module, desc))
    role_ids = {r["role_name"]: r["role_id"]
                for r in cur.execute("SELECT role_id, role_name FROM tblRoles")}
    perm_ids = {r["permission_code"]: r["permission_id"] for r in
                cur.execute("SELECT permission_id, permission_code FROM tblPermissions")}
    for role, codes in ROLE_PERMISSIONS.items():
        for code in codes:
            cur.execute("INSERT INTO tblRolePermissions(role_id, permission_id)"
                        " VALUES (?,?)", (role_ids[role], perm_ids[code]))

    # --- masters --------------------------------------------------------
    div_ids: dict[str, int] = {}
    for name in DIVISIONS:
        cur.execute("INSERT INTO tblDivisionMaster(division_name) VALUES (?)", (name,))
        div_ids[name] = cur.lastrowid

    dist_ids: dict[str, int] = {}
    dist_division: dict[int, int] = {}
    for division, districts in DISTRICTS.items():
        for d in districts:
            cur.execute("INSERT INTO tblDistrictMaster(district_name, division_id)"
                        " VALUES (?,?)", (d, div_ids[division]))
            dist_ids[d] = cur.lastrowid
            dist_division[cur.lastrowid] = div_ids[division]

    blocks: dict[int, list[int]] = {}
    offices: dict[int, list[int]] = {}
    for d, did in dist_ids.items():
        blocks[did] = []
        for suffix in ("Sadar", "East", "West"):
            cur.execute("INSERT INTO tblBlockMaster(block_name, district_id)"
                        " VALUES (?,?)", (f"{d} {suffix}", did))
            blocks[did].append(cur.lastrowid)
        offices[did] = []
        for label in ("RTPS Counter", "Block Office", "Sub-Divisional Office"):
            cur.execute("INSERT INTO tblOfficeMaster(office_name, district_id)"
                        " VALUES (?,?)", (f"{d} {label}", did))
            offices[did].append(cur.lastrowid)

    dept_ids: dict[str, int] = {}
    for name in DEPARTMENTS:
        cur.execute("INSERT INTO tblDepartmentMaster(department_name) VALUES (?)", (name,))
        dept_ids[name] = cur.lastrowid

    svc: list[tuple[int, str, int, int]] = []
    for name, dept, sla in SERVICES:
        cur.execute("INSERT INTO tblServiceMaster(service_name, department_id, sla_days)"
                    " VALUES (?,?,?)", (name, dept_ids[dept], sla))
        svc.append((cur.lastrowid, name, dept_ids[dept], sla))

    # --- users ----------------------------------------------------------
    def add_user(username, name, role, designation, district=None, division=None):
        salt = uuid.uuid5(uuid.NAMESPACE_DNS, username).hex[:16]
        cur.execute(
            "INSERT INTO tblUsers(username, password_hash, salt, employee_name,"
            " designation, mobile, email, division_id, district_id, status,"
            " last_login, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, hash_password(DEMO_PASSWORD, salt), salt, name, designation,
             f"9{rng.randint(100000000, 999999999)}",
             f"{username}@rtps.bihar.gov.in",
             div_ids.get(division) if division else
             (dist_division.get(dist_ids[district]) if district else None),
             dist_ids.get(district) if district else None,
             "Active", None, _now_iso(now - timedelta(days=330)), "system"))
        uid = cur.lastrowid
        cur.execute("INSERT INTO tblUserRoles(user_id, role_id) VALUES (?,?)",
                    (uid, role_ids[role]))
        return uid

    users: dict[str, int] = {}
    users["superadmin"] = add_user("superadmin", "A. K. Verma", "Super Admin",
                                   "Technical Director, RTPS Cell")
    users["stateadmin"] = add_user("stateadmin", "S. R. Choudhary", "State Admin",
                                   "Joint Secretary, GAD")
    users["divadmin.patna"] = add_user("divadmin.patna", "M. P. Singh", "Division Admin",
                                       "Divisional Commissioner (QAP)", division="Patna")
    users["divadmin.magadh"] = add_user("divadmin.magadh", "R. N. Prasad", "Division Admin",
                                        "Divisional Commissioner (QAP)", division="Magadh")

    operator_by_district: dict[int, int] = {}
    verifier_by_district: dict[int, int] = {}
    reviewer_by_district: dict[int, int] = {}
    admin_by_district: dict[int, int] = {}

    # Every district is staffed, so every record has a complete chain of
    # operator -> verifier -> reviewer -> district approver behind it.
    staffed = list(dist_ids)
    for d in staffed:
        slug = d.lower().replace(" ", "")
        did = dist_ids[d]
        admin_by_district[did] = add_user(
            f"distadmin.{slug}", f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "District Admin", "District Magistrate (QAP)", district=d)
        reviewer_by_district[did] = add_user(
            f"reviewer.{slug}", f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "Reviewer", "Additional Collector", district=d)
        verifier_by_district[did] = add_user(
            f"verifier.{slug}", f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "Verifier", "QAP Verification Officer", district=d)
        operator_by_district[did] = add_user(
            f"operator.{slug}", f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "Operator", "RTPS Counter Operator", district=d)
    users["readonly"] = add_user("readonly", "Audit Observer", "Read Only",
                                 "Audit Observer, Finance Department")

    # --- applications and their history ---------------------------------
    status_mix = (["Approved"] * 150 + ["Locked"] * 90 + ["Rejected"] * 28
                  + ["Correction Required"] * 44 + ["Under Verification"] * 52
                  + ["Submitted"] * 46 + ["Draft"] * 20)
    rng.shuffle(status_mix)
    # Busier districts appear more often, as they do in the real caseload.
    busy = ["Patna", "Gaya", "Muzaffarpur", "Darbhanga", "Bhagalpur",
            "Purnia", "Saran", "Nalanda", "Begusarai", "Rohtas"]
    district_pool = [dist_ids[d] for d in busy] * 4 + list(dist_ids.values())
    levels = ["District Reviewer", "District Approver", "State Reviewer", "State Approval"]
    seq = 0

    for status in status_mix:
        seq += 1
        did = rng.choice(district_pool)
        sid, sname, dept_id, sla = rng.choice(svc)
        created = now - timedelta(days=rng.randint(1, 300),
                                  hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
        applicant = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        number = f"RTPS/{created.year}/{did:02d}/{seq:05d}"
        operator = operator_by_district.get(did) or users["superadmin"]
        verifier = verifier_by_district.get(did)
        reviewer = reviewer_by_district.get(did)
        dist_admin = admin_by_district.get(did)

        submitted = None if status == "Draft" else created + timedelta(hours=rng.randint(1, 30))
        approved_at = None
        score = None
        current_level = None
        if status in ("Approved", "Locked"):
            approved_at = min(submitted + timedelta(days=rng.randint(2, sla + 6)),
                              now - timedelta(hours=rng.randint(30, 60)))
            current_level = "Completed"
        elif status == "Under Verification":
            current_level = rng.choice(levels)
        elif status == "Rejected":
            current_level = rng.choice(levels)

        cur.execute(
            "INSERT INTO tblApplications(application_number, applicant_name,"
            " district_id, subdivision, block_id, office_id, department_id,"
            " service_id, submission_date, status, current_level, score, remarks,"
            " is_locked, created_by, created_at, updated_at, submitted_at, approved_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, applicant, did, f"{rng.choice(['Sadar', 'East', 'West'])} Sub-division",
             rng.choice(blocks[did]), rng.choice(offices[did]), dept_id, sid,
             (submitted or created).strftime("%Y-%m-%d"), status, current_level, score,
             None, 1 if status == "Locked" else 0, operator,
             _now_iso(created), _now_iso(submitted or created),
             _now_iso(submitted) if submitted else None,
             _now_iso(approved_at) if approved_at else None))
        app_id = cur.lastrowid

        for field, value in (("Aadhaar reference", f"XXXX-XXXX-{rng.randint(1000, 9999)}"),
                             ("Mobile", f"9{rng.randint(100000000, 999999999)}"),
                             ("Mode of application", rng.choice(["RTPS Counter", "Online", "Common Service Centre"]))):
            cur.execute("INSERT INTO tblApplicationDetails(application_id, field_name, field_value)"
                        " VALUES (?,?,?)", (app_id, field, value))

        # documents
        for i, (fn, ft) in enumerate(rng.sample(
                [("application_form.pdf", "PDF"), ("aadhaar_proof.pdf", "PDF"),
                 ("photograph.jpg", "JPG"), ("declaration.docx", "DOCX"),
                 ("income_statement.xlsx", "XLSX"), ("ward_slip.png", "PNG")],
                k=rng.randint(1, 3))):
            cur.execute(
                "INSERT INTO tblDocuments(application_id, file_name, file_type,"
                " file_size, version, uploaded_by, upload_time, verified, content)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (app_id, fn, ft, rng.randint(48, 2400) * 1024, 1, operator,
                 _now_iso((submitted or created) + timedelta(minutes=5 + i)),
                 1 if status in ("Approved", "Locked") else 0, None))

        # verification
        if status not in ("Draft", "Submitted") and verifier:
            result = "Fail" if status == "Correction Required" else "Pass"
            verified_at = submitted + timedelta(days=rng.randint(1, 4))
            total = 0
            marks = []
            for code, text, weight in CHECKLIST:
                if result == "Fail" and code in ("QAP-01", "QAP-05") and rng.random() < 0.7:
                    item = "Fail"
                else:
                    item = "Pass" if rng.random() < 0.93 else "Fail"
                if item == "Pass":
                    total += weight
                marks.append((code, text, weight, item))
            cur.execute(
                "INSERT INTO tblVerification(application_id, verifier_id, score,"
                " result, quality_assessment, recommendation, remarks, verified_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (app_id, verifier, float(total), result,
                 QUALITY[0] if total >= 90 else QUALITY[1] if total >= 75
                 else QUALITY[2] if total >= 60 else QUALITY[3],
                 "Forward for approval" if result == "Pass" else "Return for correction",
                 "Checklist applied against the QAP standard.", _now_iso(verified_at)))
            vid = cur.lastrowid
            for code, text, weight, item in marks:
                cur.execute(
                    "INSERT INTO tblVerificationChecklist(verification_id, item_code,"
                    " item_text, weight, result, comment) VALUES (?,?,?,?,?,?)",
                    (vid, code, text, weight, item,
                     None if item == "Pass" else "Evidence insufficient"))
            cur.execute("UPDATE tblApplications SET score=? WHERE application_id=?",
                        (float(total), app_id))

        # an earlier, resolved correction on some records that went on to pass
        if status in ("Approved", "Locked", "Rejected") and rng.random() < 0.22:
            raised = submitted + timedelta(days=rng.randint(1, 3))
            answered = raised + timedelta(days=rng.randint(1, 6), hours=rng.randint(0, 20))
            closed = answered + timedelta(hours=rng.randint(2, 30))
            cur.execute(
                "INSERT INTO tblCorrections(application_id, raised_by, assigned_to,"
                " reason, comments, status, raised_at, responded_at, closed_at,"
                " closure_remarks) VALUES (?,?,?,?,?, 'Closed', ?,?,?,?)",
                (app_id, verifier, operator, rng.choice(CORRECTION_REASONS),
                 "Corrected document attached and resubmitted.",
                 _now_iso(raised), _now_iso(answered), _now_iso(closed),
                 "Re-verified; the correction holds."))
            cid = cur.lastrowid
            for action, actor, at in (("Raised", verifier, raised),
                                      ("Responded", operator, answered),
                                      ("Closed", verifier, closed)):
                cur.execute("INSERT INTO tblCorrectionHistory(correction_id, action,"
                            " actor_id, comments, action_at) VALUES (?,?,?,?,?)",
                            (cid, action, actor, None, _now_iso(at)))

        # corrections
        if status == "Correction Required":
            raised = submitted + timedelta(days=rng.randint(1, 5))
            cur.execute(
                "INSERT INTO tblCorrections(application_id, raised_by, assigned_to,"
                " reason, comments, status, raised_at) VALUES (?,?,?,?,?,?,?)",
                (app_id, verifier or users["superadmin"], operator,
                 rng.choice(CORRECTION_REASONS),
                 "Attach the corrected document and resubmit.",
                 rng.choice(["Open", "Assigned"]), _now_iso(raised)))
            cid = cur.lastrowid
            cur.execute("INSERT INTO tblCorrectionHistory(correction_id, action,"
                        " actor_id, comments, action_at) VALUES (?,?,?,?,?)",
                        (cid, "Raised", verifier or users["superadmin"],
                         "Verification failed the checklist.", _now_iso(raised)))

        # approvals
        if status in ("Approved", "Locked", "Rejected", "Under Verification"):
            actors = {"District Reviewer": reviewer, "District Approver": dist_admin,
                      "State Reviewer": users["stateadmin"],
                      "State Approval": users["stateadmin"]}
            reached = (levels if status in ("Approved", "Locked")
                       else levels[:levels.index(current_level) + 1])
            stamp = (approved_at or (submitted + timedelta(days=rng.randint(2, 10))))
            for i, level in enumerate(reached):
                last = (i == len(reached) - 1)
                if status in ("Approved", "Locked"):
                    decision = "Approved"
                elif status == "Rejected" and last:
                    decision = "Rejected"
                elif last:
                    decision = "Pending"
                else:
                    decision = "Approved"
                at = stamp - timedelta(days=(len(reached) - i - 1) * rng.randint(1, 3))
                if decision != "Pending":
                    cur.execute(
                        "INSERT INTO tblApprovalHistory(application_id, level,"
                        " approver_id, decision, remarks, action_at) VALUES (?,?,?,?,?,?)",
                        (app_id, level, actors.get(level), decision,
                         "Checked against the QAP verification result.", _now_iso(at)))
                cur.execute(
                    "INSERT INTO tblApproval(application_id, current_level, approver_id,"
                    " decision, remarks, approval_date) VALUES (?,?,?,?,?,?)",
                    (app_id, level, actors.get(level), decision,
                     None if decision == "Pending" else "Recorded.",
                     None if decision == "Pending" else _now_iso(at)))

        # lock / unlock
        if status == "Locked":
            lock_date = min(approved_at + timedelta(days=1), now - timedelta(hours=6))
            unlock_status = None
            unlock_req_at = None
            unlock_reason = None
            if rng.random() < 0.3:
                unlock_status = rng.choice(["Requested", "Approved", "Rejected"])
                unlock_req_at = min(lock_date + timedelta(days=rng.randint(1, 20)),
                                    now - timedelta(hours=3))
                unlock_reason = rng.choice([
                    "Applicant name spelling to be corrected after court order",
                    "Service category wrongly recorded at the counter",
                    "Certificate re-issue requested by the sub-divisional office",
                ])
            cur.execute(
                "INSERT INTO tblLockUnlock(application_id, lock_date, locked_by,"
                " unlock_reason, unlock_requested_by, unlock_requested_at,"
                " unlock_status, unlock_approved_by, unlock_date, relock_date)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (app_id, _now_iso(lock_date), dist_admin or users["stateadmin"],
                 unlock_reason, dist_admin if unlock_status else None,
                 _now_iso(unlock_req_at) if unlock_req_at else None, unlock_status,
                 users["stateadmin"] if unlock_status == "Approved" else None,
                 _now_iso(unlock_req_at + timedelta(days=1))
                 if unlock_status == "Approved" else None, None))

        # notifications for the recent, still-moving records
        if status in ("Correction Required", "Under Verification") and rng.random() < 0.35:
            cur.execute(
                "INSERT INTO tblNotifications(user_id, application_id, event, message,"
                " channel, type, status, sent_time, read_flag) VALUES (?,?,?,?,?,?,?,?,?)",
                (operator, app_id,
                 "Correction Raised" if status == "Correction Required" else "New Submission",
                 f"{number}: "
                 + ("a correction has been raised against this application."
                    if status == "Correction Required"
                    else "the application has moved into the approval chain."),
                 rng.choice(["In-App", "Email", "SMS"]),
                 "Action" if status == "Correction Required" else "Info",
                 "Sent", _now_iso((submitted or created) + timedelta(days=1)),
                 1 if rng.random() < 0.5 else 0))

    # --- a readable slice of audit history ------------------------------
    sample = cur.execute(
        "SELECT application_id, application_number, status, created_by, created_at"
        " FROM tblApplications ORDER BY created_at DESC LIMIT 120").fetchall()
    names = {r["user_id"]: r["username"] for r in
             cur.execute("SELECT user_id, username FROM tblUsers")}
    for r in sample:
        for activity, module in (("Submission", "Application Management"),
                                 ("Verification", "QAP Verification"),
                                 ("Approval", "Approval Workflow")):
            if activity == "Verification" and r["status"] in ("Draft", "Submitted"):
                continue
            if activity == "Approval" and r["status"] in ("Draft", "Submitted",
                                                          "Correction Required"):
                continue
            cur.execute(
                "INSERT INTO tblAuditLogs(user_id, username, activity, module, entity,"
                " entity_id, old_value, new_value, ip_address, browser, timestamp)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r["created_by"], names.get(r["created_by"], "system"), activity,
                 module, "tblApplications", r["application_number"], None, r["status"],
                 f"10.{rng.randint(1, 40)}.{rng.randint(1, 250)}.{rng.randint(2, 250)}",
                 rng.choice(["Chrome 141", "Edge 141", "Firefox 139"]),
                 r["created_at"]))
    for uname in ("superadmin", "stateadmin", "readonly"):
        uid = cur.execute("SELECT user_id FROM tblUsers WHERE username=?",
                          (uname,)).fetchone()["user_id"]
        cur.execute(
            "INSERT INTO tblAuditLogs(user_id, username, activity, module, entity,"
            " entity_id, old_value, new_value, ip_address, browser, timestamp)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (uid, uname, "Login", "Login & Security", "tblUsers", uname, None,
             "Success", "10.2.14.9", "Chrome 141",
             _now_iso(now - timedelta(days=1, hours=2))))

    conn.commit()
