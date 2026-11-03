-- Simulation ground truth: used only for evaluation marts, never for scoring.
select transaction_id, tenant_id, is_fraud, scenario
from {{ source('aegis', 'simulation_labels') }}
