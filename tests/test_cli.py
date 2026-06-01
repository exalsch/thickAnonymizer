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
