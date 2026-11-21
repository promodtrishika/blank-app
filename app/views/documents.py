"""Screen 17 — Document Repository (blueprint module 13)."""

from __future__ import annotations

import streamlit as st

from app import audit, auth, db, theme, ui

user = auth.require("doc.view")

ui.page_header("Document Repository",
               "Upload, view, download and version the documents behind each record.",
               ":material/folder_open:")

ALLOWED = ["pdf", "docx", "xlsx", "jpg", "jpeg", "png"]
MIME = {"PDF": "application/pdf", "JPG": "image/jpeg", "JPEG": "image/jpeg",
        "PNG": "image/png",
        "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

scope, scope_params = auth.scope_clause()
filters = ui.filter_row(key="docs", statuses=theme.APP_STATUSES, with_dates=False)
where, params = ui.where_from_filters(filters)
frame = ui.applications(where, params, limit=400)

totals = db.one(
    "SELECT COUNT(*) AS n, SUM(d.file_size) AS bytes,"
    " SUM(CASE WHEN d.verified = 1 THEN 1 ELSE 0 END) AS verified"
    "  FROM tblDocuments d JOIN tblApplications a"
    "    ON a.application_id = d.application_id"
    f" WHERE {scope}", scope_params)
ui.kpi_row([
    ("Documents", f"{totals['n'] or 0:,}"),
    ("Attachment checks passed", f"{totals['verified'] or 0:,}"),
    ("Storage used", f"{(totals['bytes'] or 0) / 1_048_576:,.1f} MB"),
], per_row=3)

if frame.empty:
    ui.empty_state("No application matches these filters.")
    st.stop()

row = ui.pick_application(frame, key="docs_pick")
if row is None:
    st.stop()
app_id = int(row["application_id"])
locked = bool(row["is_locked"])

docs = db.frame(
    "SELECT d.document_id, d.file_name, d.file_type, d.file_size, d.version,"
    " u.employee_name AS uploaded_by, d.upload_time, d.verified,"
    " d.content IS NOT NULL AS has_content"
    "  FROM tblDocuments d LEFT JOIN tblUsers u ON u.user_id = d.uploaded_by"
    " WHERE d.application_id = ? ORDER BY d.file_name, d.version DESC", [app_id])

ui.section("Files on this record")
if docs.empty:
    ui.empty_state("No document attached yet.", ":material/folder_off:")
else:
    shown = docs.assign(
        attachment=docs["verified"].map({1: "Verified", 0: "Not verified"}))
    ui.table(shown[["file_name", "file_type", "file_size", "version",
                    "uploaded_by", "upload_time", "attachment"]], columns={
        "file_name": st.column_config.TextColumn("File", width="medium"),
        "file_type": st.column_config.TextColumn("Type"),
        "file_size": st.column_config.NumberColumn("Size (bytes)", format="%d"),
        "version": st.column_config.NumberColumn("Version", format="%d"),
        "uploaded_by": st.column_config.TextColumn("Uploaded by"),
        "upload_time": st.column_config.TextColumn("When"),
        "attachment": st.column_config.TextColumn("Attachment check"),
    })

    doc_id = st.selectbox(
        "Document", docs["document_id"].tolist(),
        format_func=lambda i: (
            f"{docs.loc[docs.document_id == i, 'file_name'].iloc[0]} — v"
            f"{docs.loc[docs.document_id == i, 'version'].iloc[0]}"),
        key="doc_pick")
    picked = db.one("SELECT * FROM tblDocuments WHERE document_id = ?", (doc_id,))
    content = picked["content"]
    in_sharepoint = picked["sp_item_id"] is not None
    if content is None and in_sharepoint:
        # The bytes live in the SharePoint library: fetch once per document
        # version and keep them for this session.
        cache_key = f"doc_bytes_{doc_id}_{picked['sp_version_id']}"
        if cache_key not in st.session_state:
            with st.spinner("Fetching from SharePoint…"):
                try:
                    st.session_state[cache_key] = db.store().files.download_document(
                        picked["sp_item_id"], picked["sp_version_id"])
                except Exception as exc:
                    st.session_state[cache_key] = None
                    st.error(f"SharePoint did not return the file: {exc}",
                             icon=":material/cloud_off:")
        content = st.session_state[cache_key]
    cols = st.columns(3)
    with cols[0]:
        if content is not None:
            st.download_button(
                "Download", content, picked["file_name"],
                MIME.get(picked["file_type"].upper(), "application/octet-stream"),
                icon=":material/download:", width="stretch",
                on_click=lambda: audit.log("Document downloaded",
                                           "Document Management", "tblDocuments",
                                           picked["file_name"], user=user))
        else:
            st.button("Download", icon=":material/download:", width="stretch",
                      disabled=True,
                      help="Seeded demo records carry metadata only; files you "
                           "upload here can be downloaded.")
    with cols[1]:
        can_check = auth.has("verify.perform", "approve.district_review",
                             "approve.district_approve")
        if st.button("Mark attachment verified", icon=":material/verified:",
                     width="stretch",
                     disabled=not can_check or bool(picked["verified"])):
            db.execute("UPDATE tblDocuments SET verified = 1 WHERE document_id = ?",
                       (doc_id,))
            audit.log("Attachment verified", "Document Management", "tblDocuments",
                      picked["file_name"], old_value="Not verified",
                      new_value="Verified", user=user)
            st.rerun()
    with cols[2]:
        st.caption(f"Version {picked['version']} of {picked['file_name']}"
                   + (f" · SharePoint version {picked['sp_version_id']}"
                      if picked["sp_version_id"] else ""))
        if picked["web_url"]:
            st.link_button("Open in SharePoint", picked["web_url"],
                           icon=":material/open_in_new:", width="stretch")
    if content is not None and picked["file_type"].upper() in ("JPG", "JPEG", "PNG"):
        st.image(content, caption=picked["file_name"], width=360)

ui.section("Upload")
if not auth.has("doc.upload"):
    st.caption("Your role can read documents but not upload them.")
elif locked:
    st.warning("This record is locked. Request an unlock before adding documents.",
               icon=":material/lock:")
else:
    with st.form("upload", border=True, clear_on_submit=True):
        files = st.file_uploader("Files", type=ALLOWED, accept_multiple_files=True,
                                 help="A file with the same name becomes the next "
                                      "version, and the earlier one is kept"
                                      + (" — in SharePoint's own version history."
                                         if db.mode() == "sharepoint" else "."))
        go = st.form_submit_button("Upload", type="primary",
                                   icon=":material/upload:", width="stretch")
    if go and files:
        for f in files:
            data = f.getvalue()
            version = db.scalar(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM tblDocuments"
                " WHERE application_id = ? AND file_name = ?", (app_id, f.name),
                default=1)
            db.execute(
                "INSERT INTO tblDocuments(application_id, file_name, file_type,"
                " file_size, version, uploaded_by, upload_time, verified, content)"
                " VALUES (?,?,?,?,?,?, datetime('now'), 0, ?)",
                (app_id, f.name, f.name.rsplit(".", 1)[-1].upper(), len(data),
                 version, user["user_id"], data))
            audit.log("Document uploaded", "Document Management", "tblDocuments",
                      f"{row['application_number']}/{f.name}",
                      new_value=f"v{version}", user=user)
        st.success(f"{len(files)} file(s) uploaded.", icon=":material/upload:")
        st.rerun()
