"""Metrics and logs sent over OpenTelemetry's OTLP, to Grafana Cloud or any collector.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. The exporters read it, OTEL_EXPORTER_OTLP_HEADERS
and OTEL_RESOURCE_ATTRIBUTES themselves, as OpenTelemetry's own settings. Metrics become
Prometheus series in Grafana, and log lines go to Loki with their fields as attributes.
"""

import logging
import os
from collections.abc import Callable
from uuid import uuid4

from opentelemetry import metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from app.core.logs import FieldsFilter

ENDPOINT_VARIABLE = "OTEL_EXPORTER_OTLP_ENDPOINT"
NAMESPACE = "cadence"
# The exporters' own lines stay on stdout. Sent over OTLP, a failed export would log a line
# that's then sent, and fails, again.
_EXPORT_LOGGERS = ("opentelemetry", "urllib3", "requests")

# Instruments made before start_telemetry runs still count: OpenTelemetry hands out stand-ins
# that start recording once a real provider is set.
meter = metrics.get_meter(NAMESPACE)


class _NotExportLines(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(_EXPORT_LOGGERS)


def start_telemetry(service: str) -> Callable[[], None]:
    """Starts sending this process's metrics and logs, if an endpoint is set.

    Call it after configure_logging, which replaces the root logger's handlers. Returns what
    to call on shutdown, which sends what's left.
    """
    if not os.environ.get(ENDPOINT_VARIABLE):
        return lambda: None
    # Each process gets its own instance ID, or the API's workers and the job worker, which
    # share one container on Render, would report over each other's counts.
    resource = Resource.create(
        {
            "service.namespace": NAMESPACE,
            "service.name": service,
            "service.instance.id": uuid4().hex,
        }
    )
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]
    )
    metrics.set_meter_provider(meter_provider)
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    handler = LoggingHandler(logger_provider=logger_provider)
    handler.addFilter(FieldsFilter())
    handler.addFilter(_NotExportLines())
    logging.getLogger().addHandler(handler)

    def stop() -> None:
        logging.getLogger().removeHandler(handler)
        logger_provider.shutdown()
        meter_provider.shutdown()

    return stop
