FROM python:3.12-slim-bullseye

WORKDIR /app

COPY pyproject.toml poetry.lock* README.md ./

RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root

COPY src/ ./src/

# 🔑 Torna o módulo src visível para o Python
ENV PYTHONPATH=/app

RUN useradd -m -u 1000 titlis && chown -R titlis:titlis /app
USER titlis

ENTRYPOINT ["kopf", "run", "--standalone", "--all-namespaces", "--liveness=http://0.0.0.0:8080/healthz", "-m", "src.main"]
