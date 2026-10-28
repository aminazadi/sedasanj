<?php
/**
 * Seda Sanj (recuploader) - FreePBX module - sedasanj.ir
 *
 * This is the "frontend" half of the engine/frontends split (plan.md
 * §3.4): everything here is FreePBX-specific GUI/module glue only -
 * fwconsole registration, the settings page, the KVStore-backed settings
 * <-> config.ini translation, the sudoers drop-in, MixMonitor globals
 * injection, and the log viewer. All of the actual work (audio handling,
 * staging, upload, retry queue, state tracking, sweeping) lives in
 * engine/, which has no FreePBX dependency at all and is deployed here
 * verbatim into /usr/local/bin/asterisk-recording-uploader.
 *
 * This module bundles its own copy of engine/ (see install.sh, which
 * copies it in from the repo's top-level engine/ directory at install
 * time) - __DIR__ . '/engine' is expected to exist inside this module's
 * own deployed directory.
 *
 * The only recording path this module provisions is MixMonitor globals
 * (globals_custom.conf) -> bin/mix-stereo.php -> bin/uploader.php. A
 * pre-1.0.0 dialplan-hook path (scorer.py, with scoring/triage) has been
 * removed; see removeLegacyDialplanHook() for the one-way cleanup applied
 * on upgrade.
 *
 * NOTE ON PRIVILEGES: install()/uninstall() perform OS-level provisioning
 * (installing a systemd unit, a sudoers drop-in, editing
 * globals_custom.conf) that requires root. This works reliably when the
 * module is installed via `fwconsole ma installlocal <path>` (which runs as
 * root). If you install purely through the Module Admin GUI and some step
 * is silently skipped due to file permissions, run the bundled
 * install.sh once as root to finish provisioning - see README.md.
 */

namespace FreePBX\modules;

if (!defined('FREEPBX_IS_AUTH')) {
	die('No direct script access allowed');
}

require_once __DIR__ . '/engine/autoload.php';

class Recuploader extends \FreePBX_Helpers implements \BMO {

	const BIN_DIR      = '/usr/local/bin/asterisk-recording-uploader';
	const CONF_DIR     = '/etc/asterisk-recording-uploader';
	const CONF_FILE    = '/etc/asterisk-recording-uploader/config.ini';
	const STATE_DIR    = '/var/lib/asterisk-recording-uploader';
	const SPOOL_DIR    = '/var/spool/asterisk-recording-uploader';
	const LOG_DIR      = '/var/log/asterisk-recording-uploader';
	const SYSTEMD_UNIT = '/etc/systemd/system/asterisk-recording-uploader.service';
	const SUDOERS_FILE = '/etc/sudoers.d/asterisk-recording-uploader';
	const SERVICE_NAME = 'asterisk-recording-uploader.service';

	// The single supported recording path as of 1.0.0: MixMonitor globals in
	// globals_custom.conf pointing at bin/mix-stereo.php -> bin/uploader.php.
	const GLOBALS_FILE = '/etc/asterisk/globals_custom.conf';
	const MIXMON_BEGIN = '; BEGIN recuploader mixmon globals - managed by the Recording Uploader module, do not edit by hand';
	const MIXMON_END   = '; END recuploader mixmon globals';
	// Direct entry point (no more scripts/mix-stereo.sh bash wrapper - the
	// engine's own bin/mix-stereo.php is called straight from MIXMON_POST).
	const MIXMON_ENTRY_POINT = self::BIN_DIR . '/bin/mix-stereo.php';

	// Pre-1.0.0 versions installed a macro-hangupcall-custom hook in
	// extensions_custom.conf that called the now-removed scorer.py on every
	// hangup. That path is retired; these constants exist only so install()
	// can clean up a leftover block from an older install (see
	// removeLegacyDialplanHook()) - nothing re-injects this any more.
	const LEGACY_DIALPLAN_FILE  = '/etc/asterisk/extensions_custom.conf';
	const LEGACY_DIALPLAN_BEGIN = '; BEGIN recuploader dialplan hook - managed by the Recording Uploader module, do not edit by hand';
	const LEGACY_DIALPLAN_END   = '; END recuploader dialplan hook';

	// Tailed by the GUI's log viewer (see readLogLines()). Must match the
	// [logging] log_file this module writes in writeConfigIni(), and the
	// line format Engine\Logger writes it in.
	const LOG_FILE = '/var/log/asterisk-recording-uploader/uploader.log';
	const LOG_LEVELS = array('DEBUG' => 10, 'INFO' => 20, 'WARNING' => 30, 'ERROR' => 40);

	protected $FreePBX = null;

	// Set by writeConfigIni() on its most recent call: null on success, an
	// admin-facing message on failure. Exposed via getLastSaveError() so
	// page.recuploader.php can show an accurate save result instead of
	// always claiming success once the form was posted.
	protected $lastSaveError = null;
	protected $importPreview = null;
	protected $importMessage = null;

	public function __construct($freepbx = null) {
		if ($freepbx == null) {
			throw new \Exception('Not given a FreePBX Object');
		}
		parent::__construct($freepbx);
		$this->FreePBX = $freepbx;
	}

	/* ------------------------------------------------------------------ *
	 * BMO lifecycle
	 * ------------------------------------------------------------------ */

	public function install() {
		$this->assertRuntimeRequirements();
		$freePbxMajor = $this->freePbxMajor();
		$this->createInstallationBackup();
		$this->ensureDirectories();
		$patchStateExisted = is_file(self::STATE_DIR . '/core-patch.json');
		$this->patchCallRecording('apply', $freePbxMajor);
		try {
			$this->installEngine();
			$this->writeConfigIniIfMissing();
			$this->installSystemdUnit();
			$this->installSudoers();
			$this->injectMixmonGlobals();
			$this->removeLegacyDialplanHook();
			$this->reloadDialplan();
			$this->serviceControl('enable');
			$this->serviceControl('start');
		} catch (\Throwable $exc) {
			if (!$patchStateExisted) {
				$this->patchCallRecording('restore', 0);
			}
			throw $exc;
		}
	}

	protected function assertRuntimeRequirements() {
		if (PHP_VERSION_ID < 70400) {
			throw new \RuntimeException('Seda Sanj requires PHP 7.4 or newer.');
		}
		foreach (array('curl', 'json', 'zlib') as $extension) {
			if (!extension_loaded($extension)) {
				throw new \RuntimeException("Seda Sanj requires the PHP {$extension} extension.");
			}
		}
	}

	protected function createInstallationBackup() {
		$existingBackup = trim((string) getenv('SEDA_SANJ_PREINSTALL_BACKUP_DIR'));
		if ($existingBackup !== ''
			&& strpos($existingBackup, '/var/backups/sedasanj-recuploader/') === 0
			&& is_file($existingBackup . '/filesystem.tar.gz')
			&& is_file($existingBackup . '/SHA256SUMS')) {
			$output = array();
			$status = 1;
			@exec('cd ' . escapeshellarg($existingBackup) . ' && sha256sum -c SHA256SUMS 2>&1', $output, $status);
			if ($status === 0) {
				return;
			}
			throw new \RuntimeException('The pre-installation backup created by install.sh failed verification.');
		}
		$helper = __DIR__ . '/backup-installation.sh';
		if (!is_file($helper) || !function_exists('exec')) {
			throw new \RuntimeException('Mandatory installation backup helper is unavailable. No installation changes were applied.');
		}
		@chmod($helper, 0755);
		$output = array();
		$status = 1;
		@exec(escapeshellarg($helper) . ' 2>&1', $output, $status);
		if ($status !== 0) {
			throw new \RuntimeException('Could not create the mandatory installation backup: ' . implode(' ', $output));
		}
		$backupDir = trim((string) end($output));
		if ($backupDir === '' || strpos($backupDir, '/var/backups/sedasanj-recuploader/') !== 0 || !is_dir($backupDir)) {
			throw new \RuntimeException('Installation backup completed without a verifiable backup directory.');
		}
	}

	public function uninstall() {
		$this->patchCallRecording('restore', 0);
		$this->serviceControl('stop');
		$this->serviceControl('disable');
		if (file_exists(self::SYSTEMD_UNIT)) {
			@unlink(self::SYSTEMD_UNIT);
			$this->shell('systemctl daemon-reload 2>&1');
		}
		if (file_exists(self::SUDOERS_FILE)) {
			@unlink(self::SUDOERS_FILE);
		}
		$this->removeMixmonGlobals();
		$this->reloadDialplan();
		$this->shell('rm -rf ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		// Config, state, spool and logs are deliberately left in place so a
		// reinstall doesn't lose upload history / pending retries. Remove
		// them by hand (or with the bundled uninstall.sh --purge) if wanted.
	}

	protected function freePbxMajor() {
		$output = trim((string) @shell_exec('fwconsole --version 2>/dev/null'));
		if (!preg_match('/\b(16|17)(?:\.|\b)/', $output, $match)) {
			throw new \RuntimeException('Seda Sanj supports only FreePBX 16 and 17; detected version is unknown.');
		}
		return (int) $match[1];
	}

	protected function patchCallRecording($action, $major) {
		$helper = __DIR__ . '/patch-callrecording.php';
		if (!is_file($helper) || !function_exists('exec')) {
			if ($action === 'apply') {
				throw new \RuntimeException('Verified FreePBX patch helper is unavailable.');
			}
			return;
		}
		$command = escapeshellarg(PHP_BINARY ?: 'php') . ' ' . escapeshellarg($helper)
			. ' ' . escapeshellarg($action)
			. ' ' . escapeshellarg('/var/www/html/admin/modules/callrecording/functions.inc.php')
			. ' ' . escapeshellarg((string) $major)
			. ' ' . escapeshellarg(self::STATE_DIR) . ' 2>&1';
		$output = array();
		$status = 1;
		@exec($command, $output, $status);
		if ($status !== 0 && $action === 'apply') {
			throw new \RuntimeException('FreePBX core fixture verification failed: ' . implode(' ', $output));
		}
	}

	public function backup() {
		// Recordings themselves are not touched by this module; only its
		// own settings (stored in the FreePBX KVStore) matter for backup,
		// and those are handled automatically by FreePBX's KVStore backup.
	}

	public function restore($backup) {
	}

	/**
	 * Called on every load of this module's admin page. We use it to
	 * process the settings form post and to re-provision (config.ini +
	 * service restart) whenever settings change.
	 */
	public function doConfigPageInit($page) {
		if (isset($_REQUEST['recuploader_import_preview'])) {
			$this->previewImportedProfile();
			return;
		}
		if (isset($_REQUEST['recuploader_import_apply'])) {
			$this->applyImportedProfile();
			return;
		}
		if (isset($_REQUEST['recuploader_save'])) {
			$previous = $this->getSettings();
			$this->saveSettingsFromRequest();
			$settings = $this->getSettings();
			try {
				$this->validateMissedCallSetting($settings);
			} catch (\Throwable $exc) {
				foreach ($previous as $key => $value) { $this->setConfig('recuploader_' . $key, $value); }
				$this->lastSaveError = $this->safeError($exc->getMessage());
				return;
			}
			if ($this->writeConfigIni($settings)) {
				$this->serviceControl('restart');
			}
			// On failure, lastSaveError is set and the service is deliberately
			// NOT restarted - restarting would just reload the OLD config.ini,
			// which could make a write failure look like nothing happened.
		}
	}

	/**
	 * Result of the most recent writeConfigIni() call: null on success, an
	 * admin-facing message on failure. Read by page.recuploader.php.
	 */
	public function getLastSaveError() {
		return $this->lastSaveError;
	}

	public function getImportPreview() {
		return $this->importPreview;
	}

	public function getImportMessage() {
		return $this->importMessage;
	}

	public function getQueueSummary() {
		$summary = array('pending' => 0, 'blocked_credit' => 0, 'failed' => 0, 'last_error' => '');
		$sqlite = self::STATE_DIR . '/state.sqlite';
		$loadedSqlite = false;
		if (extension_loaded('pdo_sqlite') && is_file($sqlite)) {
			try {
				$pdo = new \PDO('sqlite:' . $sqlite);
				foreach ($pdo->query('SELECT status, COUNT(*) AS total FROM jobs GROUP BY status') as $row) {
					$status = isset($summary[$row['status']]) ? $row['status'] : 'pending';
					$summary[$status] += (int) $row['total'];
				}
				$row = $pdo->query("SELECT last_error FROM jobs WHERE last_error IS NOT NULL AND last_error <> '' ORDER BY next_attempt_epoch DESC LIMIT 1")->fetch(\PDO::FETCH_ASSOC);
				if ($row) {
					$summary['last_error'] = $this->safeError($row['last_error']);
				}
				$loadedSqlite = true;
			} catch (\Throwable $exc) {
			}
		}
		if (!$loadedSqlite) {
			foreach (glob(self::SPOOL_DIR . '/pending/*.json') ?: array() as $path) {
				$job = json_decode((string) @file_get_contents($path), true);
				if (!is_array($job)) {
					continue;
				}
				$status = ($job['status'] ?? 'pending') === 'blocked_credit' ? 'blocked_credit' : 'pending';
				$summary[$status]++;
				if (($job['last_error'] ?? '') !== '') {
					$summary['last_error'] = $this->safeError($job['last_error']);
				}
			}
		}
		$summary['failed'] = count(glob(self::SPOOL_DIR . '/failed/*.json') ?: array());
		return $summary;
	}

	public function getMissedCallSummary() {
		$summary = array('queued' => count(glob(self::SPOOL_DIR . '/missed-calls/pending/*.json') ?: array()), 'delivered' => count(glob(self::STATE_DIR . '/sent/*.json') ?: array()), 'failed' => count(glob(self::SPOOL_DIR . '/missed-calls/failed/*.json') ?: array()), 'cdr_available' => false, 'unanswered_ready' => false);
		try {
			$diagnostics = \Engine\CdrSource::connect()->diagnostics();
			$summary['cdr_available'] = !empty($diagnostics['available']);
			$summary['unanswered_ready'] = !empty($diagnostics['unanswered_ready']);
		} catch (\Throwable $exc) {
		}
		return $summary;
	}

	public function getVoicemailSummary() {
		$summary = array('uploaded' => 0, 'ignored' => 0, 'spooled' => 0, 'failed' => 0);
		try {
			require_once self::BIN_DIR . '/autoload.php';
			$cfg = \Engine\Config::load(self::CONF_FILE);
			foreach (\Engine\StateStore::create($cfg)->allEntries() as $key => $entry) {
				if (strpos((string) $key, 'vm:') !== 0) {
					continue;
				}
				$status = $entry['status'] ?? '';
				if (isset($summary[$status])) {
					$summary[$status]++;
				}
			}
		} catch (\Throwable $exc) {
		}
		return $summary;
	}

	/* ------------------------------------------------------------------ *
	 * AJAX (log viewer "Refresh Logs" button - see page.recuploader.php).
	 *
	 * Previously the log viewer was a standalone GET <form> that reloaded
	 * config.php entirely, which reset the page to its default-active tab
	 * (Upload Endpoint) instead of staying on the Logging tab the admin was
	 * looking at. Routing the refresh through BMO's ajax.php (module=
	 * recuploader&command=getlogs) instead means the button can update just
	 * the log <pre> block in place via JS, with no page navigation and no
	 * tab switch at all.
	 * ------------------------------------------------------------------ */

	public function ajaxRequest($req, &$setting) {
		if ($req === 'getlogs') {
			$setting['authenticate'] = true;
			$setting['allowremote'] = false;
			return true;
		}
		return false;
	}

	public function ajaxHandler() {
		if (!isset($_REQUEST['command']) || $_REQUEST['command'] !== 'getlogs') {
			return false;
		}
		$logLevels = array('DEBUG', 'INFO', 'WARNING', 'ERROR');
		$minLevel = (isset($_REQUEST['log_min_level']) && in_array($_REQUEST['log_min_level'], $logLevels, true))
			? $_REQUEST['log_min_level']
			: 'INFO';
		$maxLines = isset($_REQUEST['log_max_lines']) ? max(10, min(2000, (int) $_REQUEST['log_max_lines'])) : 200;
		$lines = $this->readLogLines($minLevel, $maxLines);
		return array(
			'status'    => true,
			'lines'     => array_reverse($lines), // newest first, matching the page's own display order
			'count'     => count($lines),
			'min_level' => $minLevel,
			'max_lines' => $maxLines,
		);
	}

	/* ------------------------------------------------------------------ *
	 * Settings (backed by BMO's built-in per-module key/value store -
	 * $this->getConfig()/$this->setConfig(), no custom SQL table needed)
	 * ------------------------------------------------------------------ */

	// MAINTENANCE NOTE: this used to be one of three places that had to be
	// hand-kept in sync (plan.md §2.5). It's now one of only two: this
	// array (the GUI's own field defaults/labels) and engine/src/Config.php's
	// DEFAULTS (the engine's single source of truth, plan.md §3.6). This
	// array's values should match Config::DEFAULTS - update both together.
	public function defaults() {
		return array(
			// Sedasanj Call Ingest API. Auth via Authorization: Bearer
			// <api-key> (or X-API-Key), multipart/form-data, HTTPS only.
			'endpoint'                 => 'https://api.sedasanj.ir/v1/ingest/calls',
			'api_key'                  => '',
			'auth_header'               => 'Authorization',
			'auth_scheme'               => 'Bearer',
			// Only used for password-protected AES-256 ZIP uploads; sent as
			// the X-CBI-Archive-Password header. Leave blank for normal
			// (WAV / GZIP / unencrypted ZIP) uploads.
			'archive_password'          => '',
			'verify_tls'                => '1',
			'timeout_seconds'           => '60',
			'immediate_retries'         => '2',
			'watch_dir'                 => '/var/spool/asterisk/monitor',
			'missed_calls_enabled'      => '0',
			'missed_calls_poll_interval_seconds' => '30',
			'voicemail_enabled'         => '0',
			'voicemail_spool_dir'       => '/var/spool/asterisk/voicemail',
			'voicemail_folders'         => 'INBOX,Old,Urgent,Work,Family,Friends',
			'voicemail_mailbox_filter'  => '',
			'voicemail_backfill'        => '0',
			'voicemail_sweep_interval_seconds' => '60',
			'voicemail_audio_preference' => 'wav,WAV,gsm',
			'filename_pattern'          => '^(?P<exten>[^-]+)-(?P<date>\d{8})-(?P<time>\d{6})-(?P<uniqueid>[\d.]+)\.(?P<ext>wav|mp3|gsm)$',
			'min_file_age_seconds'      => '3',
			'on_success'                => 'move',
			'move_dir'                  => '/var/spool/asterisk-recording-uploader/uploaded',
			// Local mono archive copy kept alongside the original recording
			// after the stereo file is staged for upload. Encoded via the
			// system ffmpeg binary, which supports gsm (the default) as
			// well as any other format ffmpeg can mux (mp3, ogg, opus,
			// wav, ...) - just set this to the file extension you want.
			// Does not affect what's actually uploaded (always the
			// original stereo recording, optionally gzipped/zipped - see
			// 'gzip_upload'/'archive_password').
			'archive_format'            => 'gsm',
			'max_retries'               => '100',
			'retry_base_seconds'        => '30',
			'retry_max_seconds'         => '3600',
			'credit_retry_seconds'      => '3600',
			'sweep_interval_seconds'    => '300',
			'stale_processing_seconds'  => '600',
			'retention_days'            => '90',
			// Excludes only the raw per-leg files (recv_*/trans_*) that never
			// finished merging - NOT format-specific, so it still excludes them
			// regardless of the configured archive_format. Beyond this, the sweeper
			// only ever acts on stereo_* files still in the recording tree; the
			// local archive file (<n>.<archive_format>) is never uploaded by it.
			'exclude_patterns'          => '^(recv_|trans_).*$',
			'log_level'                 => 'INFO',
			// Gzip the staged copy before uploading (transport detail only - the
			// local archive copy is never gzipped). Off by default. The endpoint
			// is told via the uploaded filename's .gz extension and
			// Content-Type: application/gzip, so the GUI asks for confirmation
			// whenever this is toggled.
			'upload_format'              => 'gzip',
			'gzip_upload'               => '1',
		);
	}

	public function getSettings() {
		$defaults = $this->defaults();
		$out = array();
		foreach ($defaults as $key => $default) {
			$val = $this->getConfig('recuploader_' . $key);
			// Only fall back to the default when the key was never saved at all
			// (getConfig() returns false/null for that). Treating '' the same
			// as "unset" meant an admin who deliberately blanked a field
			// (api_key, move_dir, exclude_patterns, ...) could never make it
			// stick - the very next read (including the one writeConfigIni()
			// does right after a save) silently reverted it to the default,
			// which looks exactly like "my change didn't save."
			$out[$key] = ($val === false || $val === null) ? $default : $val;
		}
		return $out;
	}

	protected function saveSettingsFromRequest() {
		foreach (array_keys($this->defaults()) as $key) {
			if (isset($_REQUEST[$key])) {
				$value = trim((string) $_REQUEST[$key]);
				if (in_array($key, array('api_key', 'archive_password'), true) && $value === '') {
					continue;
				}
				$this->setConfig('recuploader_' . $key, $value);
			} elseif (in_array($key, array('verify_tls', 'missed_calls_enabled', 'voicemail_enabled', 'voicemail_backfill'), true)) {
				// Unchecked checkboxes don't get posted at all.
				$this->setConfig('recuploader_' . $key, '0');
			}
		}
		if (isset($_REQUEST['clear_archive_password']) || (isset($_REQUEST['upload_format']) && $_REQUEST['upload_format'] !== 'zip')) {
			$this->setConfig('recuploader_archive_password', '');
		}
	}

	protected function ensureSession() {
		if (session_status() !== PHP_SESSION_ACTIVE) {
			@session_start();
		}
	}

	protected function previewImportedProfile() {
		try {
			if (!isset($_FILES['config_profile']) || !is_array($_FILES['config_profile'])) {
				throw new \Engine\ConfigProfileError('No configuration file was uploaded');
			}
			$file = $_FILES['config_profile'];
			if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
				throw new \Engine\ConfigProfileError('Configuration upload failed');
			}
			if ((int) ($file['size'] ?? 0) > \Engine\ConfigProfile::MAX_BYTES) {
				throw new \Engine\ConfigProfileError('Configuration file exceeds 64 KiB');
			}
			$json = @file_get_contents($file['tmp_name']);
			if ($json === false) {
				throw new \Engine\ConfigProfileError('Could not read the uploaded configuration');
			}
			$settings = \Engine\ConfigProfile::parse($json);
			$this->validateImportedEnvironment($settings);
			$remote = $this->validateImportedCredentials($settings);
			$this->ensureSession();
			$token = bin2hex(random_bytes(32));
			$_SESSION['recuploader_import'][$token] = array(
				'expires' => time() + 600,
				'settings' => $settings,
			);
			$this->importPreview = array(
				'token' => $token,
				'settings' => \Engine\ConfigProfile::preview($settings),
				'remote' => $remote,
			);
		} catch (\Throwable $exc) {
			$this->lastSaveError = 'Configuration import rejected: ' . $this->safeError($exc->getMessage());
		}
	}

	protected function applyImportedProfile() {
		$this->ensureSession();
		$token = isset($_REQUEST['import_token']) ? (string) $_REQUEST['import_token'] : '';
		$entry = $_SESSION['recuploader_import'][$token] ?? null;
		unset($_SESSION['recuploader_import'][$token]);
		if (!is_array($entry) || ($entry['expires'] ?? 0) < time() || !is_array($entry['settings'] ?? null)) {
			$this->lastSaveError = 'The import preview expired or was already used.';
			return;
		}
		$settings = $entry['settings'];
		$oldSettings = $this->getSettings();
		$oldConfig = is_file(self::CONF_FILE) ? @file_get_contents(self::CONF_FILE) : false;
		$wasActive = $this->serviceIsActive();
		try {
			foreach ($settings as $key => $value) {
				if ($key[0] !== '_' && array_key_exists($key, $this->defaults())) {
					$this->setConfig('recuploader_' . $key, (string) $value);
				}
			}
			if (!$this->writeConfigIni($this->getSettings())) {
				throw new \RuntimeException($this->lastSaveError ?: 'Could not write configuration');
			}
			$this->serviceControl('restart');
			if (!$this->serviceIsActive()) {
				throw new \RuntimeException('Uploader service did not become active after restart');
			}
			$this->importMessage = 'Configuration imported and the uploader service restarted.';
			$this->lastSaveError = null;
		} catch (\Throwable $exc) {
			foreach ($oldSettings as $key => $value) {
				$this->setConfig('recuploader_' . $key, $value);
			}
			if ($oldConfig !== false) {
				$this->atomicWrite(self::CONF_FILE, $oldConfig);
			} else {
				$this->writeConfigIni($oldSettings);
			}
			$this->serviceControl($wasActive ? 'restart' : 'stop');
			$this->lastSaveError = 'Import rolled back: ' . $this->safeError($exc->getMessage());
		}
	}

	protected function validateMissedCallSetting(array $settings) {
		if (($settings['missed_calls_enabled'] ?? '0') !== '1') { return; }
		$diagnostics = \Engine\CdrSource::connect()->diagnostics();
		if (empty($diagnostics['available'])) {
			throw new \RuntimeException('Missed-call CDR source is unavailable or missing required columns.');
		}
		if (empty($diagnostics['unanswered_ready'])) {
			throw new \RuntimeException('Enable unanswered=yes in /etc/asterisk/cdr.conf and reload Asterisk CDR before enabling missed calls.');
		}
	}

	protected function validateImportedEnvironment(array $settings) {
		if (PHP_VERSION_ID < 70400) {
			throw new \RuntimeException('PHP 7.4 or newer is required');
		}
		foreach (array('curl', 'json', 'zlib') as $extension) {
			if (!extension_loaded($extension)) {
				throw new \RuntimeException("Required PHP extension is missing: {$extension}");
			}
		}
		foreach (array($settings['watch_dir'], $settings['move_dir'], self::SPOOL_DIR . '/pending', self::SPOOL_DIR . '/failed') as $dir) {
			$probe = is_dir($dir) ? $dir : dirname($dir);
			if (!is_dir($probe) || !is_writable($probe)) {
				throw new \RuntimeException("Directory is not writable: {$dir}");
			}
		}
		$this->validateMissedCallSetting($settings);
		if ($settings['voicemail_enabled'] === '1'
			&& (!is_dir($settings['voicemail_spool_dir']) || !is_readable($settings['voicemail_spool_dir']))) {
			throw new \RuntimeException('Voicemail spool directory is not readable by the FreePBX uploader service.');
		}
		if ($settings['upload_format'] === 'zip') {
			$machine = php_uname('m');
			$arch = in_array($machine, array('x86_64', 'amd64'), true) ? 'x86_64'
				: (in_array($machine, array('aarch64', 'arm64'), true) ? 'aarch64' : $machine);
			$binary = __DIR__ . '/engine/bin/7zip/7zzs-' . $arch;
			if (!is_file($binary) || !is_executable($binary)) {
				throw new \RuntimeException("ZIP binary is unavailable for architecture {$arch}");
			}
		}
		if ($settings['archive_format'] === 'gsm') {
			$machine = php_uname('m');
			$arch = in_array($machine, array('x86_64', 'amd64'), true) ? 'x86_64'
				: (in_array($machine, array('aarch64', 'arm64'), true) ? 'aarch64' : $machine);
			$moduleEncoder = __DIR__ . '/engine/bin/gsm/gsm-encode-' . $arch;
			$installedEncoder = self::BIN_DIR . '/bin/gsm/gsm-encode-' . $arch;
			foreach (array($moduleEncoder, $installedEncoder) as $encoder) {
				if (is_file($encoder) && !is_executable($encoder)) {
					@chmod($encoder, 0755);
				}
			}
			if (\Engine\Staging::gsmEncoderCommand() === null && !is_executable($installedEncoder)) {
				throw new \RuntimeException("No executable GSM encoder is available for architecture {$arch}");
			}
		}
		if (!in_array($settings['archive_format'], array('gsm', 'wav'), true)) {
			$ffmpeg = \Engine\Staging::ffmpegPath();
			if (strpos($ffmpeg, '/') !== false) {
				if (!is_file($ffmpeg) || !is_executable($ffmpeg)) {
					throw new \RuntimeException('The configured ffmpeg binary is unavailable');
				}
			} elseif (trim((string) @shell_exec('command -v ' . escapeshellarg($ffmpeg) . ' 2>/dev/null')) === '') {
				throw new \RuntimeException('ffmpeg is unavailable for the local archive format');
			}
		}
	}

	protected function validateImportedCredentials(array $settings) {
		$url = preg_replace('#/calls/?$#', '/config/validate', $settings['endpoint']);
		if (!is_string($url) || $url === $settings['endpoint']) {
			throw new \RuntimeException('Endpoint must end with /v1/ingest/calls');
		}
		$headers = array($settings['auth_header'] . ': ' . trim($settings['auth_scheme'] . ' ' . $settings['api_key']));
		if ($settings['archive_password'] !== '') {
			$headers[] = 'X-CBI-Archive-Password: ' . $settings['archive_password'];
		}
		$ch = curl_init($url);
		curl_setopt_array($ch, array(
			CURLOPT_POST => true,
			CURLOPT_POSTFIELDS => '',
			CURLOPT_HTTPHEADER => $headers,
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_TIMEOUT => min(30, (int) $settings['timeout_seconds']),
			CURLOPT_SSL_VERIFYPEER => $settings['verify_tls'] === '1',
			CURLOPT_SSL_VERIFYHOST => $settings['verify_tls'] === '1' ? 2 : 0,
		));
		$body = curl_exec($ch);
		$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$error = curl_error($ch);
		curl_close($ch);
		if ($body === false || $status < 200 || $status >= 300) {
			throw new \RuntimeException($error !== '' ? 'Online validation failed' : "Online validation returned HTTP {$status}");
		}
		$data = json_decode($body, true);
		if (!is_array($data) || ($data['archive_format'] ?? null) !== $settings['upload_format']
			|| !array_key_exists('archive_password_valid', $data) || $data['archive_password_valid'] !== true) {
			throw new \RuntimeException('Online validation reported a transport or archive-password mismatch');
		}
		return array(
			'tenant' => (string) ($data['tenant'] ?? ''),
			'archive_format' => (string) $data['archive_format'],
			'balance_minutes' => $data['balance_minutes'] ?? null,
		);
	}

	protected function safeError($message) {
		return preg_replace('/sk_live_[A-Za-z0-9_\-]+/', '[REDACTED]', (string) $message);
	}

	/* ------------------------------------------------------------------ *
	 * Provisioning helpers
	 * ------------------------------------------------------------------ */

	protected function ensureDirectories() {
		foreach (array(
			self::CONF_DIR,
			self::STATE_DIR,
			self::SPOOL_DIR . '/pending',
			self::SPOOL_DIR . '/failed',
			self::SPOOL_DIR . '/uploaded',
			self::LOG_DIR,
		) as $dir) {
			if (!is_dir($dir)) {
				@mkdir($dir, 0750, true);
			}
		}
		$this->shell('chown -R asterisk:asterisk ' . escapeshellarg(self::CONF_DIR) . ' ' . escapeshellarg(self::STATE_DIR) . ' ' . escapeshellarg(self::SPOOL_DIR) . ' ' . escapeshellarg(self::LOG_DIR) . ' 2>&1');
	}

	/**
	 * Deploys this module's bundled engine/ tree (host-agnostic PHP engine -
	 * no FreePBX classes, see plan.md §3.4) into BIN_DIR verbatim: BIN_DIR
	 * ends up with autoload.php, src/, bin/, config/ at its top level,
	 * exactly mirroring engine/'s own layout - this is required for the
	 * engine's own relative path resolution (Staging::engineRoot(), which
	 * assumes bin/7zip sits next to src/) to work once deployed.
	 */
	protected function installEngine() {
		$engineSrc = __DIR__ . '/engine';
		if (!is_dir($engineSrc)) {
			error_log('recuploader: bundled engine/ directory not found at ' . $engineSrc . ' - module package is incomplete');
			return;
		}
		if (is_dir(self::BIN_DIR)) {
			$this->shell('rm -rf ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		}
		if (!@mkdir(self::BIN_DIR, 0755, true)) {
			error_log('recuploader: could not create ' . self::BIN_DIR);
			return;
		}
		$this->shell('find ' . escapeshellarg($engineSrc . '/bin/7zip') . ' ' . escapeshellarg($engineSrc . '/bin/ffmpeg')
			. ' ' . escapeshellarg($engineSrc . '/bin/gsm') . ' -type f -exec chmod 755 {} \\; 2>/dev/null');
		$this->shell('cp -r ' . escapeshellarg($engineSrc . '/.') . ' ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		$this->shell('chmod -R a+rX ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		// Entry points and vendored binaries need the execute bit; a plain
		// recursive copy from a Windows-edited source tree may not carry it.
		$this->shell('chmod 755 ' . escapeshellarg(self::BIN_DIR . '/bin') . '/*.php 2>&1');
		$this->shell('find ' . escapeshellarg(self::BIN_DIR . '/bin/7zip') . ' ' . escapeshellarg(self::BIN_DIR . '/bin/ffmpeg')
			. ' ' . escapeshellarg(self::BIN_DIR . '/bin/gsm')
			. ' -type f -exec chmod 755 {} \\; 2>/dev/null');
		$this->shell('chown -R asterisk:asterisk ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		foreach (array(
			'autoload.php',
			'bin/service.php',
			'bin/uploader.php',
			'bin/mix-stereo.php',
			'src/Config.php',
			'src/StateStore.php',
			'src/Queue.php',
			'src/IngestMapper.php',
			'src/Sweeper.php',
			'src/VoicemailSweeper.php',
			'src/Voicemail/VoicemailMessage.php',
			'src/MissedCallPoller.php',
			'src/CdrSource.php',
		) as $relativePath) {
			$sourceFile = $engineSrc . '/' . $relativePath;
			$deployedFile = self::BIN_DIR . '/' . $relativePath;
			if (!is_file($sourceFile) || !is_file($deployedFile)
				|| !hash_equals(hash_file('sha256', $sourceFile), hash_file('sha256', $deployedFile))) {
				throw new \RuntimeException("Deployed uploader engine verification failed for {$relativePath}.");
			}
		}

		// Local archive encoding (archive.format) shells out to ffmpeg,
		// resolved in this order: ARU_FFMPEG_PATH env var, then a vendored
		// bin/ffmpeg/ffmpeg-<arch> binary, then $PATH - check both of the
		// latter two here so a missing dependency fails loudly here instead
		// of silently at upload time.
		$arch = trim((string) @shell_exec('uname -m 2>/dev/null'));
		$archTag = in_array($arch, array('x86_64', 'amd64'), true) ? 'x86_64'
			: (in_array($arch, array('aarch64', 'arm64'), true) ? 'aarch64' : $arch);
		$vendoredFfmpeg = self::BIN_DIR . "/bin/ffmpeg/ffmpeg-{$archTag}";
		if (!is_file($vendoredFfmpeg) && trim((string) @shell_exec('command -v ffmpeg 2>/dev/null')) === '') {
			error_log('recuploader: ffmpeg not found on $PATH and no vendored binary at bin/ffmpeg/ffmpeg-'
				. "{$archTag} - archive.format encoding (default: gsm) will fail until either is installed"
				. ' (e.g. apt-get/dnf/yum install ffmpeg) or vendored');
		}
	}

	protected function writeConfigIniIfMissing() {
		if (!file_exists(self::CONF_FILE)) {
			$this->writeConfigIni($this->getSettings());
		}
	}

	protected function writeConfigIni(array $s) {
		$verifyTls = ($s['verify_tls'] === '1' || $s['verify_tls'] === 'true') ? 'true' : 'false';
		$uploadFormat = isset($s['upload_format']) && in_array($s['upload_format'], array('wav', 'gzip', 'zip'), true)
			? $s['upload_format']
			: (($s['archive_password'] ?? '') !== '' ? 'zip' : ((($s['gzip_upload'] ?? '0') === '1') ? 'gzip' : 'wav'));
		$q = function ($value) {
			$value = (string) $value;
			if (strpos($value, "\0") !== false || preg_match('/[\r\n"]/', $value)) {
				throw new \RuntimeException('A configuration value cannot be represented safely in INI format.');
			}
			return '"' . $value . '"';
		};
		$ini = "; Managed by the FreePBX Recording Uploader module.\n"
			. "; Edit via Admin > Seda Sanj in the FreePBX GUI - manual changes\n"
			. "; here will be overwritten the next time settings are saved.\n\n"
			. "[general]\n"
			. "endpoint = \"\"\n"
			. "endpoint_b64 = " . $q(base64_encode($s['endpoint'])) . "\n"
			. "api_key = \"\"\n"
			. "api_key_b64 = " . $q(base64_encode($s['api_key'])) . "\n"
			. "auth_header = " . $q($s['auth_header']) . "\n"
			. "auth_scheme = " . $q($s['auth_scheme']) . "\n"
			. "archive_password = \"\"\n"
			. "archive_password_b64 = " . $q(base64_encode($s['archive_password'])) . "\n"
			. "verify_tls = {$verifyTls}\n"
			. "timeout_seconds = {$s['timeout_seconds']}\n"
			. "immediate_retries = {$s['immediate_retries']}\n\n"
			. "[upload]\n"
			. "format = {$uploadFormat}\n"
			. "method = POST_MULTIPART\n"
			. "file_field_name = file\n"
			. "metadata_mode = form_fields\n"
			. "metadata_json_field_name = metadata\n"
			. "extra_headers =\n"
			. "gzip = " . ($uploadFormat === 'gzip' ? 'true' : 'false') . "\n\n"
			. "[post_upload]\n"
			. "on_success = {$s['on_success']}\n"
			. "move_dir = \"\"\n"
			. "move_dir_b64 = " . $q(base64_encode($s['move_dir'])) . "\n\n"
			. "[archive]\n"
			. "format = " . $q($s['archive_format']) . "\n\n"
			. "[watcher]\n"
			. "watch_dir = \"\"\n"
			. "watch_dir_b64 = " . $q(base64_encode($s['watch_dir'])) . "\n"
			. "filename_pattern = \"\"\n"
			. "filename_pattern_b64 = " . $q(base64_encode($s['filename_pattern'])) . "\n"
			. "state_file = " . self::STATE_DIR . "/watcher_state.json\n"
			. "min_file_age_seconds = {$s['min_file_age_seconds']}\n\n"
			. "[voicemail]\n"
			. "enabled = " . (($s['voicemail_enabled'] ?? '0') === '1' ? 'true' : 'false') . "\n"
			. "spool_dir = \"\"\n"
			. "spool_dir_b64 = " . $q(base64_encode($s['voicemail_spool_dir'])) . "\n"
			. "folders = \"\"\n"
			. "folders_b64 = " . $q(base64_encode($s['voicemail_folders'])) . "\n"
			. "mailbox_filter = " . $q($s['voicemail_mailbox_filter']) . "\n"
			. "backfill = " . (($s['voicemail_backfill'] ?? '0') === '1' ? 'true' : 'false') . "\n"
			. "sweep_interval_seconds = " . (int) $s['voicemail_sweep_interval_seconds'] . "\n"
			. "audio_preference = " . $q($s['voicemail_audio_preference']) . "\n\n"
			. "[missed_calls]\n"
			. "enabled = " . (($s['missed_calls_enabled'] ?? '0') === '1' ? 'true' : 'false') . "\n"
			. "poll_interval_seconds = " . max(10, min(3600, (int) ($s['missed_calls_poll_interval_seconds'] ?? 30))) . "\n"
			. "settle_seconds = 15\n"
			. "overlap_seconds = 120\n"
			. "cursor_file = " . self::STATE_DIR . "/missed-calls-cursor.json\n"
			. "spool_dir = " . self::SPOOL_DIR . "/missed-calls/pending\n"
			. "failed_dir = " . self::SPOOL_DIR . "/missed-calls/failed\n\n"
			. "[queue]\n"
			. "spool_dir = " . self::SPOOL_DIR . "/pending\n"
			. "failed_dir = " . self::SPOOL_DIR . "/failed\n"
			. "max_retries = {$s['max_retries']}\n"
			. "retry_base_seconds = {$s['retry_base_seconds']}\n"
			. "retry_max_seconds = {$s['retry_max_seconds']}\n"
			. "credit_retry_seconds = {$s['credit_retry_seconds']}\n\n"
			. "[state]\n"
			. "state_file = " . self::STATE_DIR . "/state.json\n"
			. "sweep_interval_seconds = {$s['sweep_interval_seconds']}\n"
			. "stale_processing_seconds = {$s['stale_processing_seconds']}\n"
			. "recursive_scan = true\n"
			. "exclude_patterns = \"\"\n"
			. "exclude_patterns_b64 = " . $q(base64_encode($s['exclude_patterns'])) . "\n"
			. "retention_days = {$s['retention_days']}\n\n"
			. "[logging]\n"
			. "log_file = " . self::LOG_DIR . "/uploader.log\n"
			. "log_level = {$s['log_level']}\n"
			. "use_syslog = true\n";

		$directory = dirname(self::CONF_FILE);
		if (!is_dir($directory) && !@mkdir($directory, 0750, true)) {
			$this->lastSaveError = 'Could not create the configuration directory.';
			return false;
		}
		$temp = @tempnam($directory, '.recuploader-');
		if ($temp === false || @file_put_contents($temp, $ini, LOCK_EX) === false) {
			if ($temp !== false) {
				@unlink($temp);
			}
			$this->lastSaveError = 'Could not write ' . self::CONF_FILE
				. ' - the FreePBX web GUI process does not have permission to write'
				. ' that file. Check its ownership (should be readable/writable by'
				. ' whichever user the GUI runs as) or run install.sh as root to reset it.';
			error_log('recuploader: failed to write ' . self::CONF_FILE . ' - check ownership/permissions');
			return false;
		}
		$handle = @fopen($temp, 'rb');
		if ($handle !== false) {
			if (function_exists('fsync')) {
				@fsync($handle);
			}
			@fclose($handle);
		}
		$this->lastSaveError = null;
		try {
			$parsed = \Engine\Config::load($temp);
		} catch (\Throwable $exc) {
			$parsed = null;
			error_log('recuploader: generated configuration parse-back failed: ' . $this->safeError($exc->getMessage()));
		}
		$mismatches = array();
		$expected = array(
			'general.endpoint' => array($parsed['general']['endpoint'] ?? null, $s['endpoint']),
			'general.api_key' => array($parsed['general']['api_key'] ?? null, $s['api_key']),
			'general.archive_password' => array($parsed['general']['archive_password'] ?? null, $s['archive_password']),
			'upload.format' => array($parsed['upload']['format'] ?? null, $uploadFormat),
			'post_upload.move_dir' => array($parsed['post_upload']['move_dir'] ?? null, $s['move_dir']),
			'watcher.watch_dir' => array($parsed['watcher']['watch_dir'] ?? null, $s['watch_dir']),
			'watcher.filename_pattern' => array($parsed['watcher']['filename_pattern'] ?? null, $s['filename_pattern']),
			'voicemail.enabled' => array($parsed['voicemail']['enabled'] ?? null, ($s['voicemail_enabled'] ?? '0') === '1'),
			'missed_calls.enabled' => array($parsed['missed_calls']['enabled'] ?? null, ($s['missed_calls_enabled'] ?? '0') === '1'),
			'missed_calls.poll_interval_seconds' => array($parsed['missed_calls']['poll_interval_seconds'] ?? null, (int) ($s['missed_calls_poll_interval_seconds'] ?? 30)),
			'voicemail.spool_dir' => array($parsed['voicemail']['spool_dir'] ?? null, $s['voicemail_spool_dir']),
			'state.exclude_patterns' => array($parsed['state']['exclude_patterns'] ?? null, $s['exclude_patterns']),
		);
		foreach ($expected as $field => $values) {
			if ($values[0] !== $values[1]) {
				$mismatches[] = $field;
			}
		}
		if (!is_array($parsed) || $mismatches) {
			$this->lastSaveError = 'The generated configuration failed parse-back validation'
				. ($mismatches ? ' for: ' . implode(', ', $mismatches) : '') . '.';
			@unlink($temp);
			return false;
		}
		@chmod($temp, 0640);
		if (!@rename($temp, self::CONF_FILE)) {
			@unlink($temp);
			$this->lastSaveError = 'Could not atomically replace ' . self::CONF_FILE . '.';
			return false;
		}
		@chmod(self::CONF_FILE, 0640);
		$this->shell('chown asterisk:asterisk ' . escapeshellarg(self::CONF_FILE) . ' 2>&1');
		return true;
	}

	protected function atomicWrite($path, $contents) {
		$directory = dirname($path);
		if (!is_dir($directory) && !@mkdir($directory, 0750, true)) {
			return false;
		}
		$temp = @tempnam($directory, '.recuploader-');
		if ($temp === false) {
			return false;
		}
		$ok = @file_put_contents($temp, $contents, LOCK_EX) !== false;
		if ($ok) {
			$handle = @fopen($temp, 'rb');
			if ($handle !== false) {
				if (function_exists('fsync')) {
					@fsync($handle);
				}
				@fclose($handle);
			}
			$ok = @rename($temp, $path);
		}
		if (!$ok) {
			@unlink($temp);
		}
		return $ok;
	}

	protected function installSystemdUnit() {
		$unit = "[Unit]\n"
			. "Description=Asterisk Recording Uploader module (combined sweeper + retry queue)\n"
			. "After=network-online.target asterisk.service\n"
			. "Wants=network-online.target\n\n"
			. "[Service]\n"
			. "Type=simple\n"
			. "Environment=ARU_CONFIG=" . self::CONF_FILE . "\n"
			// php-cli is resolved through $PATH when the service actually starts
			// (not hardcoded here) - it is not always at /usr/bin/php, and this
			// must stay in sync with systemd/asterisk-recording-uploader.service.
			. "ExecStart=/bin/bash -c 'exec \"\$(command -v php)\" " . self::BIN_DIR . "/bin/service.php'\n"
			. "Restart=on-failure\n"
			. "RestartSec=5\n"
			. "User=asterisk\n"
			. "Group=asterisk\n"
			. "NoNewPrivileges=true\n"
			. "ProtectSystem=full\n"
			. "ProtectHome=true\n\n"
			. "[Install]\n"
			. "WantedBy=multi-user.target\n";

		if (@file_put_contents(self::SYSTEMD_UNIT, $unit) === false) {
			error_log('recuploader: failed to write ' . self::SYSTEMD_UNIT . ' - check ownership/permissions');
		}
		$this->shell('systemctl daemon-reload 2>&1');
	}

	/**
	 * Least-privilege sudoers drop-in so the GUI (running as the asterisk
	 * user on the FreePBX distro) can control just this one service,
	 * without needing broader root access.
	 */
	protected function installSudoers() {
		$line = "asterisk ALL=(root) NOPASSWD: /bin/systemctl start " . self::SERVICE_NAME . ", "
			. "/bin/systemctl stop " . self::SERVICE_NAME . ", "
			. "/bin/systemctl restart " . self::SERVICE_NAME . ", "
			. "/bin/systemctl enable " . self::SERVICE_NAME . ", "
			. "/bin/systemctl disable " . self::SERVICE_NAME . ", "
			. "/bin/systemctl status " . self::SERVICE_NAME . "\n";
		if (@file_put_contents(self::SUDOERS_FILE, $line) === false) {
			error_log('recuploader: failed to write ' . self::SUDOERS_FILE . ' - check ownership/permissions');
		}
		@chmod(self::SUDOERS_FILE, 0440);
	}

	protected function serviceControl($action) {
		// Try direct first (works when running as root, e.g. via
		// `fwconsole ma installlocal`), fall back to sudo (works when the
		// GUI process is the asterisk user and installSudoers() ran ok).
		$this->shell('systemctl ' . escapeshellarg($action) . ' ' . self::SERVICE_NAME . ' 2>&1');
		$this->shell('sudo -n systemctl ' . escapeshellarg($action) . ' ' . self::SERVICE_NAME . ' 2>&1');
	}

	protected function serviceIsActive() {
		if (!function_exists('exec')) {
			return true;
		}
		$status = 1;
		@exec('systemctl is-active --quiet ' . self::SERVICE_NAME . ' 2>/dev/null', $unused, $status);
		return $status === 0;
	}

	/**
	 * Injects the MIXMON_DIR/MONITOR_REC_OPTION/MIXMON_POST globals (see
	 * dialplan/globals-custom-mixmon.conf) into globals_custom.conf, the
	 * same idempotent, marker-delimited way the old dialplan hook used to be
	 * injected. Previously this only happened via install.sh; doing it here
	 * too means a plain `fwconsole ma install` (GUI-only, no root shell
	 * access) provisions the module's one recording path as well.
	 *
	 * MIXMON_POST resolves php via `command -v` at call time (same pattern
	 * as installSystemdUnit()) rather than assuming /usr/bin/php, since
	 * Asterisk's own environment when running MIXMON_POST may have a
	 * minimal $PATH and php-cli isn't always at a fixed location.
	 */
	protected function injectMixmonGlobals() {
		$existing = file_exists(self::GLOBALS_FILE) ? file_get_contents(self::GLOBALS_FILE) : '';
		if (strpos($existing, self::MIXMON_BEGIN) !== false) {
			return; // already installed
		}
		$block = "\n" . self::MIXMON_BEGIN . "\n"
			. "MIXMON_DIR=/var/spool/asterisk/monitor/\n"
			. "MONITOR_REC_OPTION=br(\${MIXMON_DIR}\${YEAR}/\${MONTH}/\${DAY}/recv_\${CALLFILENAME}.\${MON_FMT})t(\${MIXMON_DIR}\${YEAR}/\${MONTH}/\${DAY}/trans_\${CALLFILENAME}.\${MON_FMT})\n"
			. "MIXMON_POST=/bin/bash -c 'exec \"\$(command -v php)\" " . self::MIXMON_ENTRY_POINT . " \"\$@\"' _ \${MIXMON_DIR}\${YEAR}/\${MONTH}/\${DAY}/ \${CALLFILENAME} \${UNIQUEID} \${CALLERID(num)} \${CDR(dnid)} \${CDR(duration)} \${CDR(dst)} \${FROM_DID}\n"
			. self::MIXMON_END . "\n";
		if (@file_put_contents(self::GLOBALS_FILE, $existing . $block) === false) {
			error_log('recuploader: failed to write ' . self::GLOBALS_FILE . ' - check ownership/permissions');
		}
	}

	protected function removeMixmonGlobals() {
		if (!file_exists(self::GLOBALS_FILE)) {
			return;
		}
		$existing = file_get_contents(self::GLOBALS_FILE);
		$pattern = '/\n?' . preg_quote(self::MIXMON_BEGIN, '/') . '.*?' . preg_quote(self::MIXMON_END, '/') . '\n?/s';
		$updated = preg_replace($pattern, "\n", $existing);
		if (@file_put_contents(self::GLOBALS_FILE, $updated) === false) {
			error_log('recuploader: failed to write ' . self::GLOBALS_FILE . ' - check ownership/permissions');
		}
	}

	/**
	 * One-way cleanup for boxes upgrading from a pre-1.0.0 install: removes
	 * the old macro-hangupcall-custom block (which called the now-deleted
	 * scorer.py) from extensions_custom.conf, if present. Never re-adds it -
	 * that dialplan-hook path is retired; mixmon is the only supported path.
	 */
	protected function removeLegacyDialplanHook() {
		if (!file_exists(self::LEGACY_DIALPLAN_FILE)) {
			return;
		}
		$existing = file_get_contents(self::LEGACY_DIALPLAN_FILE);
		if (strpos($existing, self::LEGACY_DIALPLAN_BEGIN) === false) {
			return; // nothing to clean up
		}
		$pattern = '/\n?' . preg_quote(self::LEGACY_DIALPLAN_BEGIN, '/') . '.*?' . preg_quote(self::LEGACY_DIALPLAN_END, '/') . '\n?/s';
		$updated = preg_replace($pattern, "\n", $existing);
		if (@file_put_contents(self::LEGACY_DIALPLAN_FILE, $updated) === false) {
			error_log('recuploader: failed to clean up legacy dialplan hook in ' . self::LEGACY_DIALPLAN_FILE . ' - check ownership/permissions');
		}
	}

	/**
	 * Tails this module's own log file for the GUI's log viewer, filtering
	 * by minimum severity. Best-effort: only reads the last ~2MB of the
	 * file (logs rotate at 10MB, see Engine\Logger) so a large log can't
	 * stall the page.
	 *
	 * Lines are matched against the format Engine\Logger::log() uses
	 * ("<ts> [<pid>] LEVEL name: message") to find the level; a line that
	 * doesn't look like the start of a record (e.g. a continuation line of a
	 * multi-line error) is only kept when showing every level, so it can't
	 * be misattributed to a level it didn't declare.
	 */
	public function readLogLines($minLevel = 'INFO', $maxLines = 200) {
		if (!file_exists(self::LOG_FILE) || !is_readable(self::LOG_FILE)) {
			return array();
		}
		$minSeverity = isset(self::LOG_LEVELS[$minLevel]) ? self::LOG_LEVELS[$minLevel] : self::LOG_LEVELS['INFO'];

		$maxBytes = 2 * 1024 * 1024; // 2MB
		$size = filesize(self::LOG_FILE);
		$fh = @fopen(self::LOG_FILE, 'r');
		if ($fh === false) {
			return array();
		}
		if ($size !== false && $size > $maxBytes) {
			fseek($fh, $size - $maxBytes);
			fgets($fh); // discard the partial first line from seeking mid-line
		}

		$matched = array();
		while (($line = fgets($fh)) !== false) {
			if (preg_match('/\]\s+(DEBUG|INFO|WARNING|ERROR)\s/', $line, $m)) {
				if (self::LOG_LEVELS[$m[1]] < $minSeverity) {
					continue;
				}
			} elseif ($minSeverity > self::LOG_LEVELS['DEBUG']) {
				continue;
			}
			$matched[] = rtrim($line, "\r\n");
		}
		fclose($fh);

		if (count($matched) > $maxLines) {
			$matched = array_slice($matched, -$maxLines);
		}
		return $matched;
	}

	protected function reloadDialplan() {
		$this->shell('fwconsole reload 2>&1');
	}

	protected function shell($cmd) {
		if (function_exists('shell_exec')) {
			@shell_exec($cmd);
		}
	}
}
