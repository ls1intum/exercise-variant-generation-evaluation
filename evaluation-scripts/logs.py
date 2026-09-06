"""Instance-log slicing and phase-timeline reconstruction.

All timings come from the server log, never from polling — polling only notices that a job finished.
The phase timeline is derived from the one INFO line added in ``ExerciseVariantJobService.updatePhase``
("Variant job {id} entering phase {PHASE}"), so every phase duration falls out by subtraction.

Log files are located by glob, not through the ``instance.log`` symlink: ``start-server.sh`` repoints
that symlink on every restart, so following it would read a file that is no longer live, and a run whose
lines straddle a restart would silently lose half of them. Each slice records which files it came from.
"""

import glob
import os
import re
import threading
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional, Tuple

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

# 2026-08-05T10:05:47.982+02:00  INFO 55202 --- [Artemis] [ocal-ci-build-2] logger.Name : message
LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2})\s+"
    r"(?P<level>[A-Z]+)\s+\d+\s+---\s+.*?:\s(?P<message>.*)$"
)

PHASE_PATTERN = re.compile(r"Variant job (?P<job_id>\S+) entering phase (?P<phase>[A-Z_]+)")


class LogLine(NamedTuple):
    timestamp: datetime
    level: str
    message: str
    raw: str
    source_file: str


def _strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", text)


def log_files(pattern: str) -> List[str]:
    """Every instance log matching the glob, oldest first."""
    return sorted(glob.glob(pattern), key=os.path.getmtime)


# Parsed lines per file, with the byte offset already consumed. Every finished run slices the log, so a
# naive re-read would re-parse the whole (growing, hundreds-of-MB) instance log once per run — quadratic
# across a full matrix. Only bytes appended since the last call are parsed. Guarded because runs collect
# concurrently.
_cache_lock = threading.Lock()
_parsed_cache: Dict[str, Tuple[int, List["LogLine"]]] = {}


def _parse_file(path: str) -> List["LogLine"]:
    with _cache_lock:
        offset, cached = _parsed_cache.get(path, (0, []))
        size = os.path.getsize(path)
        if size < offset:
            # The file shrank: not an append, so the cache cannot be trusted. Re-parse from the start.
            offset, cached = 0, []
        if size == offset:
            return list(cached)

        lines = list(cached)
        with open(path, encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            for raw in handle:
                clean = _strip_ansi(raw.rstrip("\n"))
                match = LINE_PATTERN.match(clean)
                if not match:
                    continue
                lines.append(
                    LogLine(
                        timestamp=datetime.fromisoformat(match.group("timestamp")),
                        level=match.group("level"),
                        message=match.group("message"),
                        raw=clean,
                        source_file=os.path.basename(path),
                    )
                )
            consumed = handle.tell()
        _parsed_cache[path] = (consumed, lines)
        return list(lines)


def read_lines(pattern: str) -> List[LogLine]:
    """Parses every matching log file into structured lines, skipping continuation lines (stack traces)."""
    lines: List[LogLine] = []
    for path in log_files(pattern):
        lines.extend(_parse_file(path))
    return lines


def slice_for_job(lines: List[LogLine], job_id: str) -> List[LogLine]:
    """Every log line carrying this job id."""
    return [line for line in lines if job_id in line.raw]


class PhaseTimeline(NamedTuple):
    entries: List[Dict[str, object]]
    durations: Dict[str, float]
    complete: bool
    problem: Optional[str]


def build_phase_timeline(job_lines: List[LogLine], finished_at: Optional[datetime], started_at: Optional[datetime] = None) -> PhaseTimeline:
    """Phase entry timestamps and per-phase durations by subtraction.

    A phase visited several times (the verify/repair loop) accumulates its durations. The last phase is
    closed by ``finished_at`` from the job record, because terminal transitions do not go through
    ``updatePhase``. Fails loudly rather than dropping an incomplete timeline quietly.

    The leading gap is named QUEUED rather than discarded. ``startedAt`` is stamped in ``startJob`` on the
    REST thread, while the first phase line is emitted once ``hyperionVariantTaskExecutor`` picks the job
    up; the difference is queue wait. Without it the durations cannot reconcile with
    ``finished_at - started_at`` and every run looks like a parser bug. It is also real elapsed time an
    instructor waits through, and a useful invariant: the executor is core 4 / max 8 / queue 32, so at
    a concurrency of 3 nothing should queue. A large QUEUED means the runner is submitting faster
    than the pool drains and the wall-time numbers are contaminated.
    """
    entries: List[Dict[str, object]] = []
    for line in job_lines:
        match = PHASE_PATTERN.search(line.message)
        if match:
            entries.append({"phase": match.group("phase"), "at": line.timestamp})

    if not entries:
        return PhaseTimeline([], {}, False, "no phase-transition lines found for this job")

    durations: Dict[str, float] = {}
    if started_at is not None:
        queued_seconds = (entries[0]["at"] - started_at).total_seconds()  # type: ignore[operator]
        if queued_seconds < 0:
            return PhaseTimeline(entries, durations, False, "first phase line precedes startedAt")
        durations["QUEUED"] = queued_seconds
    for index, entry in enumerate(entries):
        if index + 1 < len(entries):
            end = entries[index + 1]["at"]
        elif finished_at is not None:
            end = finished_at
        else:
            return PhaseTimeline(entries, durations, False, "job has no finishedAt to close the final phase")
        seconds = (end - entry["at"]).total_seconds()  # type: ignore[operator]
        if seconds < 0:
            return PhaseTimeline(entries, durations, False, f"negative duration for phase {entry['phase']}")
        durations[str(entry["phase"])] = durations.get(str(entry["phase"]), 0.0) + seconds

    return PhaseTimeline(entries, durations, True, None)
