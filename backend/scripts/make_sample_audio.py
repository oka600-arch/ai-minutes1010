"""sample-data の会話台本から、テスト用の会議音声を作る（無料の読み上げソフト pyopenjtalk を使用）。

話者ごとに声の高さと速さを変え、発言の間に短い無音を入れる。実際の会議より聞き取りやすい音声になる点に注意。

    pip install pyopenjtalk-plus numpy
    python scripts/make_sample_audio.py ../sample-data/eigyo_teirei_2026-10-08.txt out.m4a
"""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pyopenjtalk

VOICES = [(0.0, 1.0), (-3.0, 0.95), (3.0, 1.05), (-1.5, 1.1)]  # (声の高さ, 速さ)


def main(script: Path, dest: Path) -> None:
    speakers: dict[str, int] = {}
    chunks: list[np.ndarray] = []
    sr = 48000
    for line in script.read_text(encoding="utf-8").splitlines():
        if "：" not in line:
            continue
        name, text = line.split("：", 1)
        half_tone, speed = VOICES[speakers.setdefault(name, len(speakers)) % len(VOICES)]
        audio, sr = pyopenjtalk.tts(text, half_tone=half_tone, speed=speed)
        chunks += [audio, np.zeros(int(sr * 0.6))]
    pcm = np.clip(np.concatenate(chunks), -32768, 32767).astype(np.int16)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        # ブラウザでの録音・圧縮に近い形式（AAC 64kbps）で保存する
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "64k", str(dest)], check=True)
    print(f"{dest}: {len(pcm) / sr:.0f}秒, 話者 {len(speakers)}人")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
