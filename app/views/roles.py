"""Screen 04 — Role Management (blueprint module 8, RBAC)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import audit, auth, db, ui

user = auth.require("role.manage")

ui.page_header("Role Management",
               "The permission matrix behind every screen and action.",
               ":material/admin_panel_settings:")

roles = [dict(r) for r in db.query(
    "SELECT r.role_id, r.role_name, r.role_level, r.scope, r.description,"
    " (SELECT COUNT(*) FROM tblUserRoles ur WHERE ur.role_id = r.role_id) AS users"
    "  FROM tblRoles r ORDER BY r.role_level")]
perms = [dict(r) for r in db.query(
    "SELECT permission_id, permission_code, module, description"
    "  FROM tblPermissions ORDER BY module, permission_code")]
granted = {(r["role_id"], r["permission_id"]) for r in db.query(
    "SELECT role_id, permission_id FROM tblRolePermissions")}

ui.section("Roles")
ui.table(pd.DataFrame(roles).drop(columns=["role_id"]), columns={
    "role_name": st.column_config.TextColumn("Role", width="medium"),
    "role_level": st.column_config.NumberColumn("Level", format="%d",
                                                help="1 is the most senior."),
    "scope": st.column_config.TextColumn("Data scope"),
    "description": st.column_config.TextColumn("What it is for", width="large"),
    "users": st.column_config.NumberColumn("Users", format="%d"),
})

ui.section("Permission matrix",
           "Tick to grant. Super Admin always keeps every permission, so the "
           "portal can never lock itself out.")
matrix = pd.DataFrame(
    [{"module": p["module"], "permission": p["permission_code"],
      "description": p["description"],
      **{r["role_name"]: (r["role_id"], p["permission_id"]) in granted for r in roles}}
     for p in perms])
role_cols = {r["role_name"]: st.column_config.CheckboxColumn(
    r["role_name"], disabled=r["role_name"] == "Super Admin") for r in roles}
edited = st.data_editor(
    matrix, hide_index=True, width="stretch", height=560, key="perm_matrix",
    disabled=["module", "permission", "description"],
    column_config={
        "module": st.column_config.TextColumn("Module", width="medium"),
        "permission": st.column_config.TextColumn("Permission", width="medium"),
        "description": st.column_config.TextColumn("Grants", width="medium"),
        **role_cols,
    })

changes = []
for p_idx, p in enumerate(perms):
    for r in roles:
        before = (r["role_id"], p["permission_id"]) in granted
        after = bool(edited.iloc[p_idx][r["role_name"]])
        if before != after and r["role_name"] != "Super Admin":
            changes.append((r, p, after))

if changes:
    st.warning(f"{len(changes)} unsaved change(s). Users pick them up at their "
               "next sign-in.", icon=":material/edit:")
    with st.expander("Review the changes"):
        for r, p, after in changes:
            st.markdown(("**Grant** " if after else "**Revoke** ")
                        + f"`{p['permission_code']}` "
                        + ("to " if after else "from ") + f"**{r['role_name']}**")
    if st.button("Save permission changes", type="primary", icon=":material/save:"):
        for r, p, after in changes:
            if after:
                db.execute("INSERT OR IGNORE INTO tblRolePermissions(role_id,"
                           " permission_id) VALUES (?,?)",
                           (r["role_id"], p["permission_id"]))
            else:
                db.execute("DELETE FROM tblRolePermissions WHERE role_id = ?"
                           " AND permission_id = ?",
                           (r["role_id"], p["permission_id"]))
            audit.log("Permission " + ("granted" if after else "revoked"),
                      "User Management", "tblRolePermissions",
                      f"{r['role_name']}:{p['permission_code']}",
                      old_value=str(not after), new_value=str(after), user=user)
        st.success("Saved.", icon=":material/save:")
        st.rerun()
