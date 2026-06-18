import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from palpitaria.config import settings
from palpitaria.services import pipeline_trigger as pt


def _make_request(timestamp: str, signature: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": pt.TRIGGER_PATH,
        "headers": [
            (b"x-pipeline-timestamp", timestamp.encode()),
            (b"x-pipeline-signature", signature.encode()),
        ],
    }
    return Request(scope)


def test_verify_trigger_request_accepts_valid_signature(monkeypatch):
    secret = "x" * 40
    monkeypatch.setattr(settings, "pipeline_trigger_secret", secret)
    ts = str(int(time.time()))
    payload = f"{ts}\nPOST\n{pt.TRIGGER_PATH}\n"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    pt.verify_trigger_request(_make_request(ts, sig))


def test_verify_trigger_request_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_trigger_secret", "y" * 40)
    ts = str(int(time.time()))
    with pytest.raises(HTTPException) as exc:
        pt.verify_trigger_request(_make_request(ts, "deadbeef"))
    assert exc.value.status_code == 401


def test_verify_trigger_request_rejects_old_timestamp(monkeypatch):
    secret = "z" * 40
    monkeypatch.setattr(settings, "pipeline_trigger_secret", secret)
    ts = str(int(time.time()) - 9999)
    payload = f"{ts}\nPOST\n{pt.TRIGGER_PATH}\n"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(HTTPException) as exc:
        pt.verify_trigger_request(_make_request(ts, sig))
    assert exc.value.status_code == 401
