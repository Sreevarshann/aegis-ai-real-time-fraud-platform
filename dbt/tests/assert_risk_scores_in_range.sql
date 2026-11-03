-- Every stored risk score must be an integer in [0, 100] and agree with its category band.
select prediction_id, risk_score, risk_category
from {{ ref('stg_predictions') }}
where risk_score not between 0 and 100
   or (risk_category = 'critical' and risk_score < 85)
   or (risk_category = 'high' and (risk_score < 60 or risk_score >= 85))
   or (risk_category = 'medium' and (risk_score < 30 or risk_score >= 60))
   or (risk_category = 'low' and risk_score >= 30)
