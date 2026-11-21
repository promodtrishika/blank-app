"""The shared pieces every screen reaches for.

One definition each of the page header, the KPI tile row, a status badge, the
filter row and the table, so eighteen screens read as one portal. Roles are
written with Streamlit's own elements — its metric, badge, dataframe and form
— rather than hand-written markup.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

from app import db, theme

# --- Holders and headings ----------------------------------------------


def page_header(title: str, subtitle: str | None = None,
                icon: str | None = None) -> None:
    """The page title — one level, always the outermost heading of a screen."""
    st.title(f"{icon} {title}" if icon else title, anchor=False)
    if subtitle:
        st.caption(subtitle)


def section(label: str, help_text: str | None = None) -> None:
    """A section heading — one level below the page title."""
    st.subheader(label, anchor=False, divider="gray")
    if help_text:
        st.caption(help_text)


# --- Status vocabulary --------------------------------------------------


def badge_markup(value: str | None, vocab: dict | None = None) -> str:
    """A badge string: colour plus icon plus the word, never colour alone."""
    vocab = vocab or theme.STATUS_BADGE
    if not value:
        return ":grey-badge[—]"
    colour, icon = vocab.get(value, ("grey", ":material/help:"))
    return f":{colour}-badge[{icon} {value}]"


def badge(value: str | None, vocab: dict | None = None) -> None:
    st.markdown(badge_markup(value, vocab))


def status_line(label: str, value: str | None, vocab: dict | None = None) -> None:
    st.markdown(f"**{label}** {badge_markup(value, vocab)}")


# --- KPI tiles ----------------------------------------------------------


def kpi_row(items: Sequence[tuple], per_row: int = 4) -> None:
    """Tiles of one number each, in rows of `per_row`, every tile bordered."""
    items = list(items)
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(per_row, border=False)
        for col, item in zip(cols, chunk):
            label, value = item[0], item[1]
            help_text = item[2] if len(item) > 2 else None
            with col:
                st.metric(label, value, help=help_text, border=True)


# --- Filters ------------------------------------------------------------


def filter_row(
    *,
    key: str,
    statuses: Iterable[str] | None = None,
    with_district: bool = True,
    with_service: bool = True,
    with_dates: bool = True,
    with_text: bool = True,
) -> dict:
    """One row of filters above the content, the same shape on every screen."""
    from app import auth

    widths = []
    if with_text:
        widths.append(2)
    if statuses is not None:
        widths.append(2)
    if with_district:
        widths.append(2)
    if with_service:
        widths.append(2)
    if with_dates:
        widths.append(3)
    cols = st.columns(widths or [1])
    out: dict = {}
    i = 0

    if with_text:
        with cols[i]:
            out["text"] = st.text_input(
                "Search", key=f"{key}_text", placeholder="Number or applicant",
                help="Matches the application number or the applicant's name.")
        i += 1

    if statuses is not None:
        with cols[i]:
            out["statuses"] = st.multiselect(
                "Status", list(statuses), key=f"{key}_status",
                placeholder="Any status")
        i += 1

    if with_district:
        districts = auth.districts_in_scope()
        labels = {d["district_name"]: d["district_id"] for d in districts}
        with cols[i]:
            picked = st.multiselect("District", list(labels), key=f"{key}_district",
                                    placeholder="Any district in your scope")
        out["district_ids"] = [labels[p] for p in picked]
        i += 1

    if with_service:
        services = {r["service_name"]: r["service_id"] for r in db.query(
            "SELECT service_id, service_name FROM tblServiceMaster"
            " WHERE status = 'Active' ORDER BY service_name")}
        with cols[i]:
            picked = st.multiselect("Service", list(services), key=f"{key}_service",
                                    placeholder="Any service")
        out["service_ids"] = [services[p] for p in picked]
        i += 1

    if with_dates:
        with cols[i]:
            out["dates"] = st.date_input(
                "Submitted between", value=(), key=f"{key}_dates",
                help="Leave empty for every date on record.")
        i += 1

    return out


def where_from_filters(f: dict, alias: str = "a") -> tuple[str, list]:
    """Turn the filter row's answers into SQL, scope included."""
    from app import auth

    clause, params = auth.scope_clause(alias)
    parts = [clause]
    if f.get("text"):
        parts.append(f"({alias}.application_number LIKE ?"
                     f" OR {alias}.applicant_name LIKE ?)")
        params += [f"%{f['text']}%", f"%{f['text']}%"]
    if f.get("statuses"):
        parts.append(f"{alias}.status IN ({','.join('?' * len(f['statuses']))})")
        params += list(f["statuses"])
    if f.get("district_ids"):
        parts.append(f"{alias}.district_id IN ({','.join('?' * len(f['district_ids']))})")
        params += list(f["district_ids"])
    if f.get("service_ids"):
        parts.append(f"{alias}.service_id IN ({','.join('?' * len(f['service_ids']))})")
        params += list(f["service_ids"])
    dates = f.get("dates") or ()
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        parts.append(f"date({alias}.submission_date) BETWEEN ? AND ?")
        params += [str(dates[0]), str(dates[1])]
    return " AND ".join(parts), params


# --- Tables and empty states -------------------------------------------

APPLICATION_COLUMNS = {
    "application_number": st.column_config.TextColumn("Application", width="medium"),
    "applicant_name": st.column_config.TextColumn("Applicant", width="medium"),
    "service_name": st.column_config.TextColumn("Service", width="medium"),
    "district_name": st.column_config.TextColumn("District"),
    "status": st.column_config.TextColumn("Status", width="medium"),
    "current_level": st.column_config.TextColumn("Level", width="medium"),
    "score": st.column_config.NumberColumn("QAP score", format="%.0f",
                                           min_value=0, max_value=100),
    "submission_date": st.column_config.TextColumn("Submitted"),
    "approved_at": st.column_config.TextColumn("Approved"),
    "age_days": st.column_config.NumberColumn("Age (days)", format="%d"),
}


def table(frame: pd.DataFrame, *, columns: dict | None = None,
          height: int | None = None, selection: bool = False,
          key: str | None = None):
    """The one table: Streamlit's dataframe, index hidden, stretched.

    Columns without an explicit label get a readable one — no snake_case ever
    reaches the screen.
    """
    config = dict(APPLICATION_COLUMNS)
    config.update(columns or {})
    for col in frame.columns:
        if col not in config:
            config[col] = st.column_config.Column(
                str(col).replace("_", " ").strip().capitalize())
    kwargs = dict(width="stretch", hide_index=True,
                  column_config={k: v for k, v in config.items() if k in frame.columns})
    if height:
        kwargs["height"] = height
    if selection:
        kwargs.update(on_select="rerun", selection_mode="single-row", key=key)
    return st.dataframe(frame, **kwargs)


def empty_state(message: str, icon: str = ":material/inbox:") -> None:
    st.info(message, icon=icon)


def download_row(frame: pd.DataFrame, stem: str, title: str | None = None) -> None:
    """Export in the three formats the blueprint names — PDF, Excel, CSV."""
    if frame.empty:
        return
    title = title or stem.replace("-", " ").title()
    cols = st.columns(3)
    with cols[0]:
        st.download_button("Download PDF", _pdf(frame, title), f"{stem}.pdf",
                           "application/pdf", icon=":material/picture_as_pdf:",
                           width="stretch")
    with cols[1]:
        st.download_button(
            "Download Excel", _xlsx(frame, title), f"{stem}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/table_view:", width="stretch")
    with cols[2]:
        st.download_button("Download CSV", frame.to_csv(index=False).encode("utf-8"),
                           f"{stem}.csv", "text/csv", icon=":material/download:",
                           width="stretch")


def _xlsx(frame: pd.DataFrame, title: str) -> bytes:
    import io

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=title[:31] or "Report")
        sheet = writer.sheets[title[:31] or "Report"]
        for i, col in enumerate(frame.columns, start=1):
            width = max(len(str(col)), *(len(str(v)) for v in frame[col].head(200)))
            sheet.column_dimensions[sheet.cell(1, i).column_letter].width = min(48, width + 2)
        sheet.freeze_panes = "A2"
    return buf.getvalue()


def _pdf(frame: pd.DataFrame, title: str) -> bytes:
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 8, f"RTPS QAP - {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 8)
    pdf.cell(0, 5, f"{len(frame):,} row(s) - generated {pd.Timestamp.now():%Y-%m-%d %H:%M}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    def cell(v) -> str:
        text = "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)
        # The core PDF fonts are Latin-1; anything outside it prints as '?'.
        return text.encode("latin-1", "replace").decode("latin-1")[:60]

    data = frame.head(1500).astype(object).map(cell)
    with pdf.table(headings_style=FontFace(emphasis="BOLD", fill_color=(240, 239, 236)),
                   line_height=4.6, text_align="LEFT", padding=1) as table:
        table.row([str(c).replace("_", " ").title() for c in data.columns])
        for values in data.itertuples(index=False):
            table.row(list(values))
    if len(frame) > 1500:
        pdf.ln(2)
        pdf.cell(0, 5, "PDF holds the first 1,500 rows; use Excel or CSV for all of them.")
    return bytes(pdf.output())


# --- Application lookups shared by several screens ---------------------

APP_SELECT = """
SELECT a.application_id, a.application_number, a.applicant_name, a.status,
       a.current_level, a.score, a.submission_date, a.is_locked,
       s.service_name, d.district_name, dep.department_name,
       b.block_name, o.office_name, a.subdivision, a.remarks,
       a.created_at, a.submitted_at, a.approved_at,
       CAST(julianday('now') - julianday(COALESCE(a.submitted_at, a.created_at))
            AS INTEGER) AS age_days
  FROM tblApplications a
  JOIN tblServiceMaster s     ON s.service_id = a.service_id
  JOIN tblDistrictMaster d    ON d.district_id = a.district_id
  JOIN tblDepartmentMaster dep ON dep.department_id = a.department_id
  LEFT JOIN tblBlockMaster b  ON b.block_id = a.block_id
  LEFT JOIN tblOfficeMaster o ON o.office_id = a.office_id
"""


def applications(where: str, params: list, order: str = "a.submitted_at DESC",
                 limit: int | None = None) -> pd.DataFrame:
    sql = f"{APP_SELECT} WHERE {where} ORDER BY {order}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.frame(sql, params)


def pick_application(frame: pd.DataFrame, key: str,
                     label: str = "Application") -> dict | None:
    """One way of choosing a record, used by every screen that acts on one."""
    if frame.empty:
        return None
    options = frame["application_id"].tolist()
    labels = {
        int(r.application_id): f"{r.application_number} — {r.applicant_name} "
                               f"({r.service_name}, {r.district_name})"
        for r in frame.itertuples()
    }
    chosen = st.selectbox(label, options, format_func=lambda i: labels[int(i)],
                          key=key, index=0)
    if chosen is None:
        return None
    row = frame[frame["application_id"] == chosen]
    return row.iloc[0].to_dict() if not row.empty else None


def detail_grid(row: dict, fields: Sequence[tuple[str, str]],
                per_row: int = 3) -> None:
    """Label-over-value pairs, read left to right then down."""
    items = [(label, row.get(col)) for label, col in fields]
    for start in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, (label, value) in zip(cols, items[start:start + per_row]):
            with col:
                st.caption(label)
                st.markdown(f"**{value if value not in (None, '') else '—'}**")
