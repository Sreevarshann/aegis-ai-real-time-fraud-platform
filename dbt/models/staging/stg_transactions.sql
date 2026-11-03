-- One row per persisted transaction, amounts normalised to USD.
select
    t.transaction_id,
    t.tenant_id,
    t.event_timestamp,
    t.ingested_at,
    date_trunc('hour', t.event_timestamp) as event_hour,
    t.event_timestamp::date as event_date,
    t.customer_id,
    t.merchant_id,
    t.merchant_category,
    t.amount,
    t.currency,
    round(t.amount * fx.usd_per_unit, 2) as amount_usd,
    t.country,
    t.device_id,
    t.payment_channel,
    t.status,
    t.is_late
from {{ source('aegis', 'transactions') }} t
left join {{ ref('fx_rates') }} fx on fx.currency = t.currency
