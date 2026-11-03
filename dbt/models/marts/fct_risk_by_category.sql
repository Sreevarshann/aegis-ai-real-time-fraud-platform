select
    t.tenant_id,
    t.merchant_category,
    count(*) as transactions,
    round(avg(p.risk_score)::numeric, 2) as avg_risk_score,
    round((count(*) filter (where p.risk_category in ('high', 'critical')))::numeric / count(*), 4) as high_risk_share,
    count(*) filter (where p.is_alert) as alerts,
    sum(t.amount_usd) as total_amount_usd
from {{ ref('stg_transactions') }} t
join {{ ref('stg_predictions') }} p using (transaction_id)
group by 1, 2
