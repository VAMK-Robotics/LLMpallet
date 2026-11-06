import importlib
import json

from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMPALLET_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("LLMPALLET_OUTPUT", str(tmp_path / "out"))
    import backend.config_store
    import backend.main
    importlib.reload(backend.config_store)
    main = importlib.reload(backend.main)
    return TestClient(main.app), main


def test_layout_and_config_roundtrip(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    r = client.post("/api/layout", json={"box_length": 400, "box_width": 300, "box_height": 200,
                                         "total_boxes": 6, "layer_count": 1})
    assert r.status_code == 200 and len(r.json()["placements"]) == 6

    cfg = client.get("/api/config").json()
    assert "password" not in cfg["robot"] and cfg["robot"]["password_set"]

    robot = cfg["robot"] | {"ip_address": "10.1.2.3", "password": None}
    robot.pop("password_set")
    assert client.put("/api/config/robot", json=robot).status_code == 200
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["robot"]["ip_address"] == "10.1.2.3"
    assert saved["robot"]["password"] == "robotics"  # kept

    bad = robot | {"var_x": "1bad"}
    assert client.put("/api/config/robot", json=bad).status_code == 422


def test_generate_blocked_by_errors(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    r = client.post("/api/generate", json={"params": {"total_boxes": 1000, "layer_count": 1}})
    body = r.json()
    assert not body["ok"] and body["csv"] == ""


def test_generate_calls_rws(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    sent = {}

    def fake_send(settings, filename, csv_text, dims):
        sent.update(filename=filename, csv=csv_text, dims=dims)
        return {"ok": True, "steps": [{"name": "fake", "ok": True, "message": ""}]}

    monkeypatch.setattr(main.rws_client, "send_job", fake_send)
    r = client.post("/api/generate", json={"params": {"box_length": 400, "box_width": 300, "box_height": 200,
                                                      "total_boxes": 6, "layer_count": 1}, "filename": "job1"})
    body = r.json()
    assert body["ok"] and body["filename"] == "job1.csv" and body["rows"] == 6
    assert sent["dims"] == (400, 300, 200)
    assert (tmp_path / "out" / "job1.csv").read_text() == sent["csv"]
    assert client.post("/api/generate", json={"params": {}, "filename": "../evil"}).status_code == 422
