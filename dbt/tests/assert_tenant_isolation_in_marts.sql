-- A prediction must never be attributed to a different tenant than its transaction.
select p.transaction_id
from {{ ref('stg_predictions') }} p
join {{ ref('stg_transactions') }} t using (transaction_id)
where p.tenant_id <> t.tenant_id
