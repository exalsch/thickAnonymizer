from thickanon.core.types import Entity, AnonymizeConfig, ReviewMode


def partition(entities: list[Entity], config: AnonymizeConfig) -> tuple[list[Entity], list[Entity]]:
    """Return (apply_now, needs_review).

    high band (score >= high_threshold) is always applied.
    gray band (low_threshold <= score < high_threshold) depends on mode:
      QUICK_REVIEW -> needs_review
      AUTO_REDACT  -> apply_now
      AUTO_SKIP    -> dropped
    (entities below low_threshold were already filtered out in detect()).
    """
    apply_now, needs_review = [], []
    for e in entities:
        if e.score >= config.high_threshold:
            apply_now.append(e)
        else:
            if config.mode is ReviewMode.QUICK_REVIEW:
                needs_review.append(e)
            elif config.mode is ReviewMode.AUTO_REDACT:
                apply_now.append(e)
            # AUTO_SKIP: drop
    return apply_now, needs_review
