from satviz import geocode


class _Result:
    def __init__(self, raw):
        self.raw = raw


def _patch_reverse(monkeypatch, raw):
    monkeypatch.setattr(geocode._geolocator, "reverse", lambda *a, **k: _Result(raw))


def test_reverse_geocode_marks_country_only_name_approximate(monkeypatch):
    _patch_reverse(monkeypatch, {"display_name": "Australia"})
    loc = geocode.reverse_geocode(-18.0, 147.0)
    assert loc.display_name == "Australia (approx.)"


def test_reverse_geocode_keeps_detailed_name(monkeypatch):
    detailed = "10 Downing Street, London, England, United Kingdom"
    _patch_reverse(monkeypatch, {"display_name": detailed})
    loc = geocode.reverse_geocode(51.5, -0.12)
    assert loc.display_name == detailed


def test_reverse_geocode_open_water_when_empty(monkeypatch):
    _patch_reverse(monkeypatch, {})
    loc = geocode.reverse_geocode(0.0, 0.0)
    assert loc.display_name == "Open water or remote area"
