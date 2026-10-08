"use client";

import { useRef, useState } from "react";
import { ACCEPT, formatBytes } from "@/lib/files";

interface Props {
  file: File | null;
  onSelect: (file: File) => void;
  compact?: boolean;
}

export function UploadDropzone({ file, onSelect, compact = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onSelect(f);
      }}
      className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed text-center transition-colors ${
        compact ? "px-4 py-6" : "px-4 py-12"
      } ${dragging ? "border-brand-600 bg-brand-50" : "border-gray-300 bg-gray-50"}`}
    >
      {file ? (
        <p className="mb-3 break-all text-sm text-gray-800">
          <span className="font-semibold">{file.name}</span>（{formatBytes(file.size)}）
        </p>
      ) : (
        <p className="mb-3 text-sm font-semibold text-gray-700">会議データをアップロード</p>
      )}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-100"
      >
        {file ? "別のファイルを選択" : "ファイルを選択"}
      </button>
      <p className="mt-2 text-xs text-gray-500">またはドラッグ＆ドロップ</p>
      <p className="mt-1 text-xs text-gray-400">音声（MP3/M4A/WAV 等）・動画（MP4/MOV 等）・TXT・VTT・SRT</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onSelect(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
