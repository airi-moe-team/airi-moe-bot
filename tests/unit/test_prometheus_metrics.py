"""Parser mínimo y puro para snapshots Prometheus del benchmark."""

from airi.observability.prometheus_metrics import (
    diff_prometheus_metrics,
    parse_prometheus_text,
)


def test_parse_prometheus_samples_and_keep_metric_type_and_labels():
    snapshot = parse_prometheus_text(
        '# HELP llama_requests_total Calls handled\n'
        '# TYPE llama_requests_total counter\n'
        'llama_requests_total{slot="0",model="qwen"} 10\n'
        '# TYPE llama_queue gauge\n'
        'llama_queue 2\n'
    )

    request = snapshot[("llama_requests_total", (("model", "qwen"), ("slot", "0")))]
    assert request.value == 10
    assert request.metric_type == "counter"
    assert snapshot[("llama_queue", ())].metric_type == "gauge"


def test_parse_escaped_labels_and_ignore_comments_invalid_and_nonfinite_values():
    snapshot = parse_prometheus_text(
        '# TYPE llama_label gauge\n'
        'llama_label{note="line\\nquote\\\"",ok="yes"} 1.25 123456\n'
        'llama_label{bad="unterminated} 2\n'
        'llama_label NaN\n'
        '# EOF\n'
    )

    item = snapshot[("llama_label", (("note", 'line\nquote"'), ("ok", "yes")))]
    assert item.value == 1.25
    assert len(snapshot) == 1


def test_diff_matches_series_by_labels_and_marks_counter_reset():
    before = parse_prometheus_text(
        '# TYPE requests_total counter\n'
        'requests_total{slot="0"} 10\n'
        'requests_total{slot="1"} 20\n'
        '# TYPE queue gauge\n'
        'queue 3\n'
    )
    after = parse_prometheus_text(
        '# TYPE requests_total counter\n'
        'requests_total{slot="0"} 13\n'
        'requests_total{slot="1"} 2\n'
        '# TYPE queue gauge\n'
        'queue 1\n'
        'new_metric 8\n'
    )

    deltas = diff_prometheus_metrics(before, after)
    by_series = {(d["name"], tuple(d["labels"].items())): d for d in deltas}

    assert by_series[("requests_total", (("slot", "0"),))]["delta"] == 3
    reset = by_series[("requests_total", (("slot", "1"),))]
    assert reset["counter_reset"] is True
    assert reset["delta"] is None
    assert by_series[("queue", ())]["delta"] == -2
    assert len(deltas) == 3
