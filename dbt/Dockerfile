FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 DBT_SEND_ANONYMOUS_USAGE_STATS=false
WORKDIR /dbt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10002 dbt
COPY . .
RUN chown -R dbt:dbt /dbt
USER dbt
CMD ["./run.sh"]
