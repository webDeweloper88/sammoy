FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY app ./app
COPY supervisor.conf /etc/supervisor.conf
COPY tests ./tests
COPY entrypoint.py ./
RUN useradd --uid 10001 --create-home reports && mkdir /data && chown reports:reports /data
USER reports
ENV RTU_WASH_REPORTS_ENV=/data/reports.env PYTHONUNBUFFERED=1
CMD ["python", "entrypoint.py"]
