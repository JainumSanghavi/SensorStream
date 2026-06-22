"""Observability wiring: Prometheus metrics + OpenTelemetry tracing.

`setup_observability(app)` does two things:

1. Exposes a Prometheus `/metrics` endpoint (text exposition format) and
   auto-instruments every route with request-rate, latency-histogram, and
   in-flight metrics. Custom business metrics declared in app/metrics.py ride
   the same default registry, so they show up on the same endpoint.

2. Optionally turns on distributed tracing. Tracing is enabled only when
   `OTEL_EXPORTER_OTLP_ENDPOINT` is set (e.g. a local Jaeger via docker
   compose); otherwise it is a no-op so local runs and the test suite need no
   collector. The whole block is defensive -- a tracing misconfiguration must
   never stop the API from serving traffic.
"""
import logging
import os

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

logger = logging.getLogger("sensorstream")


def setup_observability(app: FastAPI) -> None:
    # Prometheus: instrument all routes and expose /metrics.
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    _setup_tracing(app)


def _setup_tracing(app: FastAPI) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return  # tracing disabled -- no collector configured

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from app.db import engine

        provider = TracerProvider(
            resource=Resource.create({"service.name": "sensorstream"})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        # Instrument the async engine's underlying sync engine.
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("OpenTelemetry tracing enabled, exporting to %s", endpoint)
    except Exception:  # pragma: no cover - never let tracing break the app
        logger.exception("Failed to initialise OpenTelemetry tracing; continuing without it")
