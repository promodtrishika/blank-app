"""Screen 15 — Master Management (blueprint module 9)."""

from __future__ import annotations

import streamlit as st

from app import audit, auth, db, ui

user = auth.require("master.manage")

ui.page_header("Master Management",
               "Districts, divisions, blocks, services, offices and departments.",
               ":material/database:")

MASTERS = {
    "District": {
        "table": "tblDistrictMaster", "key": "district_id",
        "sql": "SELECT m.district_id, m.district_name, v.division_name, m.status"
               "  FROM tblDistrictMaster m JOIN tblDivisionMaster v"
               "    ON v.division_id = m.division_id ORDER BY m.district_name",
        "name": "district_name", "parent": ("division_id", "tblDivisionMaster",
                                            "division_name", "Division"),
    },
    "Division": {
        "table": "tblDivisionMaster", "key": "division_id",
        "sql": "SELECT division_id, division_name, status FROM tblDivisionMaster"
               " ORDER BY division_name",
        "name": "division_name", "parent": None,
    },
    "Block": {
        "table": "tblBlockMaster", "key": "block_id",
        "sql": "SELECT b.block_id, b.block_name, d.district_name, b.status"
               "  FROM tblBlockMaster b JOIN tblDistrictMaster d"
               "    ON d.district_id = b.district_id ORDER BY d.district_name, b.block_name",
        "name": "block_name", "parent": ("district_id", "tblDistrictMaster",
                                         "district_name", "District"),
    },
    "Service": {
        "table": "tblServiceMaster", "key": "service_id",
        "sql": "SELECT s.service_id, s.service_name, dep.department_name, s.sla_days,"
               " s.status FROM tblServiceMaster s JOIN tblDepartmentMaster dep"
               "   ON dep.department_id = s.department_id ORDER BY s.service_name",
        "name": "service_name", "parent": ("department_id", "tblDepartmentMaster",
                                           "department_name", "Department"),
    },
    "Office": {
        "table": "tblOfficeMaster", "key": "office_id",
        "sql": "SELECT o.office_id, o.office_name, d.district_name, o.status"
               "  FROM tblOfficeMaster o JOIN tblDistrictMaster d"
               "    ON d.district_id = o.district_id ORDER BY d.district_name, o.office_name",
        "name": "office_name", "parent": ("district_id", "tblDistrictMaster",
                                          "district_name", "District"),
    },
    "Department": {
        "table": "tblDepartmentMaster", "key": "department_id",
        "sql": "SELECT department_id, department_name, status FROM tblDepartmentMaster"
               " ORDER BY department_name",
        "name": "department_name", "parent": None,
    },
}

counts = {k: db.scalar(f"SELECT COUNT(*) FROM {v['table']}") for k, v in MASTERS.items()}
ui.kpi_row([(f"{k}s", f"{n:,}") for k, n in counts.items()], per_row=6)

kind = st.segmented_control("Master", list(MASTERS), default="District",
                            key="master_kind")
if not kind:
    st.stop()
m = MASTERS[kind]
frame = db.frame(m["sql"])

ui.section(f"{kind} master")
q = st.text_input("Search", placeholder=f"{kind} name", key=f"m_q_{kind}")
view = frame[frame[m["name"]].str.contains(q, case=False)] if q and not frame.empty else frame
ui.table(view, columns={}, height=360)
ui.download_row(view, f"{kind.lower()}-master", f"{kind} Master")

add, change = st.columns(2, gap="large")
with add:
    ui.section(f"Add a {kind.lower()}")
    with st.form(f"add_{kind}", border=True, clear_on_submit=True):
        name = st.text_input(f"{kind} name *")
        parent_id = None
        if m["parent"]:
            col, ptable, pname, plabel = m["parent"]
            parents = db.query(f"SELECT {col}, {pname} FROM {ptable}"
                               f" WHERE status = 'Active' ORDER BY {pname}")
            plabels = [p[pname] for p in parents]
            chosen = st.selectbox(f"{plabel} *", plabels)
            parent_id = next(p[col] for p in parents if p[pname] == chosen) if plabels else None
        sla = st.number_input("SLA (days)", 1, 90, 15) if kind == "Service" else None
        go = st.form_submit_button(f"Add {kind.lower()}", type="primary",
                                   icon=":material/add:", width="stretch")
    if go:
        if not name.strip():
            st.error("A name is required.", icon=":material/error:")
        elif db.scalar(f"SELECT COUNT(*) FROM {m['table']} WHERE {m['name']} = ?",
                       (name.strip(),)):
            st.error(f"A {kind.lower()} with that name already exists.",
                     icon=":material/error:")
        else:
            cols, vals = [m["name"]], [name.strip()]
            if m["parent"]:
                cols.append(m["parent"][0]); vals.append(parent_id)
            if sla is not None:
                cols.append("sla_days"); vals.append(int(sla))
            db.execute(f"INSERT INTO {m['table']}({', '.join(cols)})"
                       f" VALUES ({', '.join('?' * len(vals))})", vals)
            audit.log(f"{kind} added", "Master Management", m["table"], name.strip(),
                      new_value="Active", user=user)
            st.success(f"{name.strip()} added.", icon=":material/add:")
            st.rerun()

with change:
    ui.section(f"Activate or deactivate")
    if frame.empty:
        ui.empty_state(f"No {kind.lower()} on record.")
    else:
        rid = st.selectbox(kind, frame[m["key"]].tolist(),
                           format_func=lambda i: frame.loc[frame[m["key"]] == i,
                                                           m["name"]].iloc[0],
                           key=f"m_pick_{kind}")
        current = frame.loc[frame[m["key"]] == rid, "status"].iloc[0]
        ui.status_line("Status", current,
                       {"Active": ("green", ":material/check_circle:"),
                        "Inactive": ("grey", ":material/block:")})
        st.caption("Deactivating hides it from new entries; records already filed "
                   "keep it.")
        target = "Inactive" if current == "Active" else "Active"
        if st.button(f"Mark {target.lower()}", icon=":material/sync_alt:",
                     width="stretch", key=f"m_flip_{kind}"):
            db.execute(f"UPDATE {m['table']} SET status = ? WHERE {m['key']} = ?",
                       (target, rid))
            audit.log(f"{kind} {target.lower()}", "Master Management", m["table"],
                      rid, old_value=current, new_value=target, user=user)
            st.rerun()
