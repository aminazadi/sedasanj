# cbi-agent

Python daemon that runs on the customer PBX. It listens to AMI, and on `Hangup`
locates the MixMonitor recording, merges the two mono legs to stereo when needed
(left = caller, right = callee), and uploads it to `POST /v1/ingest/calls`.
Failed uploads stay on disk in the spool directory and retry on a timer, so
PBX-side data survives platform downtime.

The upload format is configured per API key. New keys use GZIP or ZIP. ZIP can
optionally use AES-256 encryption; the password is sent only over HTTPS and is
never persisted by the platform in plaintext.

## Install

```bash
sudo mkdir -p /opt/cbi-agent /etc/cbi-agent
python3.12 -m venv /opt/cbi-agent/venv
/opt/cbi-agent/venv/bin/pip install /path/to/cbi_voice_analytics-*.whl
sudo cp cbi-agent.toml.example /etc/cbi-agent/cbi-agent.toml   # then edit the API key
sudo cp systemd/cbi-agent.service /etc/systemd/system/
sudo systemctl enable --now cbi-agent
```

Requirements: `ffmpeg` on the PBX (leg merge), AMI user with `read = call`, and
the dialplan snippet in `dialplan/cbi-record.conf`.

## Check connectivity

```bash
/opt/cbi-agent/venv/bin/cbi-agent --config /etc/cbi-agent/cbi-agent.toml --drain-only
```

`GET /v1/ingest/health` validates the API key from the panel's install page.
It also reports the archive format and whether the key requires a ZIP password.

Permanent rejections are moved to the spool `failed` directory. The recording
and generated archive remain available for inspection and manual replay.
