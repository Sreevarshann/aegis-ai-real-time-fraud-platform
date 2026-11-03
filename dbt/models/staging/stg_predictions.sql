select
    p.prediction_id,
    p.transaction_id,
    p.tenant_id,
    p.model_version_id,
    p.risk_score,
    p.probability,
    p.risk_category,
    p.scored_at,
    a.alert_id,
    a.status as alert_status,
    (a.alert_id is not null) as is_alert
from {{ source('aegis', 'risk_predictions') }} p
left join {{ source('aegis', 'risk_alerts') }} a on a.transaction_id = p.transaction_id
