from collections import Counter


class BatchReport:
    def __init__(self):
        self.totals = Counter()
        self.files = {}
        self.skipped = {}
        self.residual_total = 0

    def record_file(self, path, applied, flagged, residual):
        for e in list(applied) + list(flagged):
            self.totals[e.entity_type] += 1
        self.residual_total += len(residual)
        self.files[str(path)] = {
            "applied_count": len(applied),
            "flagged_count": len(flagged),
            "residual_count": len(residual),
        }

    def record_skip(self, path, reason):
        self.skipped[str(path)] = reason

    def to_dict(self):
        return {
            "totals": dict(self.totals),
            "files": self.files,
            "skipped": self.skipped,
            "residual_total": self.residual_total,
        }

    def summary(self) -> str:
        lines = [f"Files processed: {len(self.files)}, skipped: {len(self.skipped)}"]
        for etype, n in sorted(self.totals.items()):
            lines.append(f"  {etype}: {n}")
        if self.residual_total:
            lines.append(f"  RESIDUAL LEAKS FLAGGED: {self.residual_total}")
        for path, reason in self.skipped.items():
            lines.append(f"  skipped {path}: {reason}")
        return "\n".join(lines)


class DeanonReport:
    def __init__(self):
        self.files = {}
        self.unknown_tokens = Counter()
        self.skipped = {}

    def record_file(self, path, restored, unknown=None):
        self.files[str(path)] = restored
        if unknown:
            self.unknown_tokens.update(unknown)

    def record_skip(self, path, reason):
        self.skipped[str(path)] = reason

    def total_restored(self) -> int:
        return sum(self.files.values())

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "unknown_tokens": dict(self.unknown_tokens),
            "skipped": self.skipped,
            "total_restored": self.total_restored(),
        }

    def summary(self) -> str:
        lines = [
            f"Tokens restored: {self.total_restored()} "
            f"across {len(self.files)} file(s), skipped: {len(self.skipped)}"
        ]
        if self.unknown_tokens:
            shown = ", ".join(sorted(self.unknown_tokens)[:5])
            lines.append(
                f"  UNKNOWN TOKENS: {sum(self.unknown_tokens.values())} "
                f"({shown}) - this mapping does not match these files"
            )
        for path, reason in self.skipped.items():
            lines.append(f"  skipped {path}: {reason}")
        return "\n".join(lines)
