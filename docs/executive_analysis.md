# BrazilCommerce 360 — Executive Analysis

**Dataset:** Olist Brazilian marketplace, September 2016 – October 2018
99,441 orders · 96,096 customers · R$13.6M GMV · 32,951 products · 3,095 sellers

Every figure below is queried from the tested dbt marts in `ECOMMERCE_DEV`, not
computed ad hoc. Each finding names the model it comes from, so any number can be
reproduced with a single `select`.

---

## Summary

Olist is an acquisition business whose growth is limited by delivery promises it
cannot keep in the states where it has no sellers. Because 97% of customers never
return, a broken promise on the first order is the whole customer relationship.

The single most actionable finding: **orders that miss the promised delivery date
receive a bad review 54% of the time, against 9% for orders that arrive on time —
a 5.9× difference.** Raw delivery speed matters far less than whether the estimate
was honoured.

---

## Finding 1 — Growth depends entirely on acquisition

*Source: `mart_retention`*

| Orders placed | Customers | Share |
|---|---|---|
| 1 | 93,099 | 96.88% |
| 2 | 2,745 | 2.86% |
| 3+ | 252 | 0.26% |

Only 3.12% of customers ever placed a second order.

**Why it matters.** There is no repeat-purchase flywheel to absorb a bad
experience. Every dissatisfied customer is permanently lost revenue, because
there is no second transaction in which to recover them.

**Recommendation.** Treat the first order as the entire customer relationship.
Investment in first-order reliability returns more than any retention campaign,
because there is currently no retention behaviour to amplify.

---

## Finding 2 — The promise matters more than the clock

*Source: `mart_delivery_satisfaction`*

Delivery speed degrades satisfaction steadily:

| Delivery time | Orders | Avg review | Bad reviews |
|---|---|---|---|
| 1–7 days | 30,496 | 4.41★ | 7.5% |
| 8–14 days | 37,683 | 4.30★ | 9.0% |
| 15–21 days | 16,009 | 4.12★ | 12.1% |
| 22+ days | 11,413 | 3.06★ | 39.9% |

But splitting by whether the *promised* date was met is far sharper:

| | Orders | Avg review | Bad reviews |
|---|---|---|---|
| On time or early | 87,969 | 4.30★ | **9.2%** |
| Late vs promise | 7,632 | 2.57★ | **54.1%** |

Late orders miss the promise by an average of 8.8 days and are **5.9× more likely
to receive a 1–2 star review**.

**Why it matters.** Olist already pads its delivery estimates, and the padding
works — 92% of orders beat the quoted date and average 4.30★. The damage is
concentrated in the 8% that miss an already-generous estimate.

**Recommendation.** Alarm on late-vs-promise rate, not average delivery days.
Any route or seller exceeding a 10% late rate should be flagged for
intervention. Extending quoted lead times in unreliable lanes would cost nothing
and convert late arrivals into on-time ones.

---

## Finding 3 — Remote is fine; unpredictable is not

*Source: `mart_geographic_chain`*

The five slowest states separate into two very different groups:

| State | Avg days | Avg review | % late vs promise | Local sellers |
|---|---|---|---|---|
| Amapá (AP) | 27.1 | 4.24★ | 4.5% | 0 |
| Amazonas (AM) | 26.4 | 4.22★ | 4.2% | 1 |
| Alagoas (AL) | 24.4 | **3.86★** | **23.3%** | 0 |
| Pará (PA) | 23.6 | 3.92★ | 11.9% | 1 |
| Sergipe (SE) | 21.4 | 3.90★ | 15.1% | 2 |

Amapá is the slowest state in the country and still scores 4.24★, because its
estimates are honest — only 4.5% of orders arrive late. Alagoas is *faster* and
scores materially worse, because nearly a quarter of its orders miss the promise.

**Why it matters.** This overturns the intuitive reading. Distance itself does
not damage satisfaction; customers accept a long wait they were warned about.
What damages satisfaction is a lead time the operation cannot hit.

**Recommendation.** Recalibrate delivery estimates per state using observed
performance rather than a national default. For Alagoas, Sergipe and Pará this is
a pricing-page change, not a logistics investment, and would move roughly 15–23%
of orders out of the late bucket immediately. Seller acquisition in the four
states with no local supply is the longer-term structural fix.

---

## Finding 4 — Value is concentrated, but not through loyalty

*Source: `mart_customer_segments`*

| Tier | Customers | Avg spend | Avg orders | % of revenue |
|---|---|---|---|---|
| Top 1% | 955 | R$1,640.60 | 1.09 | 11.5% |
| Top 10% | 8,593 | R$470.05 | 1.11 | 29.7% |
| Next 40% | 38,175 | R$150.04 | 1.04 | 42.1% |
| Bottom 50% | 47,697 | R$47.34 | 1.01 | 16.6% |

The top 11% of customers generate 41.2% of revenue.

**The detail that changes the interpretation.** Average orders per customer is
1.09 in the top 1% and 1.01 in the bottom half — essentially identical.
High-value customers are not buying more often; they are placing a single, much
larger order. The top 1% spends 35× the bottom 50% in what is, for nearly all of
them, one transaction.

**Recommendation.** Do not build a loyalty programme against this pattern; there
is no repeat behaviour to reward. Identify high-basket orders *at checkout* and
route them to the most reliable fulfilment lanes. A late delivery on a R$1,600
single-shot order is a disproportionate loss.

---

## Finding 5 — The average review score is a misleading KPI

*Source: `mart_review_distribution`*

| Score | Reviews | Share |
|---|---|---|
| 5★ | 56,910 | 57.8% |
| 4★ | 19,007 | 19.3% |
| 3★ | 8,097 | 8.2% |
| 2★ | 3,114 | 3.2% |
| 1★ | 11,282 | 11.5% |

The distribution is bimodal and non-monotonic: 1-star reviews are more common
than 2-star and 3-star combined. Only 30.7% of reviews fall anywhere in the 2–4
range.

**Why it matters.** The mean of 4.09 describes an experience almost no customer
actually had. Worse, it is insensitive: a rise in 1-star reviews can be offset by
a rise in 5-star reviews and leave the mean unchanged for months.

**Recommendation.** Adopt **percentage of 1-star reviews** as the operational
health metric. It moves earlier than the mean and maps directly to the churn risk
that matters in a business with no repeat purchase.

---

## Predictive model — flagging bad reviews before they happen

*Source: `analysis/risk_model.py`, scores in `MART.review_risk_scores`*

A logistic regression trained on 95,601 scored orders, using only features known
at delivery time.

**Feature effects (odds ratios):**

| Feature | Odds ratio |
|---|---|
| `is_late` | **3.49×** |
| `days_late` | 1.07× |
| `delivery_days` | 1.04× |
| `freight_ratio` | 1.09× |

Lateness dominates. The other three features are close to neutral once lateness
is accounted for, which is itself the finding: it is not slowness that predicts a
bad review, it is a missed commitment.

**Performance:** test ROC AUC 0.684, average precision 0.388, against a 12.8%
base rate. Modest, and reported as such — the model is useful because of where
its confidence concentrates, not because of its overall discrimination.

**Bucket calibration:**

| Risk bucket | Orders | Actually bad |
|---|---|---|
| Medium | 49,445 | 7.9% |
| High | 37,981 | 10.7% |
| Very High | 8,175 | **52.0%** |

The Very High bucket contains 8.5% of orders and captures a population where more
than half will leave a bad review — **four times the base rate**.

**Recommendation.** Trigger proactive outreach on the Very High bucket:
notification, apology, or a goodwill credit issued before the review request is
sent. At 8,175 orders this is an operationally tractable volume.

**Model choice.** Logistic regression was chosen over a gradient-boosted model
deliberately. A tree would likely improve AUC by a few points and would not
produce the odds ratio above, which is the number that supports the
recommendation. Interpretability was worth more than accuracy here.

**Limitations.** No order scored below 0.2 probability, so the model produces no
Low bucket — it separates high risk from ordinary risk, not high from negligible.
It is also trained on delivered orders with reviews only, so it does not
generalise to cancelled orders or silent customers.

---

## The chain

The five findings are one causal sequence:

1. Four states have customers and no local sellers, so orders travel far.
2. Distance is survivable when the estimate is honest — Amapá waits 27 days and
   still gives 4.24★.
3. Where the estimate is *not* honest, satisfaction collapses: Alagoas is faster
   than Amapá and scores 0.38★ lower, because 23% of its orders arrive late.
4. Late orders draw a bad review 54% of the time, and bad reviews are
   overwhelmingly 1-star rather than middling.
5. Because 97% of customers never return, that review is the last interaction —
   and for the top decile, it lands on a single high-value order.

**The lever is the promise, not the parcel.** Recalibrating delivery estimates
per state costs nothing and addresses the largest single driver of
dissatisfaction in the dataset.

---

## Reproducing these figures

```sql
select * from ECOMMERCE_DEV.dbt_mart.mart_retention;
select * from ECOMMERCE_DEV.dbt_mart.mart_delivery_satisfaction order by lens, bucket_order;
select * from ECOMMERCE_DEV.dbt_mart.mart_geographic_chain order by avg_delivery_days desc;
select * from ECOMMERCE_DEV.dbt_mart.mart_customer_segments;
select * from ECOMMERCE_DEV.dbt_mart.mart_review_distribution;
select * from ECOMMERCE_DEV.dbt_mart.review_risk_scores;
```

Model metrics are written to `analysis/artifacts/metrics.json` on every training
run. Data quality decisions affecting these figures are documented in
`docs/data_quality_notes.md`.
