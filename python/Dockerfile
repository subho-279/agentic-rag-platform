FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# uid 1000 matches the gateway image so the shared uploads volume has one owner.
RUN useradd -u 1000 -m app && mkdir -p /data/uploads && chown app /data/uploads

WORKDIR /app
COPY pyproject.toml ./
COPY ragplatform ./ragplatform
RUN pip install .

USER app
EXPOSE 8000
CMD ["uvicorn", "ragplatform.agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
