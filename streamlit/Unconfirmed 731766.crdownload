"""
BrazilCommerce 360 — dashboard

Reads the dbt insight marts directly. All business logic lives in dbt, where it
is tested and version-controlled; this file only presents. Each chart carries a
caption stating the takeaway and the action, because a chart without a "so what"
is decoration.

Two data sources, one set of charts:

  * Snowflake, when [snowflake] credentials are present. The queries below are
    what runs, and they read the dbt marts directly.
  * A committed CSV snapshot of those same marts otherwise, so the public
    deployment works without exposing warehouse credentials.

The snapshot is REGENERATED from the raw data by the same logic as the dbt
models, not exported from Snowflake. `data/marts/README.md` records where the
two disagree. The header states which source is in use, because a dashboard
that quietly serves stale figures as live ones is worse than one that admits
what it is reading.

Run locally:
    streamlit run streamlit/app.py

Deploy:
    push to GitHub and connect the repo at share.streamlit.io. Leave the
    Secrets box empty to serve the snapshot; paste the [snowflake] block from
    .streamlit/secrets.toml to go live.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="BrazilCommerce 360",
    page_icon="📦",
    layout="wide",
)

# Colour roles rather than arbitrary choices: green reads as healthy, red as the
# problem being highlighted, amber as the transition between them.
GREEN, AMBER, RED, BLUE = "#1baf7a", "#eda100", "#e34948", "#3987e5"

DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "ECOMMERCE_DEV")
MART = f"{DATABASE}.DBT_MART"
STAGING = f"{DATABASE}.DBT_STAGING"

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "marts"


# ---------------------------------------------------------------------------
# Which source
#
# Reading st.secrets raises rather than returning empty when no secrets file
# exists at all, so the check has to be defensive. Absent credentials are a
# normal state here, not an error: it is how the public deployment runs.
# ---------------------------------------------------------------------------

def _have_credentials() -> bool:
    try:
        return "snowflake" in st.secrets
    except Exception:
        return False


LIVE = _have_credentials()
SOURCE = "snowflake" if LIVE else "snapshot"


# ---------------------------------------------------------------------------
# Data access
#
# Both paths return a frame with lower-case column names, because Snowflake
# returns identifiers upper-cased and the charts should not have to care which
# source they were handed.
# ---------------------------------------------------------------------------

@st.cache_resource
def get_connection():
    import snowflake.connector

    return snowflake.connector.connect(**dict(st.secrets["snowflake"]))


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str) -> pd.DataFrame:
    """Run a query against Snowflake."""
    cur = get_connection().cursor()
    try:
        cur.execute(sql)
        df = cur.fetch_pandas_all()
    finally:
        cur.close()
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(show_spinner=False)
def load_mart(table: str) -> pd.DataFrame:
    """Read one table from the committed snapshot.

    The CSVs carry the same column names and row order as the Snowflake
    tables, so no renaming or sorting happens here — if a column name drifts,
    it should fail loudly in the chart rather than be patched over in the
    loader.
    """
    path = SNAPSHOT_DIR / f"{table}.csv"
    if not path.exists():
        st.error(
            f"**Snapshot table `{table}` is missing.**\n\n"
            f"Expected `{path}`. Regenerate it with "
            "`python analysis/build_snapshot.py`, or add Snowflake credentials "
            "to read the warehouse instead."
        )
        st.stop()
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    return df


def fetch(table: str, sql: str, *, lens: str | None = None) -> pd.DataFrame:
    """One dataset, from whichever source is available.

    `sql` is what runs against the warehouse. On the snapshot path the same
    table is read from CSV and the same row filter applied, so both paths hand
    the charts an identically shaped frame.

    Credentials that are present but do not work — an expired trial, a paused
    warehouse, a rotated password — fall back to the snapshot with a warning
    rather than showing a stack trace. A public dashboard should degrade, not
    break, and it should say which happened.
    """
    global LIVE
    if LIVE:
        try:
            return q(sql)
        except Exception as exc:                      # noqa: BLE001 - any failure
            LIVE = False
            st.session_state["_connection_error"] = f"{type(exc).__name__}: {exc}"
    df = load_mart(table)
    if lens is not None:
        df = df[df.lens == lens]
    return df.reset_index(drop=True)


_REDACT = [
    # account identifier and host, e.g. ABCDEFG-HIJ12345.us-east-1.snowflakecomputing.com:443
    (re.compile(r"[\w.-]*snowflakecomputing\.com(?::\d+)?", re.I), "<account>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"(?i)\buser\s+'[^']*'"), "user '<user>'"),
]


def redact(text: str) -> str:
    """Strip identifiers out of an error before it is shown.

    This page is public. A connection error is useful diagnostics and is worth
    showing, but the account identifier, host and user in it are not anyone
    else's business.
    """
    for pattern, replacement in _REDACT:
        text = pattern.sub(replacement, text)
    return text


def connection_warning() -> None:
    """Shown once, after the first failed query, not before one is attempted."""
    err = st.session_state.get("_connection_error")
    if err:
        st.warning(
            "**Snowflake credentials are set but the warehouse could not be "
            "reached.** Serving the committed snapshot instead.\n\n"
            f"`{redact(err)[:200]}`"
        )


# Model metrics are properties of a fitted model, not of a table, so they
# cannot come from either query. The snapshot refits on a regenerated feature
# table and lands slightly differently — same features, same split, marginally
# different row count. Both are recorded rather than one being presented as
# though it covered both cases.
_SNAPSHOT_METRICS = SNAPSHOT_DIR / "model_metrics.json"


def model_metrics() -> dict:
    """Read at the point of use, not at import — the source can change part way
    through a run if a live connection fails and falls back."""
    if LIVE or not _SNAPSHOT_METRICS.exists():
        return {"auc": 0.684, "late_odds": 3.49}   # models/metrics.json, warehouse run
    m = json.loads(_SNAPSHOT_METRICS.read_text())
    return {"auc": m["test_roc_auc"], "late_odds": m["odds_ratios"]["is_late"]}


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("BrazilCommerce 360")

kpis = fetch("kpis", f"""
    select
        (select sum(item_price) from {MART}.fact_orders)                    as gmv,
        (select count(distinct order_id) from {MART}.fact_orders)            as orders,
        (select count(*) from {MART}.dim_customers)                          as customers,
        (select round(avg(review_score), 2) from {STAGING}.stg_order_reviews
          where review_score between 1 and 5)                               as avg_review,
        (select pct_of_reviews from {MART}.mart_review_distribution
          where review_score = 1)                                           as pct_one_star,
        (select round(sum(case when order_frequency <> '1 order'
                               then pct_of_customers else 0 end), 2)
           from {MART}.mart_retention)                                      as repeat_rate
""").iloc[0]

connection_warning()

st.markdown(
    f"Olist Brazilian marketplace · September 2016 – October 2018 · "
    f"{int(kpis.orders):,} orders with line items across "
    f"{int(kpis.customers):,} customers · "
    + ("reading **Snowflake**" if LIVE else "reading the **committed snapshot**")
)

st.info(
    "**The lever is the promise, not the parcel.** Orders that miss the promised "
    "delivery date draw a bad review 54% of the time against 9% for on-time "
    "orders — a 5.9× difference. Remote states with honest estimates score well; "
    "closer states with unreliable ones score worst. Because 97% of customers "
    "never return, that review is the last interaction."
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("GMV", f"R${kpis.gmv / 1e6:.1f}M")
c2.metric("Orders", f"{int(kpis.orders):,}")
c3.metric("Customers", f"{int(kpis.customers):,}")
c4.metric("Repeat rate", f"{kpis.repeat_rate:.1f}%",
          "no retention flywheel", delta_color="off")
c5.metric("1-star share", f"{kpis.pct_one_star:.1f}%",
          "track this, not the mean", delta_color="off")

st.divider()


# ---------------------------------------------------------------------------
# 1 — Retention
# ---------------------------------------------------------------------------

st.subheader("1 · Growth depends entirely on acquisition")

left, right = st.columns([2, 1])

with left:
    ret = fetch("mart_retention", f"""
        select order_frequency, customers, pct_of_customers
        from {MART}.mart_retention
        order by order_frequency
    """)

    fig = go.Figure(go.Bar(
        x=ret.order_frequency,
        y=ret.pct_of_customers,
        marker_color=[RED, AMBER, GREEN],
        text=[f"{v:.2f}%" for v in ret.pct_of_customers],
        textposition="outside",
    ))
    fig.update_layout(
        height=320, margin=dict(t=20, b=20),
        yaxis=dict(title="% of customers", range=[0, 108]),
        xaxis_title="Orders placed",
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    once = ret.loc[ret.order_frequency == "1 order", "pct_of_customers"].iloc[0]
    st.markdown("#### Why it matters")
    st.markdown(
        f"**{once:.2f}%** of customers ordered exactly once. There is no repeat-purchase "
        "flywheel to absorb a bad experience.\n\n"
        "**→ Action:** treat the first order as the entire customer relationship. "
        "First-order reliability returns more than any retention campaign, because "
        "there is no retention behaviour to amplify."
    )

st.divider()


# ---------------------------------------------------------------------------
# 2 — Delivery and the promise
# ---------------------------------------------------------------------------

st.subheader("2 · The promise matters more than the clock")

left, right = st.columns(2)

with left:
    speed = fetch("mart_delivery_satisfaction", f"""
        select bucket, orders, avg_review_score, pct_bad_review
        from {MART}.mart_delivery_satisfaction
        where lens = 'speed'
        order by bucket_order
    """, lens="speed")

    fig = go.Figure(go.Bar(
        x=speed.bucket, y=speed.avg_review_score,
        marker_color=[GREEN, GREEN, AMBER, RED],
        text=[f"{v:.2f}★" for v in speed.avg_review_score],
        textposition="outside",
        customdata=speed[["orders", "pct_bad_review"]],
        hovertemplate="<b>%{x}</b><br>%{customdata[0]:,} orders"
                      "<br>%{customdata[1]:.1f}% bad reviews<extra></extra>",
    ))
    fig.update_layout(
        height=320, margin=dict(t=20, b=20),
        yaxis=dict(title="Average review score", range=[0, 5.4]),
        xaxis_title="Actual delivery time",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Satisfaction erodes gradually, then falls sharply past three weeks.")

with right:
    promise = fetch("mart_delivery_satisfaction", f"""
        select bucket, orders, avg_review_score, pct_bad_review
        from {MART}.mart_delivery_satisfaction
        where lens = 'promise'
        order by bucket_order
    """, lens="promise")

    fig = go.Figure(go.Bar(
        x=promise.bucket, y=promise.avg_review_score,
        marker_color=[GREEN, RED],
        text=[f"{v:.2f}★" for v in promise.avg_review_score],
        textposition="outside",
        customdata=promise[["orders", "pct_bad_review"]],
        hovertemplate="<b>%{x}</b><br>%{customdata[0]:,} orders"
                      "<br>%{customdata[1]:.1f}% bad reviews<extra></extra>",
    ))
    fig.update_layout(
        height=320, margin=dict(t=20, b=20),
        yaxis=dict(title="Average review score", range=[0, 5.4]),
        xaxis_title="Delivered against the promised date",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("The same orders, split by whether the estimate was met. A far sharper divide.")

late = promise[promise.bucket.str.startswith("Late")].iloc[0]
ontime = promise[~promise.bucket.str.startswith("Late")].iloc[0]

st.info(
    f"**Why it matters:** Olist already pads its estimates, and it works — {int(ontime.orders):,} "
    f"orders beat the quoted date and average {ontime.avg_review_score:.2f}★. The damage sits "
    f"in the {int(late.orders):,} that miss an already-generous estimate: "
    f"**{late.pct_bad_review:.1f}% draw a bad review against {ontime.pct_bad_review:.1f}%**.\n\n"
    "**→ Action:** alarm on late-vs-promise rate, not average delivery days. Extending quoted "
    "lead times in unreliable lanes costs nothing and converts late arrivals into on-time ones."
)

st.divider()


# ---------------------------------------------------------------------------
# 3 — Geography
# ---------------------------------------------------------------------------

st.subheader("3 · Remote is fine; unpredictable is not")

geo = fetch("mart_geographic_chain", f"""
    select state, orders, avg_delivery_days, avg_review_score,
           pct_late_vs_promise, customers, sellers
    from {MART}.mart_geographic_chain
    order by avg_delivery_days desc
""")

fig = px.scatter(
    geo,
    x="avg_delivery_days",
    y="avg_review_score",
    size="orders",
    color="pct_late_vs_promise",
    text="state",
    size_max=45,
    color_continuous_scale=[[0, GREEN], [0.5, AMBER], [1, RED]],
    labels={
        "avg_delivery_days": "Average delivery time (days)",
        "avg_review_score": "Average review score",
        "pct_late_vs_promise": "% late",
    },
    custom_data=["state", "orders", "pct_late_vs_promise", "sellers"],
)
fig.update_traces(
    textposition="top center",
    textfont_size=9,
    hovertemplate="<b>%{customdata[0]}</b><br>%{x:.1f} days · %{y:.2f}★"
                  "<br>%{customdata[1]:,} orders<br>%{customdata[2]:.1f}% late"
                  "<br>%{customdata[3]} local sellers<extra></extra>",
)
fig.update_layout(height=460, margin=dict(t=20, b=20))
st.plotly_chart(fig, use_container_width=True)

# Named rather than coded, so the caption reads as a sentence. Derived from the
# frame rather than typed in, so it cannot drift from the chart beside it.
STATE_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
    "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe",
    "SP": "São Paulo", "TO": "Tocantins",
}


def state_name(code: str) -> str:
    return STATE_NAMES.get(str(code), str(code))


_slowest = geo.sort_values("avg_delivery_days", ascending=False).iloc[0]
_worst = geo.sort_values("avg_review_score").iloc[0]
_latest = ", ".join(
    state_name(s) for s in
    geo.sort_values("pct_late_vs_promise", ascending=False).state.head(3))

st.info(
    f"**Why it matters:** the colour, not the position, tells the story. "
    f"{state_name(_slowest.state)} is the slowest state in the country at "
    f"{_slowest.avg_delivery_days:.0f} days and still scores "
    f"{_slowest.avg_review_score:.2f}★, because only {_slowest.pct_late_vs_promise:.1f}% "
    f"of its orders arrive late. {state_name(_worst.state)} is *faster* at "
    f"{_worst.avg_delivery_days:.0f} days and scores worst at "
    f"{_worst.avg_review_score:.2f}★, because {_worst.pct_late_vs_promise:.0f}% miss the "
    "promise. Distance is survivable when the estimate is honest.\n\n"
    "**→ Action:** recalibrate delivery estimates per state from observed performance "
    f"rather than a national default. For {_latest} this is a pricing-page change, not a "
    "logistics investment."
)

st.divider()


# ---------------------------------------------------------------------------
# 4 — Customer value
# ---------------------------------------------------------------------------

st.subheader("4 · Value is concentrated, but not through loyalty")

left, right = st.columns([2, 1])

with left:
    seg = fetch("mart_customer_segments", f"""
        select value_tier, customers, avg_spend, pct_of_revenue, avg_orders
        from {MART}.mart_customer_segments
    """)
    tier_order = ["Top 1%", "Top 10%", "Next 40%", "Bottom 50%"]
    seg["value_tier"] = pd.Categorical(seg.value_tier, categories=tier_order, ordered=True)
    seg = seg.sort_values("value_tier")

    fig = go.Figure()
    fig.add_bar(
        x=seg.value_tier.astype(str), y=seg.pct_of_revenue, name="% of revenue",
        marker_color=BLUE,
        text=[f"{v:.1f}%" for v in seg.pct_of_revenue], textposition="outside",
    )
    fig.add_scatter(
        x=seg.value_tier.astype(str), y=seg.avg_orders, name="Avg orders per customer",
        yaxis="y2", mode="lines+markers",
        line=dict(color=RED, width=2), marker=dict(size=9),
    )
    fig.update_layout(
        height=340, margin=dict(t=20, b=20),
        yaxis=dict(title="% of revenue", range=[0, 50]),
        yaxis2=dict(title="Avg orders", overlaying="y", side="right", range=[0, 2]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Revenue share varies widely across tiers. Orders per customer does not.")

with right:
    st.markdown("#### Why it matters")
    st.markdown(
        "The top 11% of customers generate **41.2%** of revenue — but average orders per "
        "customer is 1.09 in the top 1% and 1.01 in the bottom half. High-value customers "
        "are not buying more often; they place a single, much larger order.\n\n"
        "**→ Action:** do not build a loyalty programme against this pattern. Identify "
        "high-basket orders at checkout and route them to the most reliable fulfilment lanes."
    )

st.divider()


# ---------------------------------------------------------------------------
# 5 — Review distribution
# ---------------------------------------------------------------------------

st.subheader("5 · The average review score is a misleading KPI")

left, right = st.columns([2, 1])

with left:
    dist = fetch("mart_review_distribution", f"""
        select review_score, reviews, pct_of_reviews
        from {MART}.mart_review_distribution
        order by review_score
    """)

    fig = go.Figure(go.Bar(
        x=[f"{s}★" for s in dist.review_score],
        y=dist.pct_of_reviews,
        marker_color=[RED, "#f0997b", AMBER, "#7fbf6a", GREEN],
        text=[f"{v:.1f}%" for v in dist.pct_of_reviews],
        textposition="outside",
    ))
    fig.update_layout(
        height=340, margin=dict(t=20, b=20),
        yaxis=dict(title="% of reviews", range=[0, 68]),
        xaxis_title="Review score",
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.markdown("#### Why it matters")
    st.markdown(
        "The distribution is bimodal and non-monotonic: **1-star reviews outnumber "
        "2-star and 3-star combined**. Only 30.7% of reviews land anywhere in the "
        "2–4 range.\n\n"
        "The mean of 4.09 is also insensitive — a rise in 1-star can be offset by a "
        "rise in 5-star and leave it unchanged for months.\n\n"
        "**→ Action:** adopt **%-1-star** as the operational health metric."
    )

st.divider()


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------

st.subheader("Flagging bad reviews before they happen")

risk = fetch("review_risk_buckets", f"""
    select risk_bucket, count(*) as orders,
           round(avg(risk_probability) * 100, 1) as avg_predicted_pct
    from {MART}.review_risk_scores
    group by risk_bucket
""")

bucket_order = ["Low", "Medium", "High", "Very High"]
risk["risk_bucket"] = pd.Categorical(risk.risk_bucket, categories=bucket_order, ordered=True)
risk = risk.dropna(subset=["risk_bucket"]).sort_values("risk_bucket")

left, right = st.columns([2, 1])

with left:
    palette = {"Low": GREEN, "Medium": GREEN, "High": AMBER, "Very High": RED}
    fig = go.Figure(go.Bar(
        x=risk.risk_bucket.astype(str),
        y=risk.orders,
        marker_color=[palette[b] for b in risk.risk_bucket.astype(str)],
        text=[f"{int(v):,}" for v in risk.orders],
        textposition="outside",
    ))
    fig.update_layout(
        height=320, margin=dict(t=20, b=20),
        yaxis_title="Orders", xaxis_title="Predicted risk bucket",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Logistic regression on delivery lateness, duration and freight burden. "
        f"Test ROC AUC {model_metrics()['auc']:.3f} against a 12.8% base rate."
    )

with right:
    _vh = risk[risk.risk_bucket.astype(str) == "Very High"]
    _vh_orders = int(_vh.orders.iloc[0]) if len(_vh) else 0

    st.markdown("#### Why it matters")
    st.markdown(
        f"Lateness dominates the model at **{model_metrics()['late_odds']:.2f}× odds**; the other "
        "features sit near neutral. It is not slowness that predicts a bad review, it is "
        "a missed commitment.\n\n"
        f"The **Very High** bucket holds {_vh_orders:,} orders where **52% actually leave "
        "a bad review** — four times the base rate.\n\n"
        "**→ Action:** trigger outreach on that bucket before the review request is sent. "
        f"At {_vh_orders:,} orders the volume is operationally tractable."
    )

st.divider()


# ---------------------------------------------------------------------------
# Footer — freshness and reconciliation
# ---------------------------------------------------------------------------

with st.expander("Data source, freshness and pipeline reconciliation"):
    if LIVE:
        st.markdown(
            "Reading **Snowflake** directly. Every figure above is the result of the "
            "query shown in `streamlit/app.py`, run against the dbt marts."
        )
    else:
        st.markdown(
            "Reading the **committed snapshot** in `data/marts/`. No warehouse "
            "credentials are present, which is how the public deployment runs.\n\n"
            "The snapshot is *regenerated* from the raw Olist CSVs by "
            "`analysis/build_snapshot.py`, a pandas re-implementation of the same dbt "
            "models — not exported from Snowflake. The marts agree with the warehouse "
            "run on the figures that carry the findings; `data/marts/README.md` records "
            "where they do not. Add credentials and the identical charts read the "
            "warehouse instead."
        )

    st.divider()

    meta = fetch("meta", f"""
        select
            (select max(purchased_at) from {MART}.fact_orders)               as latest_order,
            (select count(distinct order_id) from {DATABASE}.raw.raw_orders) as raw_orders,
            (select count(distinct order_id) from {MART}.fact_orders)        as mart_orders
    """).iloc[0]

    a, b, c = st.columns(3)
    a.metric("Latest order", f"{pd.to_datetime(meta.latest_order):%Y-%m-%d}")
    b.metric("Orders in RAW", f"{int(meta.raw_orders):,}")
    c.metric("Orders in MART", f"{int(meta.mart_orders):,}")

    gap = int(meta.raw_orders) - int(meta.mart_orders)
    st.caption(
        f"The {gap:,}-order gap is expected: `fact_orders` joins to order items, so orders "
        "with no line item are absent by design. The pipeline alarms on a change to this "
        "gap rather than on the gap itself."
    )

    st.caption(
        "Trend analysis elsewhere in this project is trimmed to Jan 2017 – Aug 2018. "
        "The dataset's first and last months are sparse and would otherwise read as a "
        "collapse in demand."
    )

st.caption(
    "Business logic lives in dbt and is covered by 123 automated tests. This app only "
    "presents. Source: github.com/hannah-vp/brazilcommerce-360"
)
