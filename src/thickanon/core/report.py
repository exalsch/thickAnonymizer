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
        return "\n".join(lines)
