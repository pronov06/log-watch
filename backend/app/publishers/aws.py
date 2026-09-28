"""Shared boto3 client factory for all AWS publishers."""

from __future__ import annotations

# The Dispatcher already retries with backoff, so botocore gets only a short
# budget of its own; otherwise one outage would stall the publish queue for ~20 s.
_CLIENT_CONFIG = dict(
    connect_timeout=3,
    read_timeout=5,
    retries={"max_attempts": 2, "mode": "standard"},
)


def make_client(service: str, region: str, endpoint_url: str | None = None):
    import boto3
    from botocore.config import Config

    kwargs = {"region_name": region, "config": Config(**_CLIENT_CONFIG)}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client(service, **kwargs)
