export type AgentArchiveFormat = "wav" | "gzip" | "zip";

export function pythonAgentConfig(
  origin: string,
  secret: string,
  format: AgentArchiveFormat,
  password: string,
): string {
  const passwordLine = password ? `\npassword = ${JSON.stringify(password)}` : "";
  return `[server]\nbase_url = ${JSON.stringify(origin)}\ntimeout_seconds = 60\n\n[auth]\napi_key = ${JSON.stringify(secret)}\n\n[archive]\nformat = ${JSON.stringify(format)}${passwordLine}\n\n[asterisk]\nami_host = "127.0.0.1"\nami_port = 5038\nami_user = "cbi"\nami_secret = "CHANGE_ME"\nmonitor_dir = "/var/spool/asterisk/monitor"\n\n[audio]\nsample_rate = 8000\nchannels = 2\ndelete_after_upload = true\n\n[retry]\nmax_attempts = 100\nbackoff_seconds = 30\nretry_max_seconds = 3600\ncredit_retry_seconds = 3600\n\n[spool]\ndir = "/var/lib/cbi-agent/spool"\n`;
}

export function freePbxModuleConfig(
  origin: string,
  keyId: string,
  keyPrefix: string,
  secret: string,
  format: AgentArchiveFormat,
  password: string,
  generatedAt = new Date().toISOString(),
): string {
  return JSON.stringify(
    {
      schema: "sedasanj.freepbx.recuploader.config",
      version: 1,
      target: "freepbx-module",
      generated_at: generatedAt,
      profile: { api_key_id: keyId, api_key_prefix: keyPrefix },
      settings: {
        general: {
          endpoint: `${origin.replace(/\/$/, "")}/v1/ingest/calls`,
          api_key: secret,
          auth_header: "Authorization",
          auth_scheme: "Bearer",
          archive_password: password,
          verify_tls: true,
          timeout_seconds: 60,
          immediate_retries: 2,
        },
        upload: { format },
        post_upload: {
          on_success: "move",
          move_dir: "/var/spool/asterisk-recording-uploader/uploaded",
        },
        archive: { format: "gsm" },
        watcher: {
          watch_dir: "/var/spool/asterisk/monitor",
          filename_pattern: "^(?P<exten>[^-]+)-(?P<date>\\d{8})-(?P<time>\\d{6})-(?P<uniqueid>[\\d.]+)\\.(?P<ext>wav|mp3|gsm)$",
          min_file_age_seconds: 3,
          exclude_patterns: "^(recv_|trans_).*$",
        },
        queue: {
          max_retries: 100,
          retry_base_seconds: 30,
          retry_max_seconds: 3600,
          credit_retry_seconds: 3600,
        },
        state: {
          sweep_interval_seconds: 300,
          stale_processing_seconds: 600,
          retention_days: 90,
        },
        logging: { log_level: "INFO" },
      },
    },
    null,
    2,
  ) + "\n";
}
