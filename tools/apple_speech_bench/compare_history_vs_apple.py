#!/usr/bin/env python3
import argparse
import csv
import difflib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_compare(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    return compact_spaces(text)


def word_tokens(text: str) -> List[str]:
    text = normalize_for_compare(text)
    return text.split() if text else []


def edit_distance(a: List[str], b: List[str]) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    if len(a) < len(b):
        a, b = b, a

    prev = list(range(len(b) + 1))
    for i, tok_a in enumerate(a, start=1):
        cur = [i]
        for j, tok_b in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if tok_a == tok_b else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def similarity_ratio_words(a_text: str, b_text: str) -> float:
    a = word_tokens(a_text)
    b = word_tokens(b_text)
    denom = max(len(a), len(b), 1)
    dist = edit_distance(a, b)
    return max(0.0, 1.0 - (dist / denom))


def basename_id_from_history_audiofile(audio_file: str) -> str:
    # audioFile looks like "data/history/audio/<id>.wav"
    name = Path(audio_file).name
    return name[: -len(".wav")] if name.lower().endswith(".wav") else name


def id_from_apple_filename(name: str) -> str:
    # apple uses "NN_<id>.wav" in tmp dir.
    stem = Path(name).stem
    stem = re.sub(r"^\d+_", "", stem)
    return stem


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


@dataclass
class AppleRow:
    index: int
    file: str
    id: str
    duration_s: Optional[float]
    processing_s: Optional[float]
    rtf: Optional[float]
    text: str


@dataclass
class HistoryRow:
    id: str
    created_at: str
    audio_file: str
    transcript: str
    processed_transcript: str
    started_at: Optional[float]
    completed_at: Optional[float]
    duration_seconds: Optional[float]
    model: str


def load_apple_results(path: Path) -> List[AppleRow]:
    rows = load_jsonl(path)
    out: List[AppleRow] = []
    for r in rows:
        if r.get("type") != "file_result":
            continue
        file = str(r.get("file") or "")
        out.append(
            AppleRow(
                index=int(r.get("index") or 0),
                file=file,
                id=id_from_apple_filename(file),
                duration_s=safe_float(r.get("duration_s")),
                processing_s=safe_float(r.get("processing_s")),
                rtf=safe_float(r.get("rtf")),
                text=str(r.get("text") or ""),
            )
        )
    out.sort(key=lambda x: x.index)
    return out


def load_history(path: Path) -> Dict[str, HistoryRow]:
    rows = load_jsonl(path)
    out: Dict[str, HistoryRow] = {}
    for r in rows:
        audio_file = str(r.get("audioFile") or "")
        id_ = str(r.get("id") or "") or basename_id_from_history_audiofile(audio_file)
        out[id_] = HistoryRow(
            id=id_,
            created_at=str(r.get("createdAt") or ""),
            audio_file=audio_file,
            transcript=str(r.get("transcript") or ""),
            processed_transcript=str(r.get("processedTranscript") or ""),
            started_at=safe_float(r.get("startedAt")),
            completed_at=safe_float(r.get("completedAt")),
            duration_seconds=safe_float(r.get("durationSeconds")),
            model=str((r.get("metadata") or {}).get("model") or ""),
        )
    return out


def fmt_seconds(x: Optional[float]) -> str:
    if x is None or math.isnan(x):
        return "-"
    return f"{x:.3f}"


def clip(text: str, n: int = 180) -> str:
    t = compact_spaces(text)
    return t if len(t) <= n else t[: n - 1] + "…"


def unified_diff(a: str, b: str, fromfile: str, tofile: str, context: int = 2) -> str:
    a_n = normalize_for_compare(a).split()
    b_n = normalize_for_compare(b).split()
    diff = difflib.unified_diff(a_n, b_n, fromfile=fromfile, tofile=tofile, n=context, lineterm="")
    return "\n".join(diff)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="data/history/history.jsonl")
    ap.add_argument("--apple", default="tools/apple_speech_bench/apple_speech_results_recent25.jsonl")
    ap.add_argument("--out-md", default="tools/apple_speech_bench/compare_recent25.md")
    ap.add_argument("--out-csv", default="tools/apple_speech_bench/compare_recent25.csv")
    args = ap.parse_args()

    history_path = Path(args.history)
    apple_path = Path(args.apple)
    out_md = Path(args.out_md)
    out_csv = Path(args.out_csv)

    apple_rows = load_apple_results(apple_path)
    history_by_id = load_history(history_path)

    rows_for_csv: List[Dict[str, Any]] = []
    md_lines: List[str] = []

    def collect(values: Iterable[Optional[float]]) -> List[float]:
        return [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]

    app_asr_s_list: List[float] = []
    apple_asr_s_list: List[float] = []
    sim_list: List[float] = []
    missing: int = 0

    for a in apple_rows:
        h = history_by_id.get(a.id)
        if not h:
            missing += 1
            continue
        # durationSeconds in this app appears to be post-audio processing/transcription time
        app_asr_s = h.duration_seconds
        apple_asr_s = a.processing_s
        if isinstance(app_asr_s, (int, float)):
            app_asr_s_list.append(float(app_asr_s))
        if isinstance(apple_asr_s, (int, float)):
            apple_asr_s_list.append(float(apple_asr_s))

        audio_s = a.duration_s
        app_total_s = (h.completed_at - h.started_at) if (h.completed_at is not None and h.started_at is not None) else None
        post_audio_latency_s = (app_total_s - audio_s) if (app_total_s is not None and audio_s is not None) else None
        rtf_app = (app_asr_s / audio_s) if (app_asr_s is not None and audio_s is not None and audio_s > 0) else None

        sim = similarity_ratio_words(h.processed_transcript or h.transcript, a.text)
        sim_list.append(sim)

        rows_for_csv.append(
            {
                "index": a.index,
                "id": a.id,
                "createdAt": h.created_at,
                "audio_s": audio_s,
                "app_model": h.model,
                "app_asr_s": app_asr_s,
                "apple_asr_s": apple_asr_s,
                "app_total_s": app_total_s,
                "app_post_audio_latency_s": post_audio_latency_s,
                "rtf_app": rtf_app,
                "rtf_apple": a.rtf,
                "similarity_words": sim,
                "app_text": h.processed_transcript or h.transcript,
                "apple_text": a.text,
            }
        )

    def mean(xs: List[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    def median(xs: List[float]) -> Optional[float]:
        if not xs:
            return None
        ys = sorted(xs)
        m = len(ys) // 2
        return ys[m] if len(ys) % 2 else (ys[m - 1] + ys[m]) / 2

    md_lines.append("# App (history.jsonl) vs Apple Speech (on-device) — 25 most recent WAVs\n")
    md_lines.append(f"- Apple input: `{apple_path}`")
    md_lines.append(f"- App history: `{history_path}`")
    md_lines.append(f"- Matched files: {len(rows_for_csv)} / {len(apple_rows)} (missing in history: {missing})\n")
    md_lines.append(
        "- Note: In your app history, `durationSeconds` appears to be *post-audio processing/transcription time* (not the WAV duration).\n"
    )

    md_lines.append("## Timing summary\n")
    md_lines.append(
        f"- App ASR time (history `durationSeconds`): avg={fmt_seconds(mean(app_asr_s_list))}s median={fmt_seconds(median(app_asr_s_list))}s"
    )
    md_lines.append(
        f"- Apple ASR time (`processing_s`): avg={fmt_seconds(mean(apple_asr_s_list))}s median={fmt_seconds(median(apple_asr_s_list))}s"
    )
    if app_asr_s_list and apple_asr_s_list:
        ratio = (mean(app_asr_s_list) / mean(apple_asr_s_list)) if mean(apple_asr_s_list) else None
        md_lines.append(f"- Avg speed ratio (app/apple): {ratio:.2f}x" if ratio else "- Avg speed ratio (app/apple): -")
    md_lines.append("")

    md_lines.append("## Text similarity summary (word-level)\n")
    md_lines.append(
        f"- Similarity (1.0=identical after normalization): avg={mean(sim_list):.3f} median={median(sim_list):.3f}"
        if sim_list
        else "- Similarity: -"
    )
    md_lines.append("")

    def md_escape(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ")

    md_lines.append("## Biggest text mismatches\n")
    md_lines.append("Lowest similarity after normalization (punctuation/casing removed):\n")
    worst = sorted(rows_for_csv, key=lambda r: float(r["similarity_words"]))[:5]
    md_lines.append("| # | id | similarity | app_text (clip) | apple_text (clip) |")
    md_lines.append("|---:|---|---:|---|---|")
    for row in worst:
        md_lines.append(
            "| {idx} | `{id}` | {sim:.3f} | {app_clip} | {apple_clip} |".format(
                idx=row["index"],
                id=row["id"],
                sim=row["similarity_words"],
                app_clip=md_escape(clip(row["app_text"], 140)),
                apple_clip=md_escape(clip(row["apple_text"], 140)),
            )
        )
    md_lines.append("")

    md_lines.append("## Per-file table\n")
    md_lines.append(
        "| # | id | audio_s | app_asr_s | apple_asr_s | app_post_audio_latency_s | rtf_app | rtf_apple | similarity | app_text (clip) | apple_text (clip) |"
    )
    md_lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|")

    for row in rows_for_csv:
        md_lines.append(
            "| {idx} | `{id}` | {audio_s} | {app_asr_s} | {apple_asr_s} | {post_audio} | {rtf_app} | {rtf_apple} | {sim:.3f} | {app_clip} | {apple_clip} |".format(
                idx=row["index"],
                id=row["id"],
                audio_s=fmt_seconds(row["audio_s"]),
                app_asr_s=fmt_seconds(row["app_asr_s"]),
                apple_asr_s=fmt_seconds(row["apple_asr_s"]),
                post_audio=fmt_seconds(row.get("app_post_audio_latency_s")),
                rtf_app=fmt_seconds(row["rtf_app"]),
                rtf_apple=fmt_seconds(row["rtf_apple"]),
                sim=row["similarity_words"],
                app_clip=md_escape(clip(row["app_text"])),
                apple_clip=md_escape(clip(row["apple_text"])),
            )
        )

    md_lines.append("\n## Detailed diffs\n")
    md_lines.append("Each section shows normalized word diff (punctuation/casing removed).\n")

    for row in rows_for_csv:
        a_text = row["apple_text"]
        h_text = row["app_text"]
        diff = unified_diff(h_text, a_text, fromfile="app", tofile="apple", context=1)
        if not diff:
            diff = "(no diff after normalization)"
        md_lines.append(f"### {row['index']}. {row['id']}\n")
        md_lines.append(f"- App model: `{row['app_model']}`")
        md_lines.append(f"- Audio length: {fmt_seconds(row['audio_s'])}s")
        md_lines.append(
            f"- Time: app_asr_s={fmt_seconds(row['app_asr_s'])}s apple_asr_s={fmt_seconds(row['apple_asr_s'])}s"
        )
        if row.get("app_post_audio_latency_s") is not None:
            md_lines.append(f"- App post-audio latency (approx): {fmt_seconds(row['app_post_audio_latency_s'])}s")
        md_lines.append(f"- Similarity: {row['similarity_words']:.3f}\n")
        md_lines.append("<details>\n<summary>Show texts + diff</summary>\n\n")
        md_lines.append("**App (processedTranscript)**\n")
        md_lines.append(f"\n{h_text}\n")
        md_lines.append("\n**Apple (on-device)**\n")
        md_lines.append(f"\n{a_text}\n")
        md_lines.append("\n**Normalized word diff**\n")
        md_lines.append("```diff")
        md_lines.append(diff)
        md_lines.append("```\n")
        md_lines.append("</details>\n")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md_lines).strip() + "\n", encoding="utf-8")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "index",
                "id",
                "createdAt",
                "audio_s",
                "app_model",
                "app_asr_s",
                "apple_asr_s",
                "app_total_s",
                "app_post_audio_latency_s",
                "rtf_app",
                "rtf_apple",
                "similarity_words",
                "app_text",
                "apple_text",
            ],
        )
        writer.writeheader()
        for r in rows_for_csv:
            writer.writerow(r)

    print(f"Wrote: {out_md}")
    print(f"Wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
