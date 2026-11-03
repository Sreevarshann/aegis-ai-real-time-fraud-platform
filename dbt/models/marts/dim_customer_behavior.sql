-- Behavioural statistics per customer observed by the streaming platform.
select
    t.tenant_id,
    t.customer_id,
    count(*) as transactions,
    sum(t.amount_usd) as total_amount_usd,
    round(avg(t.amount_usd), 2) as avg_amount_usd,
    round(stddev_samp(t.amount_usd), 2) as stddev_amount_usd,
    count(distinct t.device_id) as distinct_devices,
    count(distinct t.country) as distinct_countries,
    count(distinct t.merchant_id) as distinct_merchants,
    min(t.event_timestamp) as first_seen_at,
    max(t.event_timestamp) as last_seen_at,
    max(p.risk_score) as max_risk_score,
    count(*) filter (where p.is_alert) as alerts
from {{ ref('stg_transactions') }} t
left join {{ ref('stg_predictions') }} p using (transaction_id)
group by 1, 2
