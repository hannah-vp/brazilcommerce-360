-- One row per (review_id, order_id).
--
-- review_id is NOT the grain. 814 rows share a review_id with another row, some
-- appearing three times — but every one of those pairs is attached to a
-- different order_id, and (review_id, order_id) is unique across all 99,224
-- source rows.
--
-- Deduplicating on review_id alone therefore deleted 814 legitimate rows and
-- left 550 orders with no review at all, while every test still passed: the
-- `unique` test on review_id was satisfied precisely because the rows had been
-- removed. The test was checking the output of the bug, not the input to it.
--
-- The row_number guard is kept rather than dropped, so a genuine duplicate pair
-- in a future load cannot pass through silently.
--
-- 8,320 reviews were created before the order was
-- delivered. This is expected behaviour — Olist requests the review at dispatch
-- rather than on arrival — so those rows are kept and flagged rather than
-- filtered.

with source as (

    select * from {{ source('raw', 'raw_order_reviews') }}

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by review_id, order_id
            order by review_answer_timestamp desc nulls last
        ) as row_num
    from source

),

final as (

    select
        review_id,
        order_id,
        try_to_number(review_score)                                     as review_score,
        nullif(trim(review_comment_title), '')                          as review_title,
        nullif(trim(review_comment_message), '')                        as review_message,
        try_to_timestamp(review_creation_date,    'YYYY-MM-DD HH24:MI:SS') as review_created_at,
        try_to_timestamp(review_answer_timestamp, 'YYYY-MM-DD HH24:MI:SS') as review_answered_at

    from deduplicated
    where row_num = 1

)

select * from final
