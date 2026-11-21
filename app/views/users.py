"""Screen 03 — User Management (blueprint module 8)."""

from __future__ import annotations

import secrets
import uuid

import streamlit as st

from app import audit, auth, db, ui

user = auth.require("user.manage")

ui.page_header("User Management",
               "Create, edit, map, disable and reset the accounts in your scope.",
               ":material/group:")

# Who may be created: never a role above your own.
roles = [dict(r) for r in db.query(
    "SELECT role_id, role_name, role_level, scope FROM tblRoles"
    " WHERE role_level >= ? ORDER BY role_level", (user["role_level"],))]
if user["role_name"] != "Super Admin":
    roles = [r for r in roles if r["role_name"] != "Super Admin"]

scope = user["scope"]
if scope == "state":
    user_where, user_params = "1 = 1", []
elif scope == "division":
    user_where = ("(u.division_id = ? OR u.district_id IN (SELECT district_id"
                  " FROM tblDistrictMaster WHERE division_id = ?))")
    user_params = [user["division_id"], user["division_id"]]
else:
    user_where, user_params = "u.district_id = ?", [user["district_id"]]

USERS_SQL = f"""
SELECT u.user_id, u.username, u.employee_name, u.designation, u.mobile, u.email,
       v.division_name, d.district_name, r.role_name, u.status, u.last_login
  FROM tblUsers u
  JOIN tblUserRoles ur ON ur.user_id = u.user_id
  JOIN tblRoles r      ON r.role_id = ur.role_id
  LEFT JOIN tblDistrictMaster d ON d.district_id = u.district_id
  LEFT JOIN tblDivisionMaster v ON v.division_id = u.division_id
 WHERE {user_where}
"""
everyone = db.frame(USERS_SQL + " ORDER BY r.role_level, u.username", user_params)

ui.kpi_row([
    ("Accounts in scope", f"{len(everyone):,}"),
    ("Active", f"{int((everyone['status'] == 'Active').sum()) if not everyone.empty else 0:,}"),
    ("Disabled", f"{int((everyone['status'] == 'Disabled').sum()) if not everyone.empty else 0:,}"),
    ("Roles you can assign", f"{len(roles)}"),
])

directory, create, edit = st.tabs(["Directory", "Create a user", "Edit, map or disable"])

COLUMNS = {
    "username": st.column_config.TextColumn("Username"),
    "employee_name": st.column_config.TextColumn("Employee name", width="medium"),
    "designation": st.column_config.TextColumn("Designation", width="medium"),
    "mobile": st.column_config.TextColumn("Mobile"),
    "email": st.column_config.TextColumn("Email", width="medium"),
    "division_name": st.column_config.TextColumn("Division"),
    "district_name": st.column_config.TextColumn("District"),
    "role_name": st.column_config.TextColumn("Role"),
    "status": st.column_config.TextColumn("Status"),
    "last_login": st.column_config.TextColumn("Last login"),
}

with directory:
    cols = st.columns([2, 2, 2])
    with cols[0]:
        q = st.text_input("Search", placeholder="Name or username", key="u_q")
    with cols[1]:
        pick_roles = st.multiselect("Role", sorted(everyone["role_name"].unique())
                                    if not everyone.empty else [],
                                    placeholder="Any role", key="u_role")
    with cols[2]:
        pick_status = st.multiselect("Status", ["Active", "Disabled"],
                                     placeholder="Any status", key="u_status")
    view = everyone
    if q:
        view = view[view["employee_name"].str.contains(q, case=False)
                    | view["username"].str.contains(q, case=False)]
    if pick_roles:
        view = view[view["role_name"].isin(pick_roles)]
    if pick_status:
        view = view[view["status"].isin(pick_status)]
    if view.empty:
        ui.empty_state("No account matches.", ":material/person_search:")
    else:
        ui.table(view.drop(columns=["user_id"]), columns=COLUMNS, height=440)
        ui.download_row(view.drop(columns=["user_id"]), "users", "Users")


def division_district_inputs(prefix: str, default_district: int | None = None):
    districts = auth.districts_in_scope()
    labels = ["— none —"] + [d["district_name"] for d in districts]
    ids = [None] + [d["district_id"] for d in districts]
    idx = ids.index(default_district) if default_district in ids else 0
    pick = st.selectbox("District", labels, index=idx, key=f"{prefix}_district")
    district_id = ids[labels.index(pick)]
    division_id = None
    if district_id:
        division_id = db.scalar("SELECT division_id FROM tblDistrictMaster"
                                " WHERE district_id = ?", (district_id,), default=None)
    elif scope == "state":
        divs = db.query("SELECT division_id, division_name FROM tblDivisionMaster"
                        " ORDER BY division_name")
        dl = ["— none —"] + [d["division_name"] for d in divs]
        dp = st.selectbox("Division (for division-level roles)", dl,
                          key=f"{prefix}_division")
        division_id = None if dp == "— none —" else next(
            d["division_id"] for d in divs if d["division_name"] == dp)
    elif scope == "division":
        division_id = user["division_id"]
    return division_id, district_id


with create:
    with st.form("create_user", border=True, clear_on_submit=False):
        row1 = st.columns(3)
        with row1[0]:
            username = st.text_input("Username *", placeholder="operator.gaya2")
        with row1[1]:
            name = st.text_input("Employee name *")
        with row1[2]:
            designation = st.text_input("Designation")
        row2 = st.columns(3)
        with row2[0]:
            mobile = st.text_input("Mobile", max_chars=10)
        with row2[1]:
            email = st.text_input("Email")
        with row2[2]:
            role = st.selectbox("Role *", [r["role_name"] for r in roles])
        division_id, district_id = division_district_inputs("new")
        go = st.form_submit_button("Create user", type="primary",
                                   icon=":material/person_add:", width="stretch")
    if go:
        problems = []
        if not username.strip() or not name.strip():
            problems.append("Username and employee name are required.")
        if db.scalar("SELECT COUNT(*) FROM tblUsers WHERE username = ?",
                     (username.strip(),)):
            problems.append("That username is taken.")
        if mobile and (len(mobile) != 10 or not mobile.isdigit()):
            problems.append("A mobile number is ten digits.")
        chosen = next(r for r in roles if r["role_name"] == role)
        if chosen["scope"] == "district" and not district_id:
            problems.append(f"A {role} must be mapped to a district.")
        if chosen["scope"] == "division" and not division_id:
            problems.append(f"A {role} must be mapped to a division.")
        if problems:
            for p in problems:
                st.error(p, icon=":material/error:")
        else:
            temp = secrets.token_urlsafe(9)
            salt = uuid.uuid4().hex[:16]
            uid = db.execute(
                "INSERT INTO tblUsers(username, password_hash, salt, employee_name,"
                " designation, mobile, email, division_id, district_id, status,"
                " created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?, 'Active',"
                " datetime('now'), ?)",
                (username.strip(), db.hash_password(temp, salt), salt, name.strip(),
                 designation or None, mobile or None, email or None, division_id,
                 district_id, user["username"]))
            db.execute("INSERT INTO tblUserRoles(user_id, role_id) VALUES (?,?)",
                       (uid, chosen["role_id"]))
            audit.log("User created", "User Management", "tblUsers", username.strip(),
                      new_value=role, user=user)
            st.success(f"{username.strip()} created as {role}.",
                       icon=":material/person_add:")
            st.info(f"Temporary password: `{temp}` — shown once. Hand it over "
                    "securely; the user should change it at first sign-in.",
                    icon=":material/key:")

with edit:
    if everyone.empty:
        ui.empty_state("No account in your scope.", ":material/person_off:")
    else:
        uid = st.selectbox(
            "Account", everyone["user_id"].tolist(),
            format_func=lambda i: (
                f"{everyone.loc[everyone.user_id == i, 'username'].iloc[0]} — "
                f"{everyone.loc[everyone.user_id == i, 'employee_name'].iloc[0]} "
                f"({everyone.loc[everyone.user_id == i, 'role_name'].iloc[0]})"),
            key="edit_pick")
        target = dict(db.one(
            "SELECT u.*, r.role_name, r.role_level FROM tblUsers u"
            " JOIN tblUserRoles ur ON ur.user_id = u.user_id"
            " JOIN tblRoles r ON r.role_id = ur.role_id WHERE u.user_id = ?", (uid,)))
        above_me = target["role_level"] < user["role_level"]
        if above_me:
            st.warning("This account holds a role above yours, so you can read it "
                       "but not change it.", icon=":material/block:")
        ui.status_line("Status", target["status"],
                       {"Active": ("green", ":material/check_circle:"),
                        "Disabled": ("red", ":material/block:")})
        with st.form("edit_user", border=True):
            row1 = st.columns(3)
            with row1[0]:
                e_name = st.text_input("Employee name", target["employee_name"])
            with row1[1]:
                e_desig = st.text_input("Designation", target["designation"] or "")
            with row1[2]:
                role_names = [r["role_name"] for r in roles]
                e_role = st.selectbox(
                    "Role", role_names,
                    index=role_names.index(target["role_name"])
                    if target["role_name"] in role_names else 0)
            row2 = st.columns(2)
            with row2[0]:
                e_mobile = st.text_input("Mobile", target["mobile"] or "", max_chars=10)
            with row2[1]:
                e_email = st.text_input("Email", target["email"] or "")
            e_div, e_dist = division_district_inputs("edit", target["district_id"])
            save = st.form_submit_button("Save changes", type="primary",
                                         icon=":material/save:", width="stretch",
                                         disabled=above_me)
        if save and not above_me:
            chosen = next(r for r in roles if r["role_name"] == e_role)
            db.execute(
                "UPDATE tblUsers SET employee_name = ?, designation = ?, mobile = ?,"
                " email = ?, division_id = ?, district_id = ? WHERE user_id = ?",
                (e_name, e_desig or None, e_mobile or None, e_email or None,
                 e_div if e_div else target["division_id"], e_dist, uid))
            db.execute("UPDATE tblUserRoles SET role_id = ? WHERE user_id = ?",
                       (chosen["role_id"], uid))
            audit.log("User modified", "User Management", "tblUsers",
                      target["username"],
                      old_value=f"{target['role_name']} / {target['district_id']}",
                      new_value=f"{e_role} / {e_dist}", user=user)
            st.success("Saved.", icon=":material/save:")
            st.rerun()

        cols = st.columns(2)
        with cols[0]:
            flip = "Disabled" if target["status"] == "Active" else "Active"
            if st.button("Disable account" if flip == "Disabled" else "Re-enable account",
                         icon=":material/block:" if flip == "Disabled"
                         else ":material/check_circle:",
                         width="stretch",
                         disabled=above_me or uid == user["user_id"]):
                db.execute("UPDATE tblUsers SET status = ? WHERE user_id = ?",
                           (flip, uid))
                audit.log(f"User {flip.lower()}", "User Management", "tblUsers",
                          target["username"], old_value=target["status"],
                          new_value=flip, user=user)
                st.rerun()
        with cols[1]:
            if st.button("Reset password", icon=":material/lock_reset:",
                         width="stretch", disabled=above_me):
                temp = secrets.token_urlsafe(9)
                db.execute("UPDATE tblUsers SET password_hash = ? WHERE user_id = ?",
                           (db.hash_password(temp, target["salt"]), uid))
                audit.log("Password reset", "User Management", "tblUsers",
                          target["username"], user=user)
                st.info(f"New temporary password for {target['username']}: `{temp}` "
                        "— shown once.", icon=":material/key:")
