from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from claudealytics.analytics.parsers.token_miner import mine_daily_tokens, mine_session_cache
from claudealytics.analytics.cache_analyzer import (
    compute_daily_cache_metrics,
    compute_cost_savings,
    detect_cache_breaking_sessions,
    project_cache_summary,
)


def render(stats):
    daily_df = _load_daily_tokens()
    session_df = _load_session_cache()

    if daily_df.empty and session_df.empty:
        st.warning("No cache data available. Ensure conversation JSONL files exist in ~/.claude/projects/")
        return

    daily_metrics = compute_daily_cache_metrics(daily_df)
    cost_savings = compute_cost_savings(daily_df)
    project_summary = project_cache_summary(session_df)

    _render_kpis(daily_metrics, cost_savings, session_df)

    st.divider()
    if not daily_metrics.empty:
        col1, col2 = st.columns(2)
        date_from = col1.date_input("From", value=daily_metrics["date"].min(), key="cache_from")
        date_to = col2.date_input("To", value=daily_metrics["date"].max(), key="cache_to")

        date_mask = (daily_metrics["date"] >= pd.to_datetime(date_from)) & (daily_metrics["date"] <= pd.to_datetime(date_to))
        filtered_daily = daily_metrics[date_mask]

        cost_mask = (cost_savings["date"] >= pd.to_datetime(date_from)) & (cost_savings["date"] <= pd.to_datetime(date_to))
        filtered_costs = cost_savings[cost_mask]
    else:
        filtered_daily = daily_metrics
        filtered_costs = cost_savings

    if not filtered_daily.empty:
        st.subheader("Daily Cache Hit Rate", help="Percentage of input tokens served from cache vs fresh API calls.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtered_daily["date"], y=filtered_daily["cache_hit_rate"],
            mode="lines+markers", name="Cache Hit Rate",
            line=dict(color="#14b8a6", width=2), marker=dict(size=5),
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Hit Rate: %{y:.1f}%<extra></extra>",
        ))
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,68,68,0.5)", annotation_text="70% healthy threshold")
        fig.update_layout(
            height=350, margin=dict(l=20, r=20, t=40, b=0),
            yaxis_title="Cache Hit Rate (%)", xaxis_title="Date", yaxis=dict(range=[0, 105]),
        )
        st.plotly_chart(fig, use_container_width=True)

    if not filtered_daily.empty:
        st.subheader("Daily Cache Reuse Multiplier", help="Ratio of cache read tokens to cache creation tokens. Above 1.25x means cache pays for itself.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtered_daily["date"], y=filtered_daily["cache_reuse_multiplier"],
            mode="lines+markers", name="Reuse Multiplier",
            line=dict(color="#8b5cf6", width=2), marker=dict(size=5),
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Multiplier: %{y:.2f}x<extra></extra>",
        ))
        fig.add_hline(y=1.25, line_dash="dash", line_color="rgba(245,158,11,0.5)", annotation_text="1.25x break-even")
        fig.update_layout(
            height=350, margin=dict(l=20, r=20, t=40, b=0),
            yaxis_title="Reuse Multiplier (x)", xaxis_title="Date",
        )
        st.plotly_chart(fig, use_container_width=True)

    if not filtered_daily.empty and (filtered_daily["ephemeral_1h_tokens"].sum() > 0 or filtered_daily["ephemeral_5m_tokens"].sum() > 0):
        st.subheader("Cache TTL Distribution Over Time", help="Token volume by cache TTL bucket (1-hour vs 5-minute ephemeral) over time.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtered_daily["date"], y=filtered_daily["ephemeral_1h_tokens"],
            mode="lines+markers", name="1h Ephemeral",
            line=dict(color="#6366f1"), marker=dict(size=4),
            hovertemplate="Date: %{x|%Y-%m-%d}<br>1h Tokens: %{y:,}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=filtered_daily["date"], y=filtered_daily["ephemeral_5m_tokens"],
            mode="lines+markers", name="5m Ephemeral",
            line=dict(color="#f59e0b"), marker=dict(size=4),
            hovertemplate="Date: %{x|%Y-%m-%d}<br>5m Tokens: %{y:,}<extra></extra>",
        ))
        fig.update_layout(
            height=350, margin=dict(l=20, r=20, t=60, b=0),
            yaxis_title="Tokens", xaxis_title="Date",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    if not filtered_costs.empty:
        st.subheader("Cache Cost Savings", help="Estimated daily USD savings from cache reads vs paying full input token price.")
        total_savings = filtered_costs["savings_usd"].sum()
        avg_savings_pct = filtered_costs["savings_pct"].mean()

        col1, col2 = st.columns(2)
        col1.metric("Total Savings (filtered)", f"${total_savings:,.2f}")
        col2.metric("Avg Daily Savings", f"{avg_savings_pct:.1f}%")

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=filtered_costs["date"], y=filtered_costs["no_cache_cost"],
            name="Without Cache", marker_color="rgba(239,68,68,0.6)",
            hovertemplate="Date: %{x|%Y-%m-%d}<br>No-Cache Cost: $%{y:.2f}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=filtered_costs["date"], y=filtered_costs["actual_cost"],
            name="Actual Cost", marker_color="rgba(20,184,166,0.8)",
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Actual Cost: $%{y:.2f}<extra></extra>",
        ))
        fig.update_layout(
            height=350, margin=dict(l=20, r=20, t=60, b=0),
            barmode="overlay", yaxis_title="Cost (USD)", xaxis_title="Date",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    if not project_summary.empty:
        st.subheader("Cache Efficiency by Project", help="Average cache hit rate per project. Red < 50%, amber 50-70%, green > 70%.")

        proj_df = project_summary.copy()
        proj_df["color"] = proj_df["avg_hit_rate"].apply(lambda x: "#ef4444" if x < 50 else ("#f59e0b" if x < 70 else "#22c55e"))

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=proj_df["project"], x=proj_df["avg_hit_rate"], orientation="h",
            marker_color=proj_df["color"],
            text=proj_df["avg_hit_rate"].apply(lambda x: f"{x:.1f}%"), textposition="outside",
            hovertemplate="Project: %{y}<br>Avg Hit Rate: %{x:.1f}%<br><extra></extra>",
        ))
        fig.add_vline(x=70, line_dash="dash", line_color="rgba(100,100,100,0.3)")
        fig.update_layout(
            height=max(200, len(proj_df) * 40 + 80), margin=dict(l=20, r=80, t=20, b=0),
            xaxis_title="Avg Cache Hit Rate (%)", xaxis=dict(range=[0, 105]),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            proj_df[["project", "session_count", "avg_hit_rate", "avg_reuse_multiplier", "model_switch_pct"]]
            .rename(columns={
                "project": "Project", "session_count": "Sessions",
                "avg_hit_rate": "Avg Hit Rate (%)", "avg_reuse_multiplier": "Avg Reuse Multiplier",
                "model_switch_pct": "Model Switch %",
            }),
            hide_index=True, use_container_width=True,
        )

    breaking = detect_cache_breaking_sessions(session_df)
    if not breaking.empty:
        with st.expander("Cache-Breaking Sessions"):
            st.caption("Sessions with poor cache efficiency, sorted worst first.")

            display_cols = ["date", "project", "model", "message_count", "cache_hit_rate", "cache_reuse_multiplier", "reasons"]
            display_df = breaking[display_cols].copy()
            display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
            display_df["model"] = display_df["model"].apply(_short_model_name)

            st.dataframe(
                display_df.rename(columns={
                    "date": "Date", "project": "Project", "model": "Model", "message_count": "Messages",
                    "cache_hit_rate": "Hit Rate (%)", "cache_reuse_multiplier": "Reuse Mult.", "reasons": "Reasons",
                }),
                hide_index=True, use_container_width=True,
            )
    elif not session_df.empty:
        st.info("No cache-breaking sessions detected. Your cache efficiency looks healthy!")

    st.divider()
    st.caption(
        "Cache pricing: cache read = 10% of input price, cache creation = 125% (5m TTL) or 200% (1h TTL) of input price. "
        "Reuse multiplier > 1.25 means cache paid for itself. Cache is prefix-based: tools -> system prompt -> CLAUDE.md -> conversation."
    )


def _render_kpis(daily_metrics: pd.DataFrame, cost_savings: pd.DataFrame, session_df: pd.DataFrame):
    col1, col2, col3, col4 = st.columns(4)

    if not daily_metrics.empty:
        total_cache_read = daily_metrics["cache_read_input_tokens"].sum()
        total_all_input = daily_metrics["input_tokens"].sum() + total_cache_read + daily_metrics["cache_creation_input_tokens"].sum()
        overall_hit_rate = (total_cache_read / total_all_input * 100) if total_all_input > 0 else 0
        col1.metric("Overall Cache Hit Rate", f"{overall_hit_rate:.1f}%")
    else:
        col1.metric("Overall Cache Hit Rate", "N/A")

    if not daily_metrics.empty:
        total_read = daily_metrics["cache_read_input_tokens"].sum()
        total_create = daily_metrics["cache_creation_input_tokens"].sum()
        avg_multiplier = (total_read / total_create) if total_create > 0 else 0
        col2.metric("Avg Reuse Multiplier", f"{avg_multiplier:.2f}x")
    else:
        col2.metric("Avg Reuse Multiplier", "N/A")

    if not cost_savings.empty:
        total_savings = cost_savings["savings_usd"].sum()
        col3.metric("Total Estimated Savings", f"${total_savings:,.2f}")
    else:
        col3.metric("Total Estimated Savings", "N/A")

    if not session_df.empty:
        switch_count = session_df["had_model_switch"].sum()
        total_sessions = len(session_df)
        col4.metric(
            "Sessions with Model Switches", f"{switch_count}",
            help=f"{switch_count}/{total_sessions} sessions ({switch_count/total_sessions*100:.0f}%)" if total_sessions > 0 else "",
        )
    else:
        col4.metric("Sessions with Model Switches", "N/A")


@st.cache_data(ttl=300)
def _load_daily_tokens() -> pd.DataFrame:
    return mine_daily_tokens(use_cache=True)


@st.cache_data(ttl=300)
def _load_session_cache() -> pd.DataFrame:
    return mine_session_cache(use_cache=True)


def _short_model_name(model: str) -> str:
    if "opus-4-6" in model: return "Opus 4.6"
    if "opus-4-5" in model: return "Opus 4.5"
    if "opus-4-1" in model: return "Opus 4.1"
    if "sonnet-4-5" in model: return "Sonnet 4.5"
    if "sonnet-4-1" in model: return "Sonnet 4.1"
    if "haiku" in model: return "Haiku 3.5"
    return model
