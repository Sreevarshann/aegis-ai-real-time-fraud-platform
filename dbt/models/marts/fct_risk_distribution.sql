-- Distribution of high-risk scores in 10-point bands, including empty bands.
with bands as (
    select generate_series(0, 90, 10) as band_floor
), tenants as (
    select distinct tenant_id from {{ ref('stg_predictions') }}
), counts as (
    select tenant_id, least(floor(risk_score / 10) * 10, 90)::int as band_floor, count(*) as n
    from {{ ref('stg_predictions') }}
    group by 1, 2
)
select
    te.tenant_id,
    b.band_floor,
    b.band_floor || '-' || case when b.band_floor = 90 then 100 else b.band_floor + 9 end as score_band,
    coalesce(c.n, 0) as transactions,
    round(coalesce(c.n, 0)::numeric / nullif(sum(coalesce(c.n, 0)) over (partition by te.tenant_id), 0), 5) as share
from tenants te
cross join bands b
left join counts c on c.tenant_id = te.tenant_id and c.band_floor = b.band_floor
