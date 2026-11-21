"""Screen 05 — Application Entry (blueprint module 3)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from app import audit, auth, db, ui, workflow

user = auth.require("app.create")

ui.page_header("Application Entry",
               "Create a draft, submit it for verification, or upload a batch.",
               ":material/note_add:")

districts = auth.districts_in_scope()
if not districts:
    ui.empty_state("Your account is not mapped to a district, so there is nowhere "
                   "to file an application. Ask an administrator to map it.",
                   ":material/person_off:")
    st.stop()

single, bulk, drafts = st.tabs(["New entry", "Bulk upload", "My drafts"])

with single:
    district_labels = {d["district_name"]: d["district_id"] for d in districts}
    services = {r["service_name"]: (r["service_id"], r["department_id"],
                                    r["sla_days"]) for r in db.query(
        "SELECT service_id, service_name, department_id, sla_days"
        "  FROM tblServiceMaster WHERE status = 'Active' ORDER BY service_name")}

    with st.form("new_application", border=True):
        st.subheader("Applicant and service", anchor=False)
        row1 = st.columns(3)
        with row1[0]:
            applicant = st.text_input("Applicant name *")
        with row1[1]:
            district_name = st.selectbox("District *", list(district_labels))
        with row1[2]:
            service_name = st.selectbox("Service *", list(services))

        did = district_labels[district_name]
        blocks = {r["block_name"]: r["block_id"] for r in db.query(
            "SELECT block_id, block_name FROM tblBlockMaster"
            " WHERE district_id = ? AND status = 'Active' ORDER BY block_name",
            (did,))}
        offices = {r["office_name"]: r["office_id"] for r in db.query(
            "SELECT office_id, office_name FROM tblOfficeMaster"
            " WHERE district_id = ? AND status = 'Active' ORDER BY office_name",
            (did,))}

        row2 = st.columns(3)
        with row2[0]:
            subdivision = st.selectbox("Sub-division",
                                       ["Sadar Sub-division", "East Sub-division",
                                        "West Sub-division"])
        with row2[1]:
            block_name = st.selectbox("Block", list(blocks) or ["—"])
        with row2[2]:
            office_name = st.selectbox("Office", list(offices) or ["—"])

        row3 = st.columns(3)
        with row3[0]:
            mobile = st.text_input("Mobile", max_chars=10,
                                   help="Ten digits, no country code.")
        with row3[1]:
            aadhaar_ref = st.text_input("Aadhaar reference",
                                        placeholder="XXXX-XXXX-1234")
        with row3[2]:
            mode = st.selectbox("Mode of application",
                                ["RTPS Counter", "Online", "Common Service Centre"])
        remarks = st.text_area("Remarks", height=80)
        attachments = st.file_uploader(
            "Attachments", type=["pdf", "docx", "xlsx", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            help="PDF, DOCX, XLSX, JPG or PNG, as the blueprint allows.")

        actions = st.columns(2)
        with actions[0]:
            save_draft = st.form_submit_button(
                "Save draft", icon=":material/save:", width="stretch")
        with actions[1]:
            submit_now = st.form_submit_button(
                "Save and submit", type="primary", icon=":material/send:",
                width="stretch", disabled=not auth.has("app.submit"))

    if save_draft or submit_now:
        problems = []
        if not applicant.strip():
            problems.append("Applicant name is required.")
        if mobile and (len(mobile) != 10 or not mobile.isdigit()):
            problems.append("A mobile number is ten digits.")
        if problems:
            for p in problems:
                st.error(p, icon=":material/error:")
        else:
            sid, dept_id, sla = services[service_name]
            seq = db.scalar("SELECT COUNT(*) FROM tblApplications") + 1
            number = f"RTPS/{pd.Timestamp.now().year}/{did:02d}/{seq:05d}"
            app_id = db.execute(
                "INSERT INTO tblApplications(application_number, applicant_name,"
                " district_id, subdivision, block_id, office_id, department_id,"
                " service_id, submission_date, status, remarks, created_by,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?, date('now'),"
                " 'Draft', ?, ?, datetime('now'), datetime('now'))",
                (number, applicant.strip(), did, subdivision,
                 blocks.get(block_name), offices.get(office_name), dept_id, sid,
                 remarks or None, user["user_id"]))
            for field, value in (("Aadhaar reference", aadhaar_ref),
                                 ("Mobile", mobile),
                                 ("Mode of application", mode)):
                if value:
                    db.execute(
                        "INSERT INTO tblApplicationDetails(application_id,"
                        " field_name, field_value) VALUES (?,?,?)",
                        (app_id, field, value))
            for f in attachments or []:
                data = f.getvalue()
                db.execute(
                    "INSERT INTO tblDocuments(application_id, file_name, file_type,"
                    " file_size, version, uploaded_by, upload_time, verified, content)"
                    " VALUES (?,?,?,?,1,?, datetime('now'), 0, ?)",
                    (app_id, f.name, (f.name.rsplit('.', 1)[-1] or '').upper(),
                     len(data), user["user_id"], data))
            audit.log("Application created", "Application Management",
                      "tblApplications", number, new_value="Draft", user=user)
            if submit_now:
                workflow.submit(app_id, user)
                st.success(f"{number} submitted for QAP verification.",
                           icon=":material/send:")
            else:
                st.success(f"{number} saved as a draft.", icon=":material/save:")

with bulk:
    st.caption(
        "Upload a CSV with the columns below. Every row is created as a draft in "
        "your scope; nothing is submitted until you submit it."
    )
    template = pd.DataFrame([{
        "applicant_name": "Sunita Devi",
        "district_name": districts[0]["district_name"],
        "service_name": "Income Certificate",
        "subdivision": "Sadar Sub-division",
        "mobile": "9876543210",
        "remarks": "Filed at the RTPS counter",
    }])
    st.download_button("Download the CSV template",
                       template.to_csv(index=False).encode("utf-8"),
                       "rtps-bulk-template.csv", "text/csv",
                       icon=":material/download:",
                       disabled=not auth.has("app.bulk_upload"))
    upload = st.file_uploader("Bulk CSV", type=["csv"],
                              disabled=not auth.has("app.bulk_upload"))
    if upload is not None:
        incoming = pd.read_csv(io.BytesIO(upload.getvalue()))
        st.caption(f"{len(incoming):,} row(s) read. Check them before creating.")
        ui.table(incoming, columns={})
        allowed = {d["district_name"]: d["district_id"] for d in districts}
        service_ids = {r["service_name"]: (r["service_id"], r["department_id"])
                       for r in db.query("SELECT service_id, service_name,"
                                         " department_id FROM tblServiceMaster")}
        missing = sorted(set(incoming.get("district_name", [])) - set(allowed))
        unknown = sorted(set(incoming.get("service_name", [])) - set(service_ids))
        if missing:
            st.error("Outside your scope, so these rows cannot be created: "
                     + ", ".join(missing), icon=":material/block:")
        if unknown:
            st.error("No such service: " + ", ".join(unknown),
                     icon=":material/error:")
        if not missing and not unknown and st.button(
                "Create these drafts", type="primary",
                icon=":material/playlist_add:"):
            created = 0
            for r in incoming.itertuples():
                did = allowed[r.district_name]
                sid, dept_id = service_ids[r.service_name]
                seq = db.scalar("SELECT COUNT(*) FROM tblApplications") + 1
                number = f"RTPS/{pd.Timestamp.now().year}/{did:02d}/{seq:05d}"
                db.execute(
                    "INSERT INTO tblApplications(application_number, applicant_name,"
                    " district_id, subdivision, department_id, service_id,"
                    " submission_date, status, remarks, created_by, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?, date('now'), 'Draft', ?, ?,"
                    " datetime('now'), datetime('now'))",
                    (number, str(r.applicant_name), did,
                     getattr(r, "subdivision", None), dept_id, sid,
                     getattr(r, "remarks", None), user["user_id"]))
                created += 1
            audit.log(f"Bulk upload of {created} draft(s)", "Application Management",
                      "tblApplications", None, new_value=str(created), user=user)
            st.success(f"{created} draft(s) created.", icon=":material/check_circle:")

with drafts:
    mine = ui.applications("a.status = 'Draft' AND a.created_by = ?",
                           [user["user_id"]], order="a.created_at DESC")
    if mine.empty:
        ui.empty_state("You have no drafts.", ":material/edit_note:")
    else:
        ui.table(mine[["application_number", "applicant_name", "service_name",
                       "district_name", "submission_date"]],
                 columns=ui.APPLICATION_COLUMNS)
        picked = ui.pick_application(mine, key="draft_pick", label="Draft")
        if picked:
            cols = st.columns(2)
            with cols[0]:
                if st.button("Submit for verification", type="primary",
                             icon=":material/send:", width="stretch",
                             disabled=not auth.has("app.submit")):
                    workflow.submit(int(picked["application_id"]), user)
                    st.success(f"{picked['application_number']} submitted.",
                               icon=":material/send:")
                    st.rerun()
            with cols[1]:
                if st.button("Delete this draft", icon=":material/delete:",
                             width="stretch",
                             disabled=not auth.has("app.delete_draft")):
                    aid = int(picked["application_id"])
                    db.execute("DELETE FROM tblApplicationDetails"
                               " WHERE application_id = ?", (aid,))
                    db.execute("DELETE FROM tblDocuments WHERE application_id = ?",
                               (aid,))
                    db.execute("DELETE FROM tblApplications"
                               " WHERE application_id = ? AND status = 'Draft'",
                               (aid,))
                    audit.log("Draft deleted", "Application Management",
                              "tblApplications", picked["application_number"],
                              old_value="Draft", user=user)
                    st.success("Draft deleted.", icon=":material/delete:")
                    st.rerun()
