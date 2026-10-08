"use client";

// 動画（または大きな音声）から、ブラウザ内で音声だけを取り出して圧縮する。
// モノラル・16kHz・32kbps の MP3 にすると、1時間の会議でも約14MBになる。
// ffmpeg.wasm はサイズが大きいので、必要になったときだけ読み込む。

import type { FFmpeg } from "@ffmpeg/ffmpeg";

const CORE_BASE_URL = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/umd";

let ffmpegPromise: Promise<FFmpeg> | null = null;

async function loadFFmpeg(): Promise<FFmpeg> {
  if (!ffmpegPromise) {
    ffmpegPromise = (async () => {
      const [{ FFmpeg }, { toBlobURL }] = await Promise.all([import("@ffmpeg/ffmpeg"), import("@ffmpeg/util")]);
      const ffmpeg = new FFmpeg();
      await ffmpeg.load({
        coreURL: await toBlobURL(`${CORE_BASE_URL}/ffmpeg-core.js`, "text/javascript"),
        wasmURL: await toBlobURL(`${CORE_BASE_URL}/ffmpeg-core.wasm`, "application/wasm"),
      });
      return ffmpeg;
    })().catch((e) => {
      ffmpegPromise = null;
      throw e;
    });
  }
  return ffmpegPromise;
}

export class AudioExtractError extends Error {}

export async function extractAudio(file: File, onProgress?: (ratio: number) => void): Promise<File> {
  let ffmpeg: FFmpeg;
  try {
    ffmpeg = await loadFFmpeg();
  } catch {
    throw new AudioExtractError("音声変換機能を読み込めませんでした。通信環境を確認してください。");
  }
  const { fetchFile } = await import("@ffmpeg/util");
  const ext = file.name.split(".").pop() ?? "bin";
  const input = `input.${ext}`;
  const output = "output.mp3";
  const handler = ({ progress }: { progress: number }) => onProgress?.(Math.min(1, Math.max(0, progress)));
  ffmpeg.on("progress", handler);
  try {
    await ffmpeg.writeFile(input, await fetchFile(file));
    const code = await ffmpeg.exec(["-i", input, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", output]);
    if (code !== 0) throw new AudioExtractError("音声を取り出せませんでした。ファイルが壊れているか、音声が含まれていません。");
    const data = await ffmpeg.readFile(output);
    if (typeof data === "string" || data.length === 0) throw new AudioExtractError("音声を取り出せませんでした。");
    const baseName = file.name.replace(/\.[^.]+$/, "");
    return new File([new Uint8Array(data)], `${baseName}.mp3`, { type: "audio/mpeg" });
  } catch (e) {
    if (e instanceof AudioExtractError) throw e;
    throw new AudioExtractError("音声の変換に失敗しました。ファイルが大きすぎる可能性があります。");
  } finally {
    ffmpeg.off("progress", handler);
    await ffmpeg.deleteFile(input).catch(() => {});
    await ffmpeg.deleteFile(output).catch(() => {});
  }
}
