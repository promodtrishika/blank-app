# RTPS QAP Portal — Blueprint

**Project:** RTPS QAP (Quality Assurance Portal)

**Purpose:** A centralized web-based platform for application monitoring, quality
assurance verification, correction management, approval workflow, lock/unlock
operations, reporting, dashboards, audit tracking, and administration.

This is the specification the prototype in this repository is built against.
How each part maps to code, and where the prototype departs from it, is in
[IMPLEMENTATION.md](IMPLEMENTATION.md).

---

## 1. System architecture

```
Users
├── Super Admin
├── State Admin
├── Division Admin
├── District Admin
├── Reviewer
├── Verifier
├── Operator
└── Read Only User
        │
        ▼
Frontend Layer — React / Angular · responsive UI · dashboards · forms · reports
        │
        ▼
Application Layer (.NET Core APIs)
  Authentication · User Management · Dashboard · Submission · Verification ·
  Approval · Correction · Lock Unlock · Report · Notification · Audit
        │
        ▼
Database Layer (SQL Server)
  Users · Roles · Permissions · Applications · Approvals · Corrections ·
  Verification · LockUnlock · AuditLogs · Notifications · Master tables
        │
        ▼
Integration Services — Email · SMS · Power BI · Azure AD · File Storage
```

## 2. User hierarchy

```
Super Admin
├── State Admin
├── Division Admin
│     └── District Admin
│           ├── Reviewer
│           ├── Verifier
│           └── Operator
└── Read Only User
```

## 3. Modules

### Module 1 — Login & Security
**Features:** Login · Logout · Azure AD SSO · MFA · Password Reset · Role Mapping ·
Session Timeout · Device Tracking
**Fields:** Username · Password · OTP · Role · Last Login

### Module 2 — Dashboard
**Widgets:** Total Records · Total Submissions · Pending Verifications ·
Corrections Pending · Approved Records · Rejected Records · Locked Records ·
Unlock Requests
**Charts:** Monthly Trend · District Performance · Division Performance ·
Service Performance · Approval Trend
**Filters:** Date · District · Division · Service

### Module 3 — Application Management
**Features:** New Entry · Edit Entry · Delete Draft · Save Draft · Final Submission ·
Bulk Upload · Document Attachment · Submission History
**Fields:** Application ID · Application Number · District · Subdivision · Block ·
Office · Department · Service Name · Submission Date · Status · Remarks · Attachment
**Status:** Draft · Submitted · Under Verification · Correction Required ·
Approved · Rejected · Locked

### Module 4 — QAP Verification
```
Submitted → Verification ─┬─ Pass → Approve
                          └─ Fail → Correction
```
**Features:** Verification Checklist · Validation Rules · Scoring System · Remarks ·
Quality Assessment · Recommendations
**Fields:** Verification ID · Application ID · Verifier · Score · Checklist Result ·
Remarks · Date

### Module 5 — Correction Management
```
Submission → Correction Raised → Correction Done → Reverification → Approval
```
**Features:** Raise Correction · Assign Correction · Respond to Correction ·
Resubmit · Correction History · Closure Remarks
**Fields:** Correction ID · Application ID · Raised By · Assigned To · Reason ·
Comments · Status · Date

### Module 6 — Approval Workflow
```
Operator → District Reviewer → District Approver → State Reviewer → State Approval
```
**Actions:** Approve · Reject · Send Back · Hold · Escalate
**Fields:** Approval ID · Application ID · Current Level · Approver · Decision ·
Remarks · Approval Date

### Module 7 — Lock / Unlock Management
```
Approved Record → Lock → Unlock Request → Approval → Unlock → Edit → Relock
```
**Features:** Lock Record · Unlock Request · Unlock Approval · Lock History ·
Unlock History
**Fields:** Lock ID · Application ID · Lock Date · Locked By · Unlock Reason ·
Unlock Date · Approved By

### Module 8 — User Management
**Functions:** User Creation · User Edit · Role Assignment · User Disable ·
Password Reset · User Mapping
**Fields:** User ID · Employee Name · Designation · Mobile · Email · Division ·
District · Role · Status
**Roles:** Super Admin · State Admin · Division Admin · District Admin · Reviewer ·
Verifier · Operator · Read Only

### Module 9 — Master Management
| Master | Fields |
|---|---|
| District | District ID · District Name · Status |
| Division | Division ID · Division Name |
| Block | Block ID · Block Name · District ID |
| Service | Service ID · Service Name · Department |
| Office | Office ID · Office Name · District |
| Department | Department ID · Department Name |

### Module 10 — Reporting
**Reports:** Submission · Verification · Correction · User Activity · Lock ·
Unlock · Pending · Approval · Audit
**Export:** PDF · Excel · CSV
**Filters:** Date Range · District · Division · Department · Service

### Module 11 — Audit Trail
**Track every action:** Login · Logout · Submission · Update · Delete ·
Verification · Correction · Approval · Lock · Unlock · User Creation ·
User Modification
**Audit table:** Audit ID · User ID · Activity · Old Value · New Value ·
IP Address · Browser · Timestamp

### Module 12 — Notification Engine
**Channels:** Email · SMS · In-App
**Events:** New Submission · Correction Raised · Correction Assigned ·
Approval Completed · Application Rejected · Lock Applied · Unlock Approved
**Fields:** Notification ID · User ID · Message · Type · Status · Sent Time

### Module 13 — Document Management
**Features:** Upload · View · Download · Version Control · Attachment Verification
**Formats:** PDF · DOCX · XLSX · JPG · PNG
**Fields:** Document ID · Application ID · File Name · File Type · Uploaded By ·
Upload Time

### Module 14 — Analytics
**Performance analytics:** District Ranking · Division Ranking · Service Ranking
**KPIs:** Average Approval Time · Average Correction Time · Submission Trend ·
Approval Rate · Rejection Rate · Pending Rate

## 4. Database tables

tblUsers · tblRoles · tblPermissions · tblUserRoles · tblApplications ·
tblApplicationDetails · tblVerification · tblVerificationChecklist ·
tblCorrections · tblCorrectionHistory · tblApproval · tblApprovalHistory ·
tblLockUnlock · tblAuditLogs · tblNotifications · tblDistrictMaster ·
tblDivisionMaster · tblBlockMaster · tblOfficeMaster · tblServiceMaster ·
tblDepartmentMaster · tblDocuments

## 5. Dashboard KPIs

Total Applications · Submitted Today · Pending Verification · Pending Approval ·
Pending Corrections · Approved Applications · Rejected Applications ·
Locked Applications · Unlock Requests · District Performance % ·
Division Performance % · Average Processing Time

## 6. Security framework

**Authentication:** Azure AD · SSO · MFA · JWT
**Authorization:** Role Based Access Control
**Security controls:** HTTPS · Encryption · Audit Logging · Password Policy ·
Session Timeout · Data Backup · Disaster Recovery

## 7. Future enhancements (Phase 2)

Mobile Application · Power BI Integration · WhatsApp Notifications ·
OCR Verification · AI Based Validation · AI Assistant · Predictive Analytics ·
District Ranking Engine · Smart Workflow Recommendations

## 8. Screen inventory

| # | Screen | # | Screen |
|---|---|---|---|
| 01 | Login | 10 | Approval |
| 02 | Dashboard | 11 | Lock Unlock |
| 03 | User Management | 12 | Reports |
| 04 | Role Management | 13 | Audit Log |
| 05 | Application Entry | 14 | Notification Center |
| 06 | Submission List | 15 | Master Management |
| 07 | Application Details | 16 | Settings |
| 08 | Verification | 17 | Document Repository |
| 09 | Correction | 18 | Analytics Dashboard |
