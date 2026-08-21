from thickanon.cli import main


def test_cli_anonymize_and_deanonymize(tmp_path, capsys):
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"  # outside root

    rc = main(["anonymize", str(f), "--root", str(root),
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
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"  # outside root

    rc = main(["anon", str(f), "--root", str(root),
               "--mapping", str(mp), "--mode", "auto_redact"])
    assert rc == 0
    assert "10.0.0.7" not in f.read_text(encoding="utf-8")

    rc = main(["deanon", str(f), "--mapping", str(mp)])
    assert rc == 0
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.7"


def test_cli_rejects_mapping_inside_root(tmp_path, capsys):
    f = tmp_path / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    inside = tmp_path / "map.json"  # inside --root

    rc = main(["anonymize", str(f), "--root", str(tmp_path),
               "--mapping", str(inside), "--mode", "auto_redact"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "outside the root" in err
    # the file must NOT have been anonymized when the guard rejects the run
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.7"
    assert not inside.exists()


def test_cli_quick_review_warns(tmp_path, capsys):
    root = tmp_path / "data"; root.mkdir()
    f = root / "warn.txt"
    f.write_text("contact jane@acme.com", encoding="utf-8")
    mp = tmp_path / "map.json"  # outside root

    rc = main(["anonymize", str(f), "--root", str(root),
               "--mapping", str(mp), "--mode", "quick_review"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "quick_review" in err
    assert "uncertain" in err.lower() or "gray-band" in err.lower() or "gray" in err.lower()


def test_cli_second_run_continues_the_mapping(tmp_path):
    # Replacing the mapping would strand run 1's tokens: counters restart at 1,
    # so run 2's [IP_1] would be a different address and de-anonymizing run 1's
    # file would silently restore the wrong value.
    root = tmp_path / "data"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"

    assert main(["anon", str(a), "--root", str(root), "--mapping", str(mp),
                 "--mode", "auto_redact"]) == 0
    first = a.read_text(encoding="utf-8")

    b = root / "b.txt"
    b.write_text("ping 10.9.9.9", encoding="utf-8")
    assert main(["anon", str(b), "--root", str(root), "--mapping", str(mp),
                 "--mode", "auto_redact"]) == 0
    assert b.read_text(encoding="utf-8") != first  # a different token

    assert main(["deanon", str(a), "--mapping", str(mp)]) == 0
    assert a.read_text(encoding="utf-8") == "ping 10.0.0.7"  # the RIGHT value


def test_cli_refuses_an_unopenable_existing_mapping(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"

    assert main(["anon", str(a), "--root", str(root), "--mapping", str(mp),
                 "--mode", "auto_redact", "--passphrase", "right"]) == 0

    b = root / "b.txt"
    b.write_text("ping 10.9.9.9", encoding="utf-8")
    rc = main(["anon", str(b), "--root", str(root), "--mapping", str(mp),
               "--mode", "auto_redact", "--passphrase", "wrong"])
    assert rc == 2
    assert b.read_text(encoding="utf-8") == "ping 10.9.9.9"  # untouched
