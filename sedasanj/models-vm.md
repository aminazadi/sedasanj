# VM مستقل مدل‌ها

Ubuntu 24.04، حدود ۱۲۸ گیگ رم و ۶۴ هسته.

مدل‌ها را روی خود سیستم اجرا کن. Postgres / Redis / MinIO / API را داخل Docker بگذار. Ollama لازم نیست.

| سرویس | پورت |
| --- | --- |
| Whisper (ASR) | `8080` |
| تحلیل متن | `8081` |
| دستیار کدنویسی | `8082` |

---

## ۱) پایه

```bash
sudo apt update && sudo apt install -y build-essential cmake git python3-venv ffmpeg docker.io docker-compose-v2
sudo mkdir -p /srv/models /opt/src
sudo usermod -aG docker $USER   # یک‌بار logout
pip install -U huggingface_hub
```

---

## ۲) مدل‌ها

```bash
# تحلیل متن — یکی از این دو
hf download bartowski/Qwen_Qwen3-14B-GGUF Qwen_Qwen3-14B-Q4_K_M.gguf --local-dir /srv/models
# یا Dorna 8B به‌صورت GGUF (Q4_K_M یا Q5_K_M)

# دستیار کد
hf download unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF --include "*Q4_K_M*" --local-dir /srv/models

# ASR فارسی: وزن HF را به ggml تبدیل کن
hf download vhdm/whisper-large-fa-v1 --local-dir /srv/models/whisper-fa-hf
git clone --depth 1 https://github.com/ggml-org/whisper.cpp /opt/src/whisper.cpp
cd /opt/src/whisper.cpp
python3 -m pip install -r models/requirements-convert.txt
python3 models/convert-h5-to-ggml.py /srv/models/whisper-fa-hf ./ /srv/models
mv /srv/models/ggml-model.bin /srv/models/whisper-large-fa-v1.bin
```

اگر تبدیل HF گیر کرد، موقتاً `large-v3-turbo` آماده را بگیر:

```bash
./models/download-ggml-model.sh large-v3-turbo
```

---

## ۳) بیلد و اجرا

```bash
# whisper.cpp
cd /opt/src/whisper.cpp
cmake -B build -DGGML_NATIVE=ON && cmake --build build -j --config Release
./build/bin/whisper-server -m /srv/models/whisper-large-fa-v1.bin \
  --host 0.0.0.0 --port 8080 --language fa --threads 8 --convert

# llama.cpp
git clone --depth 1 https://github.com/ggml-org/llama.cpp /opt/src/llama.cpp
cd /opt/src/llama.cpp
cmake -B build -DGGML_NATIVE=ON && cmake --build build -j --config Release

# تحلیل تماس
./build/bin/llama-server -m /srv/models/Qwen_Qwen3-14B-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8081 --ctx-size 8192 --threads 16 --parallel 2 --jinja

# دستیار برنامه‌نویسی
./build/bin/llama-server -m /srv/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8082 --ctx-size 32768 --threads 24 --parallel 1 --jinja
```

این سه را بعداً با systemd دائمی کن. برای استخراج JSON در Qwen3، در پرامپت `/no_think` بگذار تا reasoning قاطی خروجی نشود.

---

## ۴) Docker (داده + API)

```yaml
# /srv/stack/compose.yml
services:
  postgres:
    image: postgres:16
    environment: { POSTGRES_PASSWORD: CHANGE_ME }
    volumes: [pg:/var/lib/postgresql/data]
  redis:
    image: redis:7
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment: { MINIO_ROOT_USER: cbi, MINIO_ROOT_PASSWORD: CHANGE_ME }
    volumes: [minio:/data]
volumes: { pg: {}, minio: {} }
```

```bash
cd /srv/stack && docker compose up -d
```

API را هم همین‌جا در Compose بیاور و برای دسترسی به مدل‌های اجراشده روی host این نگاشت را به
سرویس API اضافه کن:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

سپس API را به این آدرس‌ها وصل کن:

- ASR: `http://host.docker.internal:8080/v1/audio/transcriptions`
- تحلیل: `http://host.docker.internal:8081/v1/chat/completions`
- کد: `http://host.docker.internal:8082/v1/chat/completions`

PostgreSQL، Redis و کنسول MinIO نباید publish شوند. اگر API یا فایل صوتی باید از NPM بیرونی
دردسترس باشد، فقط همان پورت‌های لازم را مطابق `deploy/compose.yml` روی IP مشخص VPS publish کنید.

---

## تقسیم ۶۴ هسته / ۱۲۸ گیگ

| سرویس | هسته | رم حدودی |
| --- | --- | --- |
| Whisper | ۸ | ۴ گیگ |
| Qwen3-14B یا Dorna | ۱۶ | ۱۵ / ۸ گیگ |
| Coder 30B-A3B | ۲۴ | ۲۵ گیگ |
| Docker | بقیه | ۲۰–۳۰ گیگ |

Qwen3-14B و Dorna را **همزمان** لود نکن؛ یکی را برای تحلیل انتخاب کن. هر سه سرویس inference با این تقسیم داخل ۱۲۸ گیگ جا می‌شوند.

فایروال: این پورت‌ها را فقط به شبکهٔ داخلی باز بگذار، نه اینترنت.
