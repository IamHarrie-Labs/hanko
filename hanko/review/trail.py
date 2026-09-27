"""An append-only log of metric readings, taken between decisions and reviews.

D-13 found that grading a falsifier only at review time misses a breach that
recovers before the clock gets there. Fixing the grader alone is not enough:
`ANY_POINT_IN_WINDOW` can only see what it was actually given. A single
sample at review time gives it exactly the same blind spot the bug had.

`hanko sweep` already fetches a token's market facts every time it runs,
whether or not any decision on that token is due. This module lets it record
each of those readings once, cheaply, so that by the time a decision on that
token comes due, the falsifier has real intra-window coverage to check
against instead of one more single point.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .outcome import Sample


class SampleTrail:
    """Append-only, one line per (subject, sample), read back filtered by range."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, subject: str, sample: Sample) -> None:
        row = {"subject": subject.upper(), **sample.to_dict()}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def __iter__(self) -> Iterator[tuple[str, Sample]]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                subject = row.pop("subject")
                yield subject, Sample.from_dict(row)

    def for_subject(
        self,
        subject: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Sample, ...]:
        """Every recorded reading for `subject` in [since, until], oldest first.

        `since` should be the decision's own `decided_at` -- a reading from
        before the decision existed says nothing about whether it held.
        """
        key = subject.upper()
        out = [
            sample
            for s, sample in self
            if s == key
            and (since is None or sample.at >= since)
            and (until is None or sample.at <= until)
        ]
        out.sort(key=lambda s: s.at)
        return tuple(out)
