"""録音ファイルから、文字起こし → AI解析 → Word/PDF 生成までを通しで実行する（Supabase・Dropbox なし）。

本番と同じ部品（WhisperTranscriber・Gemini/Ollama の解析・Word/PDF 生成）を使い、結果と処理時間を出力する。
AI解析は .env（または環境変数）の ANALYSIS_PROVIDER / GEMINI_API_KEY を使う。キーがない場合は文字起こしまで行う。

    python scripts/e2e_audio_test.py 音声ファイル 種類(record|review|daily) 出力フォルダ [台本.txt]
"""

import json
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.deps import get_analyzer, get_transcriber  # noqa: E402
from app.schemas import MeetingInfo  # noqa: E402
from app.services.docx_builder import build_docx  # noqa: E402
from app.services.minutes_types import fill_meeting_info, get_type  # noqa: E402
from app.services.naming import JST  # noqa: E402
from app.services.pdf_builder import build_pdf  # noqa: E402


def _chars(text: str) -> str:
    """比較用に、記号・空白・話者名を除いた文字列にする。"""
    lines = [line.split("：", 1)[-1] for line in text.splitlines()]
    return "".join(c for c in "".join(lines) if unicodedata.category(c)[0] in "LN")


def char_error_rate(reference: str, hypothesis: str) -> float:
    """文字誤り率（編集距離 ÷ 正解の文字数）。"""
    ref, hyp = _chars(reference), _chars(hypothesis)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(len(ref), 1)


def main(audio: Path, type_key: str, out: Path, script: Path | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    t = get_type(type_key)
    participants = []
    if script:
        participants = list(dict.fromkeys(l.split("：", 1)[0] for l in script.read_text(encoding="utf-8").splitlines() if "：" in l))
    info = MeetingInfo(meeting_name=audio.stem, meeting_datetime=datetime.now(JST), participants=participants)
    report: dict = {"audio": audio.name, "type": t.label, "whisper_model": s.whisper_model}

    started = time.monotonic()
    transcript = get_transcriber().transcribe(audio, participants)
    report["transcribe_seconds"] = round(time.monotonic() - started, 1)
    (out / "transcript.txt").write_text(transcript, encoding="utf-8")
    if script:
        report["char_error_rate"] = round(char_error_rate(script.read_text(encoding="utf-8"), transcript), 3)

    analyzer = get_analyzer()
    problem = analyzer.check()
    if problem:
        report["analysis"] = f"未実行：{problem}"
    else:
        started = time.monotonic()
        data = fill_meeting_info(t, analyzer.analyze(info, transcript, t), info)
        report["analyze_seconds"] = round(time.monotonic() - started, 1)
        report["analysis_model"] = analyzer.model_name
        (out / "minutes.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "minutes.docx").write_bytes(build_docx(info, t, data))
        (out / "minutes.pdf").write_bytes(build_pdf(info, t, data))

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]) if len(sys.argv) > 4 else None)
