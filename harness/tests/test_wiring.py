from cadence.wiring import build_runtime


def test_build_runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    rt = build_runtime()
    assert [c.name for c in rt.catalogue.available()] == [
        "schedule.add", "schedule.cancel", "chat", "correction"]
    assert rt.hub.catalogue is rt.catalogue
