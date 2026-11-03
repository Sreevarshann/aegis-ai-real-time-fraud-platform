-- The hourly mart must account for every staged transaction (no rows lost or double counted).
with mart as (select tenant_id, sum(transactions) as n from {{ ref('fct_hourly_volume') }} group by 1),
src as (select tenant_id, count(*) as n from {{ ref('stg_transactions') }} group by 1)
select src.tenant_id, src.n as source_rows, mart.n as mart_rows
from src full outer join mart using (tenant_id)
where coalesce(src.n, -1) <> coalesce(mart.n, -1)
