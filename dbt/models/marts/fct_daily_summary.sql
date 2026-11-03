select
    t.tenant_id,
    t.event_date as day,
    count(*) as transactions,
    count(distinct t.customer_id) as customers,
    count(distinct t.merchant_id) as merchants,
    sum(t.amount_usd) as total_amount_usd,
    round(avg(t.amount_usd), 2) as avg_amount_usd,
    round((count(*) filter (where t.status = 'declined'))::numeric / count(*), 4) as declined_share,
    round((count(*) filter (where t.is_late))::numeric / count(*), 4) as late_share,
    count(*) filter (where p.is_alert) as alerts
from {{ ref('stg_transactions') }} t
left join {{ ref('stg_predictions') }} p using (transaction_id)
group by 1, 2
