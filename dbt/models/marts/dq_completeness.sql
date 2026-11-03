-- Data completeness and integrity checks, one row per tenant and check.
with t as (select * from {{ ref('stg_transactions') }}),
p as (select * from {{ ref('stg_predictions') }}),
checks as (
    select tenant_id, 'prediction_coverage' as check_name, count(*) as total_rows,
           count(*) filter (where p.transaction_id is null) as failing_rows
    from t left join p using (transaction_id, tenant_id) group by 1
    union all
    select tenant_id, 'fx_rate_available', count(*), count(*) filter (where amount_usd is null) from t group by 1
    union all
    select tenant_id, 'known_customer', count(*), count(*) filter (where c.customer_id is null)
    from t left join {{ source('aegis', 'customers') }} c using (tenant_id, customer_id) group by 1
    union all
    select tenant_id, 'not_late', count(*), count(*) filter (where is_late) from t group by 1
    union all
    select tenant_id, 'not_future_dated', count(*),
           count(*) filter (where event_timestamp > ingested_at + interval '5 minutes') from t group by 1
)
select
    tenant_id,
    check_name,
    total_rows,
    failing_rows,
    round(1 - failing_rows::numeric / nullif(total_rows, 0), 5) as pass_rate
from checks
