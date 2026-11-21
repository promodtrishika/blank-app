"""The charts, built once and reused.

Form follows the data's job: change over time is a line, magnitude by identity
is a sorted bar, an ordered pipeline is an ordinal ramp. Colour comes last and
from `theme` only — the categorical slots in fixed order for series, one hue
for a single measure, the ordinal ramp for the funnel. Every chart with two or
more series carries a legend and direct labels, and the trend also offers its
numbers as a table, which is the relief the light-mode aqua slot needs. Values
and labels wear text colour, never a series colour; a mark beside them carries
the identity.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app import theme

AXIS = alt.Axis(grid=False, domainOpacity=0.3, tickOpacity=0.3, labelPadding=6,
                labelOverlap=False, labelLimit=240)
ROW_STEP = 28  # px per bar row, so every category name has room
MEASURE_AXIS = alt.Axis(grid=True, gridOpacity=0.15, domain=False, ticks=False,
                        labelPadding=6)


def _empty(message: str) -> None:
    st.info(message, icon=":material/query_stats:")


def _value_labels(data: pd.DataFrame, label: str, value: str,
                  sort) -> alt.Chart:
    """Direct value labels in text colour, with no colour encoding at all."""
    return (
        alt.Chart(data)
        .mark_text(align="left", dx=6, fontSize=12, color=theme.text_secondary())
        .encode(
            # No axis setting here: in a layer the axes merge, and axis=None
            # on one layer would strip the category names from the bars.
            y=alt.Y(f"{label}:N", sort=sort),
            x=alt.X(f"{value}:Q"),
            text=alt.Text(f"{value}:Q", format=",.0f"),
        )
    )


def trend(frame: pd.DataFrame, x: str, y: str, series: str,
          order: list[str], x_title: str = "", y_title: str = "",
          height: int = 300) -> None:
    """Change over time, one line per series — at most three series.

    `order` is the full, fixed series list: colour follows the series, so a
    filter that empties one series never repaints the others.
    """
    if frame.empty:
        _empty("No records fall in this range yet.")
        return
    names = list(order)
    frame = frame.astype({series: str})
    if len(names) > 3:
        raise ValueError("fold anything past the third series into 'Other', or facet it")
    scale = alt.Scale(domain=names, range=theme.categorical(len(names)))

    hover = alt.selection_point(nearest=True, on="pointerover", fields=[x],
                                empty=False, clear="pointerout")
    lines = (
        alt.Chart(frame)
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=45, filled=True))
        .encode(
            x=alt.X(f"{x}:O", title=x_title or None, axis=AXIS),
            y=alt.Y(f"{y}:Q", title=y_title or None, axis=MEASURE_AXIS),
            color=alt.Color(f"{series}:N", scale=scale,
                            legend=alt.Legend(title=None, orient="top",
                                              direction="horizontal")),
            tooltip=[alt.Tooltip(f"{x}:O", title=x_title or x),
                     alt.Tooltip(f"{series}:N", title="Series"),
                     alt.Tooltip(f"{y}:Q", title=y_title or y, format=",.0f")],
        )
    )
    crosshair = (
        alt.Chart(frame)
        .mark_rule(strokeWidth=1, opacity=0.3)
        .encode(x=alt.X(f"{x}:O"))
        .add_params(hover)
        .transform_filter(hover)
    )
    # Direct name labels at the last period, in the series colour: these name
    # the lines, so they are the one place a label carries identity.
    tail = frame.loc[frame.groupby(series)[x].idxmax()].sort_values(y).copy()
    # Dodge the end labels: hold them at least 7% of the y range apart, so two
    # lines ending close together never print their names on top of each other.
    gap = max(frame[y].max() - min(0, frame[y].min()), 1) * 0.07
    placed = []
    for value in tail[y]:
        placed.append(max(value, placed[-1] + gap) if placed else value)
    tail["_label_y"] = placed
    names_at_end = (
        alt.Chart(tail)
        .mark_text(align="left", dx=8, fontSize=12, fontWeight=600)
        .encode(x=alt.X(f"{x}:O"),
                y=alt.Y("_label_y:Q"),
                text=alt.Text(f"{series}:N"),
                color=alt.Color(f"{series}:N", scale=scale, legend=None))
    )
    st.altair_chart((crosshair + lines + names_at_end).properties(height=height),
                    width="stretch")
    with st.expander("See these numbers as a table"):
        wide = (frame.pivot_table(index=x, columns=series, values=y, aggfunc="sum")
                .fillna(0).astype(int))
        st.dataframe(wide, width="stretch")


def ranked_bar(frame: pd.DataFrame, label: str, value: str,
               value_title: str = "", height: int | None = None,
               top: int | None = None) -> None:
    """Magnitude by identity: one measure, one hue, sorted, labelled."""
    if frame.empty:
        _empty("Nothing to rank yet.")
        return
    data = frame.sort_values(value, ascending=False)
    if top:
        data = data.head(top)
    height = height or max(180, ROW_STEP * len(data))
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, color=theme.sequential(), height=16)
        .encode(
            y=alt.Y(f"{label}:N", sort="-x", title=None, axis=AXIS),
            x=alt.X(f"{value}:Q", title=value_title or None, axis=MEASURE_AXIS),
            tooltip=[alt.Tooltip(f"{label}:N",
                                 title=label.replace("_", " ").title()),
                     alt.Tooltip(f"{value}:Q", title=value_title or value,
                                 format=",.1f")],
        )
    )
    chart = bars + _value_labels(data, label, value, sort="-x")
    st.altair_chart(chart.properties(height=height), width="stretch")


def funnel(stages: list[tuple[str, int]], height: int = 240) -> None:
    """An ordered pipeline: the ordinal ramp, light at the wide end."""
    if not stages:
        _empty("No records are in the approval chain.")
        return
    frame = pd.DataFrame(stages, columns=["stage", "count"])
    order = frame["stage"].tolist()
    scale = alt.Scale(domain=order, range=theme.ordinal(len(frame)))
    bars = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=4, height=22)
        .encode(
            y=alt.Y("stage:N", sort=order, title=None, axis=AXIS),
            x=alt.X("count:Q", title="Applications", axis=MEASURE_AXIS),
            color=alt.Color("stage:N", scale=scale, legend=None),
            tooltip=[alt.Tooltip("stage:N", title="Stage"),
                     alt.Tooltip("count:Q", title="Applications", format=",.0f")],
        )
    )
    chart = bars + _value_labels(frame, "stage", "count", sort=order)
    st.altair_chart(chart.properties(height=height), width="stretch")
