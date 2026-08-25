-- FINDING 4: the average review score is a misleading KPI.
--
-- Scores are bimodal — mostly 5s and 1s with little in between — so the mean
-- describes an experience almost no customer had. The percentage of 1-star
-- reviews is the more actionable health metric.

with reviews as (

    select * from {{ ref('stg_order_reviews') }}
    where review_score between 1 and 5

)

select
    review_score,
    count(*)                                                as reviews,
    round(count(*) * 100.0 / sum(count(*)) over (), 1)      as pct_of_reviews
from reviews
group by review_score
order by review_score
