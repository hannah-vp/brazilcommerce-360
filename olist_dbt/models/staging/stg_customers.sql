-- One row per order-customer record.
--
-- Data quality note 4: customer_id is issued per ORDER, not per person.
-- customer_unique_id is the person. 99,441 customer_ids map to 96,096 people.
-- Any retention, lifetime-value or segmentation logic must group on
-- customer_unique_id or it will report a repeat rate of zero.

with source as (

    select * from {{ source('raw', 'raw_customers') }}

),

final as (

    select
        customer_id,                                 -- per-order key
        customer_unique_id,                          -- the actual person
        customer_zip_code_prefix                as zip_prefix,
        lower(trim(customer_city))              as customer_city,
        upper(trim(customer_state))             as customer_state

    from source

)

select * from final
