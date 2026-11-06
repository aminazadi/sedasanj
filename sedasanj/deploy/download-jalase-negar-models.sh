#!/bin/sh
# Download each published model once; incomplete transfers are never published.
set -eu
root=${MODEL_DOWNLOAD_DIR:-/models}/v1
download() {
  destination="$root/$1/$2"
  url=$3
  if [ -s "$destination" ]; then return; fi
  mkdir -p "$(dirname "$destination")"
  temp="$destination.tmp"
  rm -f "$temp"
  trap 'rm -f "$temp"' EXIT HUP INT TERM
  curl --fail --location --retry 5 --retry-delay 5 --connect-timeout 30 --output "$temp" "$url"
  test -s "$temp"
  chmod 644 "$temp"
  mv -f "$temp" "$destination"
  trap - EXIT HUP INT TERM
}
download 'silero-vad' 'silero_vad.onnx' 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx'
download 'gtcrn-denoiser' 'gtcrn_simple.onnx' 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx'
download 'campplus-sv-zh-en-16k' 'speaker_embedding.onnx' 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx'
download 'pyannote-segmentation-3-0' 'model.int8.onnx' 'https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/main/model.int8.onnx'
download 'shenava-koochik-v1-5-rnnt' 'encoder.int8.onnx' 'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/encoder.int8.onnx?download=true'
download 'shenava-koochik-v1-5-rnnt' 'decoder.int8.onnx' 'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/decoder.int8.onnx?download=true'
download 'shenava-koochik-v1-5-rnnt' 'joiner.int8.onnx' 'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/joiner.int8.onnx?download=true'
download 'shenava-koochik-v1-5-rnnt' 'tokens.txt' 'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/tokens.txt?download=true'
