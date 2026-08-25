"""
BrazilCommerce 360 — dashboard

Reads the dbt insight marts directly. All business logic lives in dbt, where it
is tested and version-controlled; this file only presents. Each chart carries a
caption stating the takeaway and the action, because a chart without a "so what"
is decoration.

Run locally:
    streamlit run streamlit/app.py

Deploy:
    push to GitHub, connect the repo at share.streamlit.io, and paste the
    [snowflake] block from .streamlit/secrets.toml into the Secrets box.
"""

from __future__ import annotations

import os

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


# ---------------------------------------------------------------------------
# Connection
#
# Credentials come from st.secrets locally and from the Secrets box on
# Streamlit Cloud. If they are missing the app says so plainly rather than
# falling back to hardcoded figures — a dashboard showing stale numbers it
# claims are live is worse than one that admits it cannot connect.
# ---------------------------------------------------------------------------

@st.cache_resource
def get_connection():
    import snowflake.connector

    try:
        creds = dict(st.secrets["snowflake"])
    except (KeyError, FileNotFoundError):
        st.error(
            "**No Snowflake credentials found.**\n\n"
            "Create `.streamlit/secrets.toml` from the template in this repo, "
            "or add the `[snowflake]` block to the Secrets box on Streamlit Cloud."
        )
        st.stop()

    return snowflake.connector.connect(**creds)


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str) -> pd.DataFrame:
    """Run a query and return a dataframe with lower-case column names."""
    cur = get_connection().cursor()
    try:
        cur.execute(sql)
        df = cur.fetch_pandas_all()
    finally:
        cur.close()
    df.columns = [c.lower() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("BrazilCommerce 360")
st.markdown(
    "Olist Brazilian marketplace · September 2016 – October 2018 · "
    "99,441 orders across 96,096 customers"
)

st.info(
    "**The lever is the promise, not the parcel.** Orders that miss the promised "
    "delivery date draw a bad review 54% of the time against 9% for on-time "
    "orders — a 5.9× difference. Remote states with honest estimates score well; "
    "closer states with unreliable ones score worst. Because 97% of customers "
    "never return, that review is the last interaction."
)

kpis = q(f"""
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
    ret = q(f"""
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
    st.markdown("#### So what")
    st.markdown(
        "**96.88%** of customers ordered exactly once. There is no repeat-purchase "
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
    speed = q(f"""
        select bucket, orders, avg_review_score, pct_bad_review
        from {MART}.mart_delivery_satisfaction
        where lens = 'speed'
        order by bucket_order
    """)

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
    promise = q(f"""
        select bucket, orders, avg_review_score, pct_bad_review
        from {MART}.mart_delivery_satisfaction
        where lens = 'promise'
        order by bucket_order
    """)

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
    f"**So what:** Olist already pads its estimates, and it works — {int(ontime.orders):,} "
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

geo = q(f"""
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

st.info(
    "**So what:** the colour, not the position, tells the story. Amapá is the slowest state "
    "in the country at 27 days and still scores 4.24★, because only 4.5% of its orders arrive "
    "late. Alagoas is *faster* and scores worst at 3.86★, because 23% miss the promise. "
    "Distance is survivable when the estimate is honest.\n\n"
    "**→ Action:** recalibrate delivery estimates per state from observed performance rather "
    "than a national default. For Alagoas, Sergipe and Pará this is a pricing-page change, not "
    "a logistics investment."
)

st.divider()


# ---------------------------------------------------------------------------
# 4 — Customer value
# ---------------------------------------------------------------------------

st.subheader("4 · Value is concentrated, but not through loyalty")

left, right = st.columns([2, 1])

with left:
    seg = q(f"""
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
    st.markdown("#### So what")
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
    dist = q(f"""
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
    st.markdown("#### So what")
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

risk = q(f"""
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
        "Test ROC AUC 0.684 against a 12.8% base rate."
    )

with right:
    st.markdown("#### So what")
    st.markdown(
        "Lateness dominates the model at **3.49× odds**; the other features sit near "
        "neutral. It is not slowness that predicts a bad review, it is a missed "
        "commitment.\n\n"
        "The **Very High** bucket holds ~8,200 orders where **52% actually leave a bad "
        "review** — four times the base rate.\n\n"
        "**→ Action:** trigger outreach on that bucket before the review request is sent. "
        "At 8,200 orders the volume is operationally tractable."
    )

st.divider()


# ---------------------------------------------------------------------------
# Footer — freshness and reconciliation
# ---------------------------------------------------------------------------

with st.expander("Data freshness and pipeline reconciliation"):
    meta = q(f"""
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
