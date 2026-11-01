"""Exact-origin CORS configuration for browser clients."""
import importlib
from fastapi.testclient import TestClient

def test_project_one_origin_is_allowed_but_other_origins_are_not(monkeypatch):
    import api
    monkeypatch.setenv("ORACLE_ARC_CORS_ORIGINS","https://console.example.test")
    module=importlib.reload(api)
    client=TestClient(module.app)
    allowed=client.options("/v1/platform/identity",headers={
        "Origin":"https://console.example.test",
        "Access-Control-Request-Method":"GET",
        "Access-Control-Request-Headers":"authorization",
    })
    assert allowed.status_code==200
    assert allowed.headers.get("access-control-allow-origin")=="https://console.example.test"
    denied=client.options("/v1/platform/identity",headers={
        "Origin":"https://attacker.example",
        "Access-Control-Request-Method":"GET",
        "Access-Control-Request-Headers":"authorization",
    })
    assert denied.headers.get("access-control-allow-origin") is None
    monkeypatch.delenv("ORACLE_ARC_CORS_ORIGINS",raising=False)
    importlib.reload(api)
