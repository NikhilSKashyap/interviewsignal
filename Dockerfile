FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e . --no-deps --quiet

EXPOSE 8080

ENV RELAY_PORT=8080
ENV RELAY_DATA_DIR=/data

CMD ["python", "-m", "interview.relay.server"]
