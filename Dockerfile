# Simulation mode of the whole app (for judges without a Mac). Power numbers here are SIMULATED or ESTIMATED,
# never MEASURED: a Linux container cannot read the Mac's power sensors.
FROM python:3.12-slim
WORKDIR /app
COPY joule/ ./joule/
COPY tests/ ./tests/
ENV PYTHONUNBUFFERED=1 JOULE_DATA=/data JOULE_CLOUD_URL=http://cloud:8787 JOULE_LLM_BASE_URL=http://host.docker.internal:11434
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "joule"]
CMD ["status"]
