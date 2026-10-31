# Image for configured checks. Built ahead of time because checks run with no network:
#   docker build -t coding-harness-check:1 -f docker/check.Dockerfile target-repository
FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
COPY requirements.txt /tmp/target-requirements.txt
RUN pip install --no-cache-dir -r /tmp/target-requirements.txt && rm /tmp/target-requirements.txt
USER 1000:1000
