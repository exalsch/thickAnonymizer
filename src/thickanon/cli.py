import argparse
import sys
from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode, GLiNERConfig
from thickanon.detectors import gliner_model
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import (
    anonymize_paths,
    deanonymize_paths,
    ensure_mapping_outside_root,
)


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

    a = sub.add_parser("anonymize", aliases=["anon"])
    a.set_defaults(action="anonymize")
    a.add_argument("paths", nargs="+")
    a.add_argument("--root", required=True)
    a.add_argument("--mapping", required=True)
    a.add_argument("--mode", choices=[m.value for m in ReviewMode], default="quick_review")
    a.add_argument("--deny", nargs="*", default=[])
    a.add_argument("--backup")
    a.add_argument("--passphrase")
    a.add_argument("--gliner", action="store_true", help="use the GLiNER neural detector")
    a.add_argument("--gliner-model", help="path to a local GLiNER model dir")
    a.add_argument("--gliner-labels", help="comma-separated entity labels to detect")
    a.add_argument("--gliner-threshold", type=float, default=0.5)
    a.add_argument("--gliner-gpu", action="store_true")

    dl = sub.add_parser("download-model")
    dl.set_defaults(action="download-model")
    dl.add_argument("--gliner-model", help="path to a local GLiNER model dir")

    d = sub.add_parser("deanonymize", aliases=["deanon"])
    d.set_defaults(action="deanonymize")
    d.add_argument("paths", nargs="+")
    d.add_argument("--mapping", required=True)
    d.add_argument("--passphrase")

    ns = parser.parse_args(argv)

    if ns.action == "anonymize":
        try:
            ensure_mapping_outside_root(ns.mapping, ns.root)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        gliner_cfg = None
        if ns.gliner:
            kw = {"enabled": True, "model_path": ns.gliner_model,
                  "threshold": ns.gliner_threshold, "gpu": ns.gliner_gpu}
            if ns.gliner_labels:
                kw["labels"] = [s.strip() for s in ns.gliner_labels.split(",") if s.strip()]
            gliner_cfg = GLiNERConfig(**kw)
        cfg = AnonymizeConfig(mode=ReviewMode(ns.mode), deny_list=ns.deny, gliner=gliner_cfg)
        mapping = MappingStore()
        report = anonymize_paths(_expand(ns.paths), Path(ns.root), mapping, cfg,
                                 backup_root=Path(ns.backup) if ns.backup else None)
        mapping.save(ns.mapping, passphrase=ns.passphrase)
        print(report.summary())
        if cfg.mode == ReviewMode.QUICK_REVIEW:
            print(
                "WARNING: quick_review mode has no interactive reviewer on the CLI, "
                "so uncertain (gray-band) detections were NOT anonymized. "
                "Use --mode auto_redact to over-redact, or the desktop app for interactive review.",
                file=sys.stderr,
            )
        return 0

    if ns.action == "download-model":
        gliner_model.load_model(GLiNERConfig(model_path=getattr(ns, "gliner_model", None)))
        print("Model ready (downloaded/cached).")
        return 0

    mapping = MappingStore.load(ns.mapping, passphrase=ns.passphrase)
    deanonymize_paths(_expand(ns.paths), mapping)
    print("Deanonymized.")
    return 0
