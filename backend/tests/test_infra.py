"""Contract tests: infra (CloudFormation, IAM, compose) must match what the code publishes."""

from pathlib import Path

import yaml

from app.config import Settings
from app.publishers.metrics import MetricsReporter, NAMESPACE

INFRA = Path(__file__).resolve().parents[2] / "infra"


class _CfnLoader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node)}
    return {suffix: loader.construct_mapping(node)}


_CfnLoader.add_multi_constructor("!", _tag)


def _template() -> dict:
    return yaml.load((INFRA / "cloudformation.yaml").read_text(encoding="utf-8"), Loader=_CfnLoader)


def test_template_resources_match_app_defaults():
    t = _template()
    res = t["Resources"]
    cfg = Settings()
    assert res["LogGroup"]["Properties"]["LogGroupName"] == cfg.cw_log_group
    assert res["LogStream"]["Properties"]["LogStreamName"] == cfg.cw_log_stream
    assert res["AlertSnsTopic"]["Properties"]["TopicName"] == "log-anomaly-alerts"
    assert t["Parameters"]["MetricsNamespace"]["Default"] == NAMESPACE


def test_alarms_watch_metrics_the_reporter_actually_sends():
    res = _template()["Resources"]
    reporter = MetricsReporter("ap-south-1")
    sent = {d["MetricName"]: d["Dimensions"] for d in
            reporter.build_metric_data([{"error_rate": 0.1, "z": 1.0, "events_per_sec": 5.0}])}
    for name in ("ErrorRateAlarm", "DetectorSilentAlarm"):
        props = res[name]["Properties"]
        assert props["MetricName"] in sent, props["MetricName"]
        assert props["Dimensions"] == sent[props["MetricName"]]
        assert props["AlarmActions"] == [{"Ref": "AlertSnsTopic"}]
    assert res["DetectorSilentAlarm"]["Properties"]["TreatMissingData"] == "breaching"


def test_iam_policies_are_least_privilege():
    import json
    for doc in (
        json.loads((INFRA / "iam-policy.json").read_text()),
        _template()["Resources"]["DetectorPublishPolicy"]["Properties"]["PolicyDocument"],
    ):
        actions = set()
        for st in doc["Statement"]:
            a = st["Action"]
            actions.update(a if isinstance(a, list) else [a])
            assert st["Effect"] == "Allow"
            if st["Resource"] == "*":  # PutMetricData has no resource ARN: must be namespace-scoped
                assert list(st["Condition"]["StringEquals"].keys()) == ["cloudwatch:namespace"]
        assert actions == {"logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                           "sns:Publish", "cloudwatch:PutMetricData"}
        assert not any("*" == a or a.endswith(":*") for a in actions)


def test_compose_is_valid_and_hardened():
    compose = yaml.safe_load((INFRA.parent / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]
    assert svc["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    env = svc["backend"]["environment"]
    assert env["LOG_SOURCES"].startswith("${LOG_SOURCES")
    assert any(v.endswith(":ro") for v in svc["backend"]["volumes"])  # host logs mounted read-only
    for df in ("backend/Dockerfile", "frontend/Dockerfile"):
        text = (INFRA.parent / df).read_text(encoding="utf-8")
        assert "USER " in text or "nginx-unprivileged" in text, f"{df} runs as root"
        assert "HEALTHCHECK" in text  # compose's service_healthy relies on these
