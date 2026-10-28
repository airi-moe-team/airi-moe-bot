"""Parser pequeño para snapshots text/plain del endpoint Prometheus."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

_NAME = r"[a-zA-Z_:][a-zA-Z0-9_:]*"
_SAMPLE_RE = re.compile(
    rf"^(?P<name>{_NAME})(?:\{{(?P<labels>.*)\}})?\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+-]Inf|NaN)"
    r"(?:\s+\d+)?\s*$"
)
_TYPE_RE = re.compile(rf"^#\s*TYPE\s+(?P<name>{_NAME})\s+(?P<type>\w+)\s*$")
_LABEL_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_SUFFIXES = ("_bucket", "_sum", "_count", "_created")


@dataclass(frozen=True)
class PrometheusMetric:
    name: str
    labels: tuple[tuple[str, str], ...]
    value: float
    metric_type: str | None = None


def _parse_labels(source: str | None) -> tuple[tuple[str, str], ...] | None:
    if not source:
        return ()
    labels = []
    index = 0
    decoder = json.JSONDecoder()
    while index < len(source):
        while index < len(source) and (source[index].isspace() or source[index] == ","):
            index += 1
        if index == len(source):
            break
        match = _LABEL_NAME_RE.match(source, index)
        if match is None:
            return None
        name = match.group(0)
        index = match.end()
        while index < len(source) and source[index].isspace():
            index += 1
        if index >= len(source) or source[index] != "=":
            return None
        index += 1
        while index < len(source) and source[index].isspace():
            index += 1
        try:
            value, index = decoder.raw_decode(source, index)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(value, str):
            return None
        labels.append((name, value))
        while index < len(source) and source[index].isspace():
            index += 1
        if index < len(source):
            if source[index] != ",":
                return None
            index += 1
    return tuple(sorted(labels))


def _family_type(metric_name: str, declared_types: dict[str, str]) -> str | None:
    if metric_name in declared_types:
        return declared_types[metric_name]
    for suffix in _SUFFIXES:
        if metric_name.endswith(suffix):
            return declared_types.get(metric_name[: -len(suffix)])
    return None


def parse_prometheus_text(text: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], PrometheusMetric]:
    """Parsea samples numéricos y conserva el tipo y labels de cada serie."""
    declared_types: dict[str, str] = {}
    lines = text.splitlines()
    for line in lines:
        type_match = _TYPE_RE.match(line.strip())
        if type_match:
            declared_types[type_match.group("name")] = type_match.group("type")

    samples = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if match is None:
            continue
        labels = _parse_labels(match.group("labels"))
        if labels is None:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        name = match.group("name")
        metric = PrometheusMetric(
            name=name,
            labels=labels,
            value=value,
            metric_type=_family_type(name, declared_types),
        )
        samples[(name, labels)] = metric
    return samples


def diff_prometheus_metrics(before: dict, after: dict) -> list[dict]:
    """Compara solo series observadas en ambos snapshots con labels idénticos."""
    deltas = []
    for key in sorted(before.keys() & after.keys(), key=repr):
        previous = before[key]
        current = after[key]
        counter_reset = (
            previous.metric_type == "counter" and current.value < previous.value
        )
        deltas.append(
            {
                "name": current.name,
                "labels": dict(current.labels),
                "metric_type": current.metric_type,
                "before": previous.value,
                "after": current.value,
                "delta": None if counter_reset else current.value - previous.value,
                "counter_reset": counter_reset,
            }
        )
    return deltas
