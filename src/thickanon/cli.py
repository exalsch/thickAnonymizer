import argparse
from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import anonymize_paths, deanonymize_paths


def _expand(paths) -> list[Path]:
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(f for f in p.rglob("*") if f.is_file())
        else:
            out.append(p)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="thickanon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("anonymize")
    a.add_argument("paths", nargs="+")
    a.add_argument("--root", required=True)
    a.add_argument("--mapping", required=True)
    a.add_argument("--mode", choices=[m.value for m in ReviewMode], default="quick_review")
    a.add_argument("--deny", nargs="*", default=[])
    a.add_argument("--backup")
    a.add_argument("--passphrase")

    d = sub.add_parser("deanonymize")
    d.add_argument("paths", nargs="+")
    d.add_argument("--mapping", required=True)
    d.add_argument("--passphrase")

    ns = parser.parse_args(argv)

    if ns.cmd == "anonymize":
        cfg = AnonymizeConfig(mode=ReviewMode(ns.mode), deny_list=ns.deny)
        mapping = MappingStore()
        report = anonymize_paths(_expand(ns.paths), Path(ns.root), mapping, cfg,
                                 backup_root=Path(ns.backup) if ns.backup else None)
        mapping.save(ns.mapping, passphrase=ns.passphrase)
        print(report.summary())
        return 0

    mapping = MappingStore.load(ns.mapping, passphrase=ns.passphrase)
    deanonymize_paths(_expand(ns.paths), mapping)
    print("Deanonymized.")
    return 0
