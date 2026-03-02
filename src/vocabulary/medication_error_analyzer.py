#!/usr/bin/env python3
"""Medication transcription error analyzer core.

This module provides reusable analysis functions for medication-name
mis-transcription detection, including incremental history scanning by
`history.jsonl` line offset.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import phonetics  # type: ignore

    PHONETICS_AVAILABLE = True
except Exception:
    PHONETICS_AVAILABLE = False


TERM_TOKEN = r"[A-Za-z][A-Za-z'\-]{2,}"
UNIT_TOKEN = r"(?:mg|mcg|g|milligram|milligrams)"

# Strong patterns are much less noisy and map directly to medication slots.
PATTERN_DEFS: List[Tuple[str, bool, re.Pattern[str]]] = [
    (
        "dose_of",
        True,
        re.compile(
            rf"\b(?:dose|refill|script|prescription)\s+of\s+(?P<term>{TERM_TOKEN})\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "term_plus_unit",
        True,
        re.compile(
            rf"\b(?P<term>{TERM_TOKEN})\s+\d+(?:\.\d+)?\s*{UNIT_TOKEN}\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "unit_of_term",
        True,
        re.compile(
            rf"\b\d+(?:\.\d+)?\s*{UNIT_TOKEN}\s+(?:dose\s+of\s+|of\s+)?(?P<term>{TERM_TOKEN})\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "month_of",
        True,
        re.compile(
            rf"\b(?:month|months)\s+of\s*(?P<term>{TERM_TOKEN})\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "for_term_medication",
        True,
        re.compile(
            rf"\bfor\s+(?P<term>{TERM_TOKEN})\s+medication\b",
            flags=re.IGNORECASE,
        ),
    ),
    # Weak patterns are noisy, so scoring is stricter for these.
    (
        "on_term",
        False,
        re.compile(
            rf"\bon\s+(?P<term>{TERM_TOKEN})\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "take_term",
        False,
        re.compile(
            rf"\b(?:take|taking|start|started|starting|continue|continuing|using|switch(?:ed)?\s+to)\s+"
            rf"(?P<term>{TERM_TOKEN})\b",
            flags=re.IGNORECASE,
        ),
    ),
]

MEDICATION_CONTEXT_RE = re.compile(
    r"\b("
    r"mg|mcg|milligram|milligrams|dose|refill|prescription|script|medication|medications|"
    r"tablet|tablets|tab|tabs|capsule|capsules|prior authorization|insurance|approved|"
    r"prn|bid|tid|qhs|qam"
    r")\b",
    flags=re.IGNORECASE,
)

SALT_WORDS: Set[str] = {
    "hydrochloride",
    "hcl",
    "sodium",
    "potassium",
    "calcium",
    "acetate",
    "phosphate",
    "sulfate",
    "sulphate",
    "nitrate",
    "tartrate",
    "succinate",
    "fumarate",
    "maleate",
    "mesylate",
    "besylate",
    "benzoate",
    "carbonate",
    "citrate",
    "chloride",
    "bromide",
    "iodide",
    "gluconate",
    "hydrate",
    "monohydrate",
    "dihydrate",
    "trihydrate",
    "kit",
    "autoinjector",
    "injection",
    "solution",
    "tablet",
    "tablets",
    "capsule",
    "capsules",
    "extended",
    "release",
    "delayed",
    "and",
    "with",
    "w",
}

# Large stopword set to avoid weak-pattern noise in redacted narrative dictation.
STOPWORDS: Set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "there",
    "here",
    "then",
    "than",
    "when",
    "while",
    "which",
    "what",
    "have",
    "has",
    "had",
    "will",
    "would",
    "should",
    "could",
    "you",
    "your",
    "our",
    "his",
    "her",
    "their",
    "they",
    "them",
    "about",
    "into",
    "onto",
    "over",
    "under",
    "same",
    "next",
    "first",
    "second",
    "third",
    "issue",
    "plan",
    "point",
    "time",
    "today",
    "tomorrow",
    "yesterday",
    "message",
    "please",
    "know",
    "able",
    "need",
    "follow",
    "portal",
    "department",
    "health",
    "patient",
    "patients",
    "symptoms",
    "pain",
    "history",
    "current",
    "new",
    "high",
    "low",
    "daily",
    "weekly",
    "monthly",
    "once",
    "twice",
    "three",
    "four",
    "five",
    "year",
    "years",
    "month",
    "months",
    "week",
    "weeks",
    "day",
    "days",
    "start",
    "started",
    "starting",
    "take",
    "taking",
    "continue",
    "continuing",
    "using",
    "used",
    "switch",
    "switched",
    "sending",
    "send",
    "sent",
    "dose",
    "doses",
    "refill",
    "prescription",
    "script",
    "medication",
    "medications",
    "insurance",
    "prior",
    "authorization",
    "approved",
    "control",
    "total",
    "tablets",
    "tablet",
    "tabs",
    "tab",
    "capsule",
    "capsules",
    "statin",
    "sartan",
    "bid",
    "tid",
    "qhs",
    "qam",
    "prn",
    "redacted_name",
    "chronic",
    "overall",
    "prostate",
    "prep",
    "really",
}

# Helps rescue low string-similarity errors for common medication families.
MEDICATION_SHAPE_HINTS: Tuple[str, ...] = (
    "jaro",
    "bound",
    "govi",
    "govy",
    "govy",
    "lutide",
    "statin",
    "sartan",
    "pril",
    "olol",
    "prazole",
    "xaban",
    "oxetine",
    "triptyline",
    "zepam",
    "gliflozin",
    "cycline",
    "mycin",
    "cillin",
    "floxacin",
    "tiaz",
    "zam",
)


@dataclass(frozen=True)
class SourceRecord:
    source: str
    record_id: str
    created_at: str
    text: str
    history_line: int = 0


@dataclass
class MatchSummary:
    observed: str
    suggested: str
    reason: str
    score: float
    occurrences: int = 0
    entries: Set[str] = field(default_factory=set)
    samples: List[str] = field(default_factory=list)


_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 8
_TERMS_AND_INDICES_CACHE: Dict[
    Tuple[
        Optional[Tuple[str, int, int]],
        Optional[Tuple[str, int, int]],
    ],
    Tuple[
        Set[str],
        Dict[str, List[str]],
        Dict[str, Set[str]],
    ],
] = {}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_term(term: str) -> str:
    token = term.strip(".,;:!?()[]{}\"'")
    token = _normalize_space(token.lower())
    return token


def _derive_aliases(term: str) -> Set[str]:
    raw = _normalize_space(term.lower())
    if not raw:
        return set()
    expanded = raw.replace("||", ";").replace("/", ";").replace(",", ";")
    aliases: Set[str] = set()
    for part in expanded.split(";"):
        part = _normalize_space(part)
        if not part or part == "unknown":
            continue
        tokens = re.findall(r"[a-z][a-z0-9'\-]*", part)
        if not tokens:
            continue
        while tokens and tokens[-1] in SALT_WORDS:
            tokens.pop()
        if not tokens:
            continue
        collapsed = " ".join(tokens)
        aliases.add(collapsed)
        if len(tokens[0]) >= 4:
            aliases.add(tokens[0])
    return aliases


def _file_signature(path: Optional[Path]) -> Optional[Tuple[str, int, int]]:
    if path is None:
        return None
    try:
        resolved = path.resolve()
        if not resolved.exists():
            return None
        stat = resolved.stat()
        return (resolved.as_posix(), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _load_medication_terms_uncached(
    lexicon_path: Path,
    user_vocabulary_path: Optional[Path] = None,
) -> Set[str]:
    """Load known medication terms from lexicon + medication category aliases."""
    with lexicon_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    terms = payload.get("terms", [])
    known: Set[str] = set()
    for term in terms:
        known.update(_derive_aliases(str(term)))

    if user_vocabulary_path and user_vocabulary_path.exists():
        try:
            with user_vocabulary_path.open("r", encoding="utf-8") as f:
                user_vocab = json.load(f)
            for _, meta in (user_vocab.get("terms") or {}).items():
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("category", "")).lower() != "medication":
                    continue
                correct = str(meta.get("correct", "")).strip()
                if correct:
                    known.add(_normalize_term(correct))
                for variant in meta.get("variations", []) or []:
                    variant_norm = _normalize_term(str(variant))
                    if variant_norm:
                        known.add(variant_norm)
        except Exception:
            # Non-fatal: analysis is still useful without user vocabulary aliases.
            pass
    return {term for term in known if term and term not in STOPWORDS}


def _get_cached_terms_and_indices(
    lexicon_path: Path,
    user_vocabulary_path: Optional[Path] = None,
) -> Tuple[Set[str], Dict[str, List[str]], Dict[str, Set[str]]]:
    cache_key = (
        _file_signature(lexicon_path),
        _file_signature(user_vocabulary_path),
    )
    with _CACHE_LOCK:
        cached = _TERMS_AND_INDICES_CACHE.get(cache_key)
        if cached is not None:
            return cached

    known_terms = _load_medication_terms_uncached(
        lexicon_path=lexicon_path,
        user_vocabulary_path=user_vocabulary_path,
    )
    by_first, by_phonetic = _build_indices(known_terms)
    cache_value = (known_terms, by_first, by_phonetic)

    with _CACHE_LOCK:
        _TERMS_AND_INDICES_CACHE[cache_key] = cache_value
        while len(_TERMS_AND_INDICES_CACHE) > _CACHE_MAX_ENTRIES:
            _TERMS_AND_INDICES_CACHE.pop(next(iter(_TERMS_AND_INDICES_CACHE)))
    return cache_value


def load_medication_terms(
    lexicon_path: Path,
    user_vocabulary_path: Optional[Path] = None,
) -> Set[str]:
    known_terms, _, _ = _get_cached_terms_and_indices(
        lexicon_path=lexicon_path,
        user_vocabulary_path=user_vocabulary_path,
    )
    return known_terms


def load_medication_terms_with_indices(
    lexicon_path: Path,
    user_vocabulary_path: Optional[Path] = None,
) -> Tuple[Set[str], Dict[str, List[str]], Dict[str, Set[str]]]:
    return _get_cached_terms_and_indices(
        lexicon_path=lexicon_path,
        user_vocabulary_path=user_vocabulary_path,
    )


def _parse_history_line(payload: Dict[str, Any], fallback_id: str) -> Optional[SourceRecord]:
    transcript = str(payload.get("transcript") or "")
    if not transcript:
        return None
    return SourceRecord(
        source="history",
        record_id=str(payload.get("id") or fallback_id),
        created_at=str(payload.get("createdAt") or ""),
        text=transcript,
    )


def read_history_records(
    history_jsonl: Path,
    *,
    start_line: int = 0,
) -> Tuple[List[SourceRecord], int]:
    """Read history records incrementally.

    Returns `(records, last_line_number_seen)`. `start_line` is inclusive offset
    of already-processed lines (0 means start from beginning).
    """
    if start_line < 0:
        start_line = 0

    records: List[SourceRecord] = []
    if not history_jsonl.exists():
        return records, 0

    last_line = 0
    with history_jsonl.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, start=1):
            last_line = idx
            if idx <= start_line:
                continue
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            record = _parse_history_line(payload, fallback_id=f"history:{idx}")
            if record is None:
                continue
            records.append(
                SourceRecord(
                    source=record.source,
                    record_id=record.record_id,
                    created_at=record.created_at,
                    text=record.text,
                    history_line=idx,
                )
            )
    return records, last_line


def iter_history_records(history_jsonl: Path, *, start_line: int = 0) -> Iterable[SourceRecord]:
    """Compatibility helper yielding incremental history records."""
    records, _ = read_history_records(history_jsonl, start_line=start_line)
    return records


def read_log_records(log_path: Path) -> List[SourceRecord]:
    if not log_path.exists():
        return []
    transcribed_re = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[TRANSCRIBED\]\s+"
        r"(?:\[Time:\s*[^\]]+\]\s*)?(?P<text>.+)$"
    )
    records: List[SourceRecord] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, start=1):
            match = transcribed_re.match(line.strip())
            if not match:
                continue
            transcript = match.group("text").strip()
            if not transcript:
                continue
            records.append(
                SourceRecord(
                    source="log",
                    record_id=f"{log_path.name}:{idx}",
                    created_at=match.group("ts"),
                    text=transcript,
                )
            )
    return records


def _is_medication_shaped(token: str) -> bool:
    lower = token.lower()
    return any(hint in lower for hint in MEDICATION_SHAPE_HINTS)


def _snippet(text: str, index: int, radius: int = 95) -> str:
    left = max(0, index - radius)
    right = min(len(text), index + radius)
    value = text[left:right].strip()
    value = _normalize_space(value)
    return value


def _build_indices(known_terms: Set[str]) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]]]:
    by_first: Dict[str, List[str]] = defaultdict(list)
    for term in known_terms:
        by_first[term[0]].append(term)

    by_phonetic: Dict[str, Set[str]] = defaultdict(set)
    if PHONETICS_AVAILABLE:
        for term in known_terms:
            code1, code2 = phonetics.dmetaphone(term)
            if code1:
                by_phonetic[code1].add(term)
            if code2:
                by_phonetic[code2].add(term)
    return by_first, by_phonetic


def _best_medication_match(
    token: str,
    med_shaped: bool,
    known_terms: Set[str],
    by_first: Dict[str, List[str]],
    by_phonetic: Dict[str, Set[str]],
) -> Tuple[Optional[str], float, Optional[str], float]:
    if not token:
        return None, 0.0, None, 0.0

    spelling_pool: List[str] = [
        candidate
        for candidate in by_first.get(token[0], list(known_terms))
        if abs(len(candidate) - len(token)) <= 6
    ]
    if not spelling_pool:
        spelling_pool = [candidate for candidate in known_terms if abs(len(candidate) - len(token)) <= 6]

    # If the observed token has medication-family shape, avoid first-letter bias
    # and prioritize candidates in the same suffix/pattern family.
    if med_shaped:
        shape_candidates: Set[str] = set()
        for hint in MEDICATION_SHAPE_HINTS:
            if hint in token:
                shape_candidates.update(candidate for candidate in known_terms if hint in candidate)
        if shape_candidates:
            spelling_pool.extend(shape_candidates)

    # Preserve order while deduplicating.
    deduped_pool: List[str] = []
    seen_pool: Set[str] = set()
    for candidate in spelling_pool:
        if candidate in seen_pool:
            continue
        seen_pool.add(candidate)
        deduped_pool.append(candidate)
    spelling_pool = deduped_pool

    best_spelling = None
    best_spelling_score = 0.0
    for candidate in spelling_pool:
        score = difflib.SequenceMatcher(None, token, candidate).ratio()
        if score > best_spelling_score:
            best_spelling = candidate
            best_spelling_score = score

    best_phonetic = None
    best_phonetic_score = 0.0
    if PHONETICS_AVAILABLE:
        code1, code2 = phonetics.dmetaphone(token)
        phonetic_pool: Set[str] = set()
        if code1:
            phonetic_pool.update(by_phonetic.get(code1, set()))
        if code2:
            phonetic_pool.update(by_phonetic.get(code2, set()))
        for candidate in phonetic_pool:
            score = difflib.SequenceMatcher(None, token, candidate).ratio()
            if score > best_phonetic_score:
                best_phonetic = candidate
                best_phonetic_score = score

    return best_spelling, best_spelling_score, best_phonetic, best_phonetic_score


def _classify_candidate(
    candidate: str,
    strong_evidence: bool,
    known_terms: Set[str],
    by_first: Dict[str, List[str]],
    by_phonetic: Dict[str, Set[str]],
) -> Tuple[str, Optional[str], float]:
    """Return `(classification, suggestion, score)`.

    classification in {"recognized", "likely_error", "unknown"}.
    """
    if candidate in known_terms:
        return "recognized", None, 1.0

    med_shaped = _is_medication_shaped(candidate)
    spelling, spelling_score, phonetic, phonetic_score = _best_medication_match(
        token=candidate,
        med_shaped=med_shaped,
        known_terms=known_terms,
        by_first=by_first,
        by_phonetic=by_phonetic,
    )

    # Weak patterns ("on X", "take X") are heavily ambiguous. Keep only
    # med-shaped tokens or near-exact lexical matches.
    if not strong_evidence and not med_shaped:
        if spelling and spelling_score >= 0.93 and len(candidate) >= 7:
            return "likely_error", spelling, spelling_score
        return "unknown", None, max(spelling_score, phonetic_score)

    # Phonetic fallback can recover names like "ogovi" -> "wegovy".
    if phonetic and phonetic_score >= (0.54 if med_shaped else 0.58):
        if strong_evidence or med_shaped or phonetic_score >= 0.80:
            return "likely_error", phonetic, phonetic_score

    # Conservative spelling threshold; relaxed slightly for med-shaped terms.
    if spelling and spelling_score >= (0.70 if med_shaped else 0.84):
        if strong_evidence or med_shaped or spelling_score >= 0.92:
            return "likely_error", spelling, spelling_score
    if spelling and med_shaped and strong_evidence and spelling_score >= 0.55:
        return "likely_error", spelling, spelling_score

    return "unknown", None, max(spelling_score, phonetic_score)


def _extract_candidates(record: SourceRecord) -> List[Tuple[str, str, bool, str]]:
    text = record.text.replace("[REDACTED_NAME]", " ")
    if not MEDICATION_CONTEXT_RE.search(text):
        return []

    candidates: List[Tuple[str, str, bool, str]] = []
    seen: Set[Tuple[str, int, str]] = set()
    for pattern_name, strong_evidence, pattern in PATTERN_DEFS:
        for match in pattern.finditer(text):
            raw_term = match.group("term")
            term = _normalize_term(raw_term)
            if not term:
                continue
            if term in STOPWORDS:
                continue
            if len(term) < 4:
                continue
            key = (term, match.start(), pattern_name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((term, pattern_name, strong_evidence, _snippet(text, match.start())))
    return candidates


def confidence_label(score: float) -> str:
    if score >= 0.92:
        return "high"
    if score >= 0.78:
        return "medium"
    return "low"


def analyze_records(
    records: Sequence[SourceRecord],
    known_terms: Set[str],
    *,
    by_first: Optional[Dict[str, List[str]]] = None,
    by_phonetic: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Any]:
    if by_first is None or by_phonetic is None:
        by_first, by_phonetic = _build_indices(known_terms)

    recognized_counter: Counter[str] = Counter()
    unknown_counter: Counter[str] = Counter()
    error_summary: Dict[Tuple[str, str], MatchSummary] = {}

    total_records = 0
    records_with_context = 0
    total_candidates = 0

    for record in records:
        total_records += 1
        extracted = _extract_candidates(record)
        if not extracted:
            continue
        records_with_context += 1

        for candidate, evidence, strong_evidence, sample in extracted:
            total_candidates += 1
            classification, suggestion, score = _classify_candidate(
                candidate,
                strong_evidence=strong_evidence,
                known_terms=known_terms,
                by_first=by_first,
                by_phonetic=by_phonetic,
            )
            if classification == "recognized":
                recognized_counter[candidate] += 1
                continue

            if classification == "likely_error" and suggestion:
                key = (candidate, suggestion)
                item = error_summary.get(key)
                if item is None:
                    item = MatchSummary(
                        observed=candidate,
                        suggested=suggestion,
                        reason=evidence,
                        score=score,
                    )
                    error_summary[key] = item
                item.occurrences += 1
                item.entries.add(record.record_id)
                # Keep only a couple samples per error family.
                if len(item.samples) < 2:
                    rendered = f"{record.created_at} [{record.record_id}] {sample}"
                    if rendered not in item.samples:
                        item.samples.append(rendered)
                # Preserve max confidence seen.
                if score > item.score:
                    item.score = score
                continue

            if _is_medication_shaped(candidate):
                unknown_counter[candidate] += 1

    likely_errors = sorted(
        error_summary.values(),
        key=lambda item: (
            -len(item.entries),
            -item.occurrences,
            -item.score,
            item.observed,
            item.suggested,
        ),
    )
    unknown = unknown_counter.most_common(50)
    recognized = recognized_counter.most_common(50)

    return {
        "total_records": total_records,
        "records_with_medication_context": records_with_context,
        "total_candidates": total_candidates,
        "recognized_top": recognized,
        "unknown_top": unknown,
        "likely_errors": likely_errors,
    }


def likely_error_candidates(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert report likely-errors into stable dict payloads for auto-learn."""
    likely_errors: List[MatchSummary] = report.get("likely_errors", [])
    candidates: List[Dict[str, Any]] = []
    for item in likely_errors:
        candidates.append(
            {
                "observed": item.observed,
                "suggested": item.suggested,
                "confidence": confidence_label(item.score),
                "score": round(float(item.score), 4),
                "occurrences": int(item.occurrences),
                "entry_count": int(len(item.entries)),
                "evidence": item.reason,
                "sample_context": item.samples[0] if item.samples else "",
            }
        )
    return candidates


def analyze_history_incremental(
    *,
    history_path: Path,
    lexicon_path: Path,
    user_vocabulary_path: Optional[Path] = None,
    start_line: int = 0,
    log_paths: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    """Analyze newly-added history lines and optional logs.

    Returns a dict with analysis report, candidate list, and the new
    `last_processed_history_line`.
    """
    known_terms, by_first, by_phonetic = load_medication_terms_with_indices(
        lexicon_path=lexicon_path,
        user_vocabulary_path=user_vocabulary_path,
    )

    history_records, last_history_line = read_history_records(
        history_jsonl=history_path,
        start_line=start_line,
    )

    records: List[SourceRecord] = list(history_records)
    if log_paths:
        for log_path in log_paths:
            records.extend(read_log_records(log_path))

    report = analyze_records(
        records=records,
        known_terms=known_terms,
        by_first=by_first,
        by_phonetic=by_phonetic,
    )
    candidates = likely_error_candidates(report)

    return {
        "report": report,
        "candidates": candidates,
        "scanned_records": len(history_records),
        "last_processed_history_line": int(last_history_line),
    }


def render_markdown_report(
    report: Dict[str, Any],
    input_sources: Sequence[Path],
    generated_at: str,
    top_n: int,
) -> str:
    recognized = report["recognized_top"]
    unknown = report["unknown_top"]
    likely_errors: List[MatchSummary] = report["likely_errors"]

    lines: List[str] = []
    lines.append("# Medication Transcription Error Analysis")
    lines.append("")
    lines.append(f"- Generated: `{generated_at}`")
    lines.append(
        "- Sources: "
        + ", ".join(f"`{path.as_posix()}`" for path in input_sources)
    )
    lines.append(f"- Records scanned: `{report['total_records']}`")
    lines.append(
        "- Records with medication context: "
        f"`{report['records_with_medication_context']}`"
    )
    lines.append(f"- Candidate medication terms extracted: `{report['total_candidates']}`")
    lines.append("")

    lines.append("## Likely Mis-Transcriptions")
    lines.append("")
    if not likely_errors:
        lines.append("No likely medication-name transcription errors were detected.")
        lines.append("")
    else:
        lines.append(
            "| Observed | Suggested | Entry Count | Occurrences | Confidence | Evidence |"
        )
        lines.append("|---|---|---:|---:|---|---|")
        for item in likely_errors[:top_n]:
            lines.append(
                f"| `{item.observed}` | `{item.suggested}` | `{len(item.entries)}` | "
                f"`{item.occurrences}` | `{confidence_label(item.score)}` | `{item.reason}` |"
            )
        lines.append("")
        lines.append("### Example Contexts")
        lines.append("")
        for item in likely_errors[: min(top_n, 15)]:
            if not item.samples:
                continue
            lines.append(f"- `{item.observed}` -> `{item.suggested}`")
            for sample in item.samples:
                lines.append(f"  - `{sample}`")
        lines.append("")

    lines.append("## Recognized Medication Terms (Top)")
    lines.append("")
    if recognized:
        lines.append("| Term | Count |")
        lines.append("|---|---:|")
        for term, count in recognized[:top_n]:
            lines.append(f"| `{term}` | `{count}` |")
    else:
        lines.append("No recognized medication terms found in extracted candidate slots.")
    lines.append("")

    lines.append("## Unresolved Candidate Terms (Top)")
    lines.append("")
    if unknown:
        lines.append("| Term | Count |")
        lines.append("|---|---:|")
        for term, count in unknown[:top_n]:
            lines.append(f"| `{term}` | `{count}` |")
    else:
        lines.append("No unresolved candidate terms.")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Inputs are already redacted; `[REDACTED_NAME]` placeholders are ignored.")
    lines.append(
        "- The analyzer intentionally favors precision in strong medication contexts; "
        "some real errors may be missed in free-form narrative text."
    )
    lines.append(
        "- Confidence reflects string/phonetic similarity, not semantic certainty."
    )
    lines.append("")
    return "\n".join(lines)


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze transcription history/logs for likely medication-name errors.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("data/history/history.jsonl"),
        help="Path to history JSONL.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        action="append",
        default=[],
        help="Optional transcript log path (repeatable).",
    )
    parser.add_argument(
        "--medical-lexicon",
        type=Path,
        default=Path("data/medical_lexicon.json"),
        help="Path to medication lexicon JSON.",
    )
    parser.add_argument(
        "--user-vocabulary",
        type=Path,
        default=Path("data/user_vocabulary.json"),
        help="Path to user vocabulary JSON (for medication aliases).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/medication_transcription_error_report.md"),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Rows per section in report tables.",
    )
    args = parser.parse_args(argv)

    if not args.medical_lexicon.exists():
        raise SystemExit(f"Medical lexicon not found: {args.medical_lexicon}")

    records: List[SourceRecord] = []
    input_sources: List[Path] = []

    history_records, _ = read_history_records(args.history, start_line=0)
    if history_records:
        input_sources.append(args.history)
        records.extend(history_records)

    for log_path in args.log:
        log_records = read_log_records(log_path)
        if log_records:
            input_sources.append(log_path)
            records.extend(log_records)

    if not records:
        raise SystemExit("No records found in provided inputs.")

    known_terms, by_first, by_phonetic = load_medication_terms_with_indices(
        lexicon_path=args.medical_lexicon,
        user_vocabulary_path=args.user_vocabulary if args.user_vocabulary.exists() else None,
    )

    report = analyze_records(
        records=records,
        known_terms=known_terms,
        by_first=by_first,
        by_phonetic=by_phonetic,
    )
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    markdown = render_markdown_report(
        report=report,
        input_sources=input_sources,
        generated_at=generated_at,
        top_n=max(5, args.top),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")

    likely_error_count = len(report["likely_errors"])
    print(f"Saved report: {args.out}")
    print(
        "Summary: "
        f"records={report['total_records']}, "
        f"context_records={report['records_with_medication_context']}, "
        f"candidate_terms={report['total_candidates']}, "
        f"likely_error_families={likely_error_count}"
    )
    return 0


def main() -> int:
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
