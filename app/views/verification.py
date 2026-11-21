"""Screen 08 — QAP Verification (blueprint module 4)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, seed, theme, ui, workflow

user = auth.require("verify.perform")

ui.page_header("QAP Verification",
               "Apply the checklist, score the record, and pass it on or send it back.",
               ":material/fact_check:")

scope, scope_params = auth.scope_clause()
# New submissions, plus records whose correction the operator has answered:
# those come back as Under Verification with no approval level yet.
queue_where = (f"{scope} AND (a.status = 'Submitted' OR"
               " (a.status = 'Under Verification' AND a.current_level IS NULL))")
queue = ui.applications(queue_where, scope_params, order="a.submitted_at ASC")

verified_by_me = db.scalar(
    "SELECT COUNT(*) FROM tblVerification WHERE verifier_id = ?",
    (user["user_id"],))
avg_score = db.scalar(
    "SELECT AVG(v.score) FROM tblVerification v"
    " JOIN tblApplications a ON a.application_id = v.application_id"
    f" WHERE {scope}", scope_params, default=0.0) or 0.0
failed = db.scalar(
    "SELECT COUNT(*) FROM tblVerification v"
    " JOIN tblApplications a ON a.application_id = v.application_id"
    f" WHERE {scope} AND v.result = 'Fail'", scope_params)
reverify_count = int((queue["status"] == "Under Verification").sum()) if not queue.empty else 0

ui.kpi_row([
    ("Waiting for verification", f"{len(queue):,}",
     "New submissions and answered corrections."),
    ("Back for re-verification", f"{reverify_count:,}"),
    ("Average score in your scope", f"{avg_score:.1f}"),
    ("Failed verifications", f"{failed:,}"),
], per_row=4)
st.caption(f"You have recorded {verified_by_me:,} verification(s).")

if queue.empty:
    ui.empty_state("Nothing is waiting for verification in your scope.",
                   ":material/task_alt:")
    st.stop()

ui.section("Verification queue", "Oldest first, because the SLA runs from submission.")
ui.table(queue[["application_number", "applicant_name", "service_name",
                "district_name", "status", "submission_date", "age_days"]],
         height=260)

ui.section("Run the checklist")
row = ui.pick_application(queue, key="verify_pick")
if row is None:
    st.stop()
app_id = int(row["application_id"])

prior = db.frame(
    "SELECT score, result, verified_at FROM tblVerification"
    " WHERE application_id = ? ORDER BY verified_at DESC", [app_id])
if not prior.empty:
    st.caption(f"This record has been verified {len(prior)} time(s) before — "
               f"the last round scored {prior.iloc[0]['score']:.0f} and "
               f"{prior.iloc[0]['result'].lower()}ed.")

docs = db.scalar("SELECT COUNT(*) FROM tblDocuments WHERE application_id = ?",
                 (app_id,))
st.caption(f"{docs} document(s) attached. Open Document Repository to read them.")

with st.form("verification", border=True):
    st.subheader("Checklist", anchor=False)
    st.caption("Each item carries its weight; the score is the weight of what passes.")
    marks = []
    for code, text, weight in seed.CHECKLIST:
        cols = st.columns([5, 2, 3])
        with cols[0]:
            st.markdown(f"**{code}** · {text}")
            st.caption(f"Weight {weight}")
        with cols[1]:
            result = st.radio(f"{code} result", ["Pass", "Fail", "NA"],
                              horizontal=True, key=f"v_{code}",
                              label_visibility="collapsed")
        with cols[2]:
            comment = st.text_input(f"{code} comment", key=f"c_{code}",
                                    placeholder="Comment (needed on a fail)",
                                    label_visibility="collapsed")
        marks.append({"item_code": code, "item_text": text, "weight": weight,
                      "result": result, "comment": comment})
    remarks = st.text_area("Verification remarks", height=90,
                           placeholder="What you checked and what you found.")
    running = sum(m["weight"] for m in marks if m["result"] == "Pass")
    st.markdown(f"**Score as it stands:** {running}/100")
    record = st.form_submit_button("Record verification", type="primary",
                                   icon=":material/fact_check:", width="stretch")

if record:
    missing = [m["item_code"] for m in marks
               if m["result"] == "Fail" and not m["comment"].strip()]
    if missing:
        st.error("A failed item needs a comment: " + ", ".join(missing),
                 icon=":material/error:")
    else:
        result, total = workflow.record_verification(
            app_id, user["user_id"], marks, remarks, user)
        if result == "Pass":
            st.success(
                f"{row['application_number']} scored {total:.0f}/100 and has moved "
                f"to {workflow.LEVELS[0]}.", icon=":material/check_circle:")
        else:
            st.warning(
                f"{row['application_number']} scored {total:.0f}/100 and failed. "
                "A correction has been raised and assigned to the operator who "
                "filed it.", icon=":material/report:")
        st.rerun()
