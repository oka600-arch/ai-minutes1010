FROM python:3.12-slim

# 音声の変換に ffmpeg を使う
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 文字起こしモデル（Whisper）をイメージに含めておき、初回の処理で数分待たないようにする。
# モデルを変える場合は WHISPER_MODEL を build-arg と環境変数の両方で同じ値にする
ARG WHISPER_MODEL=small
ENV HF_HOME=/app/models WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8')" \
    && chmod -R a+rwX /app/models

COPY app ./app
COPY fonts ./fonts

ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
