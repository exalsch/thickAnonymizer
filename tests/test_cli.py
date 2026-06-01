from thickanon.cli import main


def test_cli_anonymize_and_deanonymize(tmp_path, capsys):
    f = tmp_path / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"

    rc = main(["anonymize", str(f), "--root", str(tmp_path),
               "--mapping", str(mp), "--mode", "auto_redact"])
    assert rc == 0
    assert "10.0.0.7" not in f.read_text(encoding="utf-8")
    assert mp.exists()
    out = capsys.readouterr().out
    assert "IP" in out

    rc = main(["deanonymize", str(f), "--mapping", str(mp)])
    assert rc == 0
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.7"


def test_cli_anon_deanon_aliases(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"

    rc = main(["anon", str(f), "--root", str(tmp_path),
               "--mapping", str(mp), "--mode", "auto_redact"])
    assert rc == 0
    assert "10.0.0.7" not in f.read_text(encoding="utf-8")

    rc = main(["deanon", str(f), "--mapping", str(mp)])
    assert rc == 0
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.7"


def test_cli_quick_review_warns(tmp_path, capsys):
    f = tmp_path / "warn.txt"
    f.write_text("contact jane@acme.com", encoding="utf-8")
    mp = tmp_path / "map.json"

    rc = main(["anonymize", str(f), "--root", str(tmp_path),
               "--mapping", str(mp), "--mode", "quick_review"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "quick_review" in err
    assert "uncertain" in err.lower() or "gray-band" in err.lower() or "gray" in err.lower()
