from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import (
    anonymize_paths,
    deanonymize_paths,
    ensure_mapping_outside_root,
)
from thickanon.cli import _expand


class Api:
    def anonymize(self, files, root, mapping_path, mode, deny, backup_dir, passphrase):
        try:
            ensure_mapping_outside_root(mapping_path, root)
            cfg = AnonymizeConfig(mode=ReviewMode(mode), deny_list=deny or [])
            mapping = MappingStore()
            report = anonymize_paths(
                _expand(files), Path(root), mapping, cfg,
                backup_root=Path(backup_dir) if backup_dir else None,
            )
            mapping.save(mapping_path, passphrase=passphrase or None)
            return {"ok": True, "summary": report.summary(), "report": report.to_dict()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def deanonymize(self, files, mapping_path, passphrase):
        try:
            mapping = MappingStore.load(mapping_path, passphrase=passphrase or None)
            deanonymize_paths(_expand(files), mapping)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
