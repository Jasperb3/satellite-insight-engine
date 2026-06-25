from satviz.enrichment import orchestrator, tools
from satviz.models import Enrichment


def test_search_web_uses_hosted_when_key_present(monkeypatch):
    monkeypatch.setattr(tools.config, "OLLAMA_API_KEY", "k")
    monkeypatch.setattr(tools.config, "has_hosted_search", lambda: True)
    called = {}
    monkeypatch.setattr(tools, "_hosted_search", lambda q: called.setdefault("hosted", q) or [])
    monkeypatch.setattr(tools, "_wikipedia_search", lambda q: called.setdefault("free", q) or [])

    tools.search_web("eiffel tower")
    assert "hosted" in called and "free" not in called


def test_search_web_falls_back_when_no_key(monkeypatch):
    monkeypatch.setattr(tools.config, "has_hosted_search", lambda: False)
    called = {}
    monkeypatch.setattr(tools, "_hosted_search", lambda q: called.setdefault("hosted", q) or [])
    monkeypatch.setattr(tools, "_wikipedia_search", lambda q: called.setdefault("free", q) or [])

    tools.search_web("eiffel tower")
    assert "free" in called and "hosted" not in called


def test_safe_records_error_and_continues():
    enrichment = Enrichment()

    def boom():
        raise RuntimeError("down")

    result = orchestrator._safe(enrichment, "pois", boom)
    assert result is None
    assert enrichment.errors == ["pois: down"]


def test_safe_returns_value_on_success():
    enrichment = Enrichment()
    assert orchestrator._safe(enrichment, "wikipedia", lambda: {"ok": 1}) == {"ok": 1}
    assert enrichment.errors == []
