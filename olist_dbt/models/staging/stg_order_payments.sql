-- One row per payment. An order may have several rows (split payments), so
-- 103,886 rows cover 99,440 orders. Sum to order level before joining.
--
-- payment_type contains three rows of 'not_defined',
-- a placeholder rather than a payment method. Mapped to 'unknown' so the
-- accepted_values test can enforce a closed set.

with source as (

    select * from {{ source('raw', 'raw_order_payments') }}

),

final as (

    select
        order_id,
        try_to_number(payment_sequential)       as payment_sequence,

        case
            when payment_type = 'not_defined' then 'unknown'
            else payment_type
        end                                     as payment_type,

        try_to_number(payment_installments)     as installments,
        try_to_decimal(payment_value, 10, 2)    as payment_value

    from source

)

select * from final
