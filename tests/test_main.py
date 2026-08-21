from thickanon.__main__ import main


def test_main_dispatches_to_cli(tmp_path):
    # Any args -> CLI path; verify it actually anonymizes and returns 0.
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"; f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"  # outside root

    rc = main(["anon", str(f), "--root", str(root),
               "--mapping", str(mp), "--mode", "auto_redact"])
    assert rc == 0
    assert "10.0.0.7" not in f.read_text(encoding="utf-8")
    assert mp.exists()


def test_main_no_args_launches_gui(monkeypatch):
    # No args -> GUI path; we stub out the window so nothing actually opens.
    calls = {}
    import thickanon.ui.app as app

    def fake_run():
        calls["ran"] = True
        return 0  # run() -> int; main() now propagates this exit code.

    monkeypatch.setattr(app, "run", fake_run)
    # _hide_console_on_windows is a no-op off Windows; safe to call directly.
    rc = main([])
    assert rc == 0
    assert calls.get("ran") is True
