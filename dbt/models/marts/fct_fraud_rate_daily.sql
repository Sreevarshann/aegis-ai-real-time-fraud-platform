-- Daily simulated fraud rate vs. alert rate and alert precision (evaluation against simulator labels).
with joined as (
    select t.tenant_id, t.event_date, coalesce(l.is_fraud, false) as is_fraud, coalesce(p.is_alert, false) as is_alert
    from {{ ref('stg_transactions') }} t
    left join {{ ref('stg_labels') }} l using (transaction_id)
    left join {{ ref('stg_predictions') }} p using (transaction_id)
)
select
    tenant_id,
    event_date as day,
    count(*) as transactions,
    count(*) filter (where is_fraud) as labelled_fraud,
    count(*) filter (where is_alert) as alerts,
    count(*) filter (where is_fraud and is_alert) as true_positives,
    round((count(*) filter (where is_fraud))::numeric / count(*), 5) as simulated_fraud_rate,
    round((count(*) filter (where is_alert))::numeric / count(*), 5) as alert_rate,
    round((count(*) filter (where is_fraud and is_alert))::numeric
          / nullif(count(*) filter (where is_alert), 0), 4) as alert_precision
from joined
group by 1, 2
