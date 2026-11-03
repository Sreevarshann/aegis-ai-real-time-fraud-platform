-- Hourly transaction volume, value and alerting per tenant (event time).
select
    t.tenant_id,
    t.event_hour as hour,
    count(*) as transactions,
    sum(t.amount_usd) as total_amount_usd,
    count(*) filter (where p.is_alert) as alerts,
    round(avg(p.risk_score)::numeric, 2) as avg_risk_score,
    count(*) filter (where t.is_late) as late_events
from {{ ref('stg_transactions') }} t
left join {{ ref('stg_predictions') }} p using (transaction_id)
group by 1, 2
