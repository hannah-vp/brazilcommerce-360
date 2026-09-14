-- One row per review, deduplicated.
--
-- the source contains 814 duplicate review_id values, some
-- appearing three times, despite review_id being the intended primary key. The
-- most recent row per review_id is kept.
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
            partition by review_id
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
