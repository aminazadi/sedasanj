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

	// Self-update (see bin/sedasanj-recuploader-update.sh). CONF_DIR is
	// chowned to asterisk, so the helper verifies against its own copy of
	// the signing key in UPDATE_ROOT_DIR, which only root can write; the
	// CONF_DIR copy is only the GUI's early check. UPDATES_DIR (asterisk)
	// holds downloads and job.json; UPDATE_STATUS_DIR (root, world
	// readable) holds the helper's status.json per job.
	const UPDATE_HELPER     = '/usr/local/sbin/sedasanj-recuploader-update';
	const UPDATE_ROOT_DIR   = '/etc/sedasanj-recuploader-update';
	const UPDATE_PUBKEY     = '/etc/asterisk-recording-uploader/release-signing.pub';
	const UPDATES_DIR       = '/var/spool/asterisk-recording-uploader/updates';
	const UPDATE_STATUS_DIR = '/var/lib/sedasanj-recuploader-update/jobs';
	const UPDATE_CACHE_SECONDS = 60;
	const UPDATE_STALE_SECONDS = 1200;

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

	/**
	 * FreePBX lifecycle hook. Module Admin runs this inside the web request as the web user
	 * (no root), `fwconsole ma install` may run it as root, and the update helper always does.
	 *
	 * - As root: provisions the whole OS side (see provision()).
	 * - Without root: registers the module and marks it "activation required". It never throws
	 *   for lack of privileges, so the Module Admin install succeeds; the module page then
	 *   shows the one root command (activate.sh) that finishes the job.
	 */
	public function install() {
		$this->assertRuntimeRequirements();
		$this->freePbxMajor();
		if ($this->isRoot()) {
			$this->provision();
			return true;
		}
		$this->recordActivation('pending', 'SS-SYS-1004', 'Installed without root privileges; run activate.sh as root to finish.');
		return true;
	}

	/** The CLI php, never the FPM/Apache binary that PHP_BINARY points at under the web GUI. */
	protected function phpCli() {
		if (PHP_SAPI === 'cli' && PHP_BINARY) {
			return PHP_BINARY;
		}
		$found = trim((string) @shell_exec('command -v php 2>/dev/null'));
		return $found !== '' ? $found : 'php';
	}

	protected function isRoot() {
		return function_exists('posix_geteuid') && posix_geteuid() === 0;
	}

	/**
	 * Root-only provisioning: mandatory backup, directories, engine, systemd unit, sudoers,
	 * update helper, MixMonitor globals, FreePBX core patch, service start. Called by install()
	 * when running as root and by activate.sh (through the FreePBX bootstrap) after a GUI install.
	 */
	public function provision() {
		if (!$this->isRoot()) {
			throw new \RuntimeException('Provisioning needs root. Run: sudo bash ' . __DIR__ . '/activate.sh');
		}
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
			$this->installUpdateHelper();
			$this->injectMixmonGlobals();
			$this->removeLegacyDialplanHook();
			$this->reloadDialplan();
			$this->serviceControl('enable');
			$this->serviceControl('restart');
		} catch (\Throwable $exc) {
			if (!$patchStateExisted) {
				$this->patchCallRecording('restore', 0);
			}
			$this->recordActivation('failed', 'SS-SYS-1004', $exc->getMessage());
			throw $exc;
		}
		$this->recordActivation('ok', '', '');
	}

	/**
	 * Activation state shown on the module page: 'ok' only when the last root provisioning
	 * finished for exactly the module version whose files are installed and the OS pieces exist.
	 *
	 * @return array{state:string,code:string,message:string,version:string,command:string}
	 */
	public function getActivationStatus() {
		$recorded = json_decode((string) @file_get_contents(self::STATE_DIR . '/activation.json'), true);
		if (!is_array($recorded)) {
			$recorded = array();
		}
		$files = $this->getModuleVersion();
		$state = isset($recorded['state']) ? (string) $recorded['state'] : 'pending';
		$ok = $state === 'ok'
			&& isset($recorded['version']) && $recorded['version'] === $files['files']
			&& file_exists(self::SYSTEMD_UNIT) && file_exists(self::UPDATE_HELPER);
		return array(
			'state' => $ok ? 'ok' : ($state === 'failed' ? 'failed' : 'pending'),
			'code' => isset($recorded['code']) ? (string) $recorded['code'] : 'SS-SYS-1004',
			'message' => isset($recorded['message']) ? (string) $recorded['message'] : '',
			'version' => isset($recorded['version']) ? (string) $recorded['version'] : '',
			'command' => 'sudo bash ' . __DIR__ . '/activate.sh',
		);
	}

	protected function recordActivation($state, $code, $message) {
		$version = $this->getModuleVersion();
		$payload = json_encode(array(
			'state' => $state,
			'code' => $code,
			'message' => $message,
			'version' => $version['files'],
			'time' => gmdate('c'),
		));
		if (!is_dir(self::STATE_DIR)) {
			// Without root (GUI install) the state directory may not exist yet; the status then
			// simply stays "pending", which is the truth.
			if (!@mkdir(self::STATE_DIR, 0755, true)) {
				return;
			}
		}
		$tmp = self::STATE_DIR . '/activation.json.tmp.' . getmypid();
		if (@file_put_contents($tmp, $payload, LOCK_EX) !== false) {
			if (!@rename($tmp, self::STATE_DIR . '/activation.json')) {
				@unlink($tmp);
			}
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
		@unlink(self::UPDATE_HELPER);
		$this->shell('rm -rf ' . escapeshellarg(self::UPDATE_ROOT_DIR) . ' 2>&1');
		$this->removeMixmonGlobals();
		$this->reloadDialplan();
		$this->shell('rm -rf ' . escapeshellarg(self::BIN_DIR) . ' 2>&1');
		// Config, state, spool and logs are deliberately left in place so a
		// reinstall doesn't lose upload history / pending retries. Remove
		// them by hand (or with the bundled uninstall.sh --purge) if wanted.
	}

	/**
	 * Major version of FreePBX (15, 16 or 17). Uses FreePBX's own getversion() when the framework is
	 * loaded (always the case inside Module Admin) and `fwconsole --version` otherwise, and takes
	 * the FIRST number only: a version such as 15.0.17 must never be read as 17.
	 */
	protected function freePbxMajor() {
		$text = '';
		if (function_exists('getversion')) {
			$text = (string) getversion();
		}
		if (!preg_match('/^\s*(?:FreePBX\s+)?(\d+)\./i', $text)) {
			$text = trim((string) @shell_exec('fwconsole --version 2>/dev/null'));
		}
		if (!preg_match('/(?:^|\s)(?:FreePBX\s+)?(\d+)\.\d+/i', $text, $match)) {
			throw new \RuntimeException('Cannot determine the FreePBX version (SS-SYS-1003).');
		}
		$major = (int) $match[1];
		if (!in_array($major, array(15, 16, 17), true)) {
			throw new \RuntimeException("Seda Sanj supports FreePBX 15, 16 and 17; detected {$major} (SS-SYS-1003).");
		}
		return $major;
	}

	protected function patchCallRecording($action, $major) {
		$helper = __DIR__ . '/patch-callrecording.php';
		if (!is_file($helper) || !function_exists('exec')) {
			if ($action === 'apply') {
				throw new \RuntimeException('Verified FreePBX patch helper is unavailable.');
			}
			return;
		}
		$command = escapeshellarg($this->phpCli()) . ' ' . escapeshellarg($helper)
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
	/**
	 * Per-session anti-CSRF token. State-changing requests (settings save,
	 * import preview/apply, update start) must be POST and carry it, so a
	 * crafted link or cross-site form cannot redirect uploads or the API key.
	 */
	public function csrfToken() {
		$this->ensureSession();
		if (empty($_SESSION['recuploader_csrf']) || !is_string($_SESSION['recuploader_csrf'])) {
			$_SESSION['recuploader_csrf'] = bin2hex(random_bytes(32));
		}
		return $_SESSION['recuploader_csrf'];
	}

	protected function csrfValid() {
		if (!isset($_SERVER['REQUEST_METHOD']) || strtoupper($_SERVER['REQUEST_METHOD']) !== 'POST') {
			return false;
		}
		$sent = isset($_POST['sj_csrf']) ? (string) $_POST['sj_csrf'] : '';
		if ($sent === '' && isset($_SERVER['HTTP_X_SJ_CSRF'])) {
			$sent = (string) $_SERVER['HTTP_X_SJ_CSRF'];
		}
		return $sent !== '' && hash_equals($this->csrfToken(), $sent);
	}

	public function doConfigPageInit($page) {
		// Start the session and mint the token before any page output, so the view
		// never has to call session_start() after headers were sent.
		$this->csrfToken();
		if (isset($_REQUEST['recuploader_import_preview']) || isset($_REQUEST['recuploader_import_apply']) || isset($_REQUEST['recuploader_save']) || isset($_REQUEST['recuploader_bundle'])) {
			if (!$this->csrfValid()) {
				$this->lastSaveError = 'The request was rejected: it must be a POST with a valid security token. Reload the page and try again.';
				return;
			}
		}
		if (isset($_REQUEST['recuploader_bundle'])) {
			$this->streamSupportBundle();
			return;
		}
		if (isset($_REQUEST['recuploader_import_preview'])) {
			$this->previewImportedProfile();
			return;
		}
		if (isset($_REQUEST['recuploader_import_apply'])) {
			$this->applyImportedProfile();
			return;
		}
		if (isset($_REQUEST['recuploader_save'])) {
			$invalid = $this->validateManualSettings($_POST);
			if ($invalid !== null) {
				$this->lastSaveError = $invalid . ' Nothing was saved.';
				return;
			}
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
				$this->setConfig('recuploader_update_cache', '');
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
		$summary = array('pending' => 0, 'blocked_credit' => 0, 'blocked_config' => 0, 'failed' => 0, 'last_error' => '');
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
				$jobStatus = isset($job['status']) ? $job['status'] : 'pending';
				$status = in_array($jobStatus, array('blocked_credit', 'blocked_config'), true) ? $jobStatus : 'pending';
				$summary[$status]++;
				if (($job['last_error'] ?? '') !== '') {
					$summary['last_error'] = $this->safeError($job['last_error']);
				}
			}
		}
		$failed = 0;
		foreach (glob(self::SPOOL_DIR . '/failed/*.json') ?: array() as $manifest) {
			// Only failure manifests (sha256 file names), not copied metadata sidecars.
			if (preg_match('/^[0-9a-f]{64}\.json$/', basename($manifest))) {
				$failed++;
			}
		}
		$summary['failed'] = $failed;
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
	 * Health & dependencies tab
	 * ------------------------------------------------------------------ */

	const DEP_JOB_DIR_FALLBACK = '/var/tmp/sedasanj-depjobs';

	protected function runQuiet($command) {
		if (!function_exists('shell_exec')) {
			return null;
		}
		$out = @shell_exec($command . ' 2>/dev/null');
		return is_string($out) ? trim($out) : null;
	}

	protected function findBinary($name) {
		$found = $this->runQuiet('command -v ' . escapeshellarg($name));
		if ($found === null || $found === '') {
			foreach (array('/usr/sbin/', '/usr/local/sbin/', '/sbin/', '/usr/bin/', '/bin/') as $dir) {
				if (@is_executable($dir . $name)) {
					return $dir . $name;
				}
			}
			return null;
		}
		return $found;
	}

	protected function moduleStatusName($status) {
		$names = array(
			'enabled' => defined('MODULE_STATUS_ENABLED') ? MODULE_STATUS_ENABLED : 2,
			'disabled' => defined('MODULE_STATUS_DISABLED') ? MODULE_STATUS_DISABLED : 1,
			'upgrade' => defined('MODULE_STATUS_NEEDUPGRADE') ? MODULE_STATUS_NEEDUPGRADE : 3,
			'broken' => defined('MODULE_STATUS_BROKEN') ? MODULE_STATUS_BROKEN : -1,
		);
		foreach ($names as $label => $value) {
			if ((int) $status === (int) $value) {
				return $label;
			}
		}
		return 'missing';
	}

	/** Collects the host inventory that \Engine\DependencyCheck::evaluate() turns into rows. */
	protected function collectDependencyEnv() {
		$names = array_merge(array_keys(\Engine\DependencyCheck::REQUIRED_MODULES), array_keys(\Engine\DependencyCheck::OPTIONAL_MODULES));
		$modules = array();
		foreach ($names as $name) {
			$info = array();
			try {
				$all = $this->FreePBX->Modules->getInfo($name);
				$info = isset($all[$name]) ? $all[$name] : array();
			} catch (\Throwable $exc) {
				$info = array();
			}
			$version = isset($info['dbversion']) && $info['dbversion'] !== '' ? $info['dbversion'] : (isset($info['version']) ? $info['version'] : '');
			$modules[$name] = array(
				'status' => isset($info['status']) ? $this->moduleStatusName($info['status']) : 'missing',
				'version' => (string) $version,
			);
		}

		$php = $this->phpCli();
		$cliVersion = $this->runQuiet(escapeshellarg($php) . ' -r ' . escapeshellarg('echo PHP_VERSION;'));
		$cliModules = $this->runQuiet(escapeshellarg($php) . ' -m');
		$cliExtensions = null;
		if ($cliModules !== null && $cliModules !== '') {
			$cliExtensions = array();
			foreach (preg_split('/\R/', strtolower($cliModules)) as $line) {
				$line = trim($line);
				if ($line !== '' && $line[0] !== '[') {
					$cliExtensions[$line] = true;
				}
			}
		}
		$webExtensions = array();
		foreach (\Engine\DependencyCheck::WEB_EXTENSIONS as $ext) {
			$webExtensions[$ext] = extension_loaded($ext);
		}

		$arch = $this->runQuiet('uname -m') ?: 'x86_64';
		$arch = $arch === 'arm64' ? 'aarch64' : $arch;
		$bundled = function ($relative) use ($arch) {
			$path = self::BIN_DIR . '/bin/' . str_replace('{arch}', $arch, $relative);
			return @is_executable($path) ? $path : null;
		};
		$binaries = array(
			'unzip' => $this->findBinary('unzip'),
			'sudo' => $this->findBinary('sudo'),
			'systemctl' => $this->findBinary('systemctl'),
			'flock' => $this->findBinary('flock'),
			'ffmpeg' => $bundled('ffmpeg/ffmpeg-{arch}') ?: $this->findBinary('ffmpeg'),
			'gsm' => $bundled('gsm/gsm-encode-{arch}') ?: $this->findBinary('gsm-encode') ?: $this->findBinary('toast'),
		);

		$engine = null;
		if (function_exists('engine_getinfo')) {
			try {
				$info = engine_getinfo();
				$engine = trim((isset($info['engine']) ? $info['engine'] : 'asterisk') . ' ' . (isset($info['version']) ? $info['version'] : ''));
			} catch (\Throwable $exc) {
				$engine = null;
			}
		}
		if ($engine === null) {
			$engine = $this->runQuiet('asterisk -V') ?: null;
		}

		$webroot = (string) $this->FreePBX->Config->get('AMPWEBROOT');
		$webroot = $webroot !== '' ? $webroot : '/var/www/html';
		$patchState = 'unknown';
		$helper = __DIR__ . '/patch-callrecording.php';
		if (is_file($helper)) {
			$state = $this->runQuiet(escapeshellarg($php) . ' ' . escapeshellarg($helper) . ' status '
				. escapeshellarg($webroot . '/admin/modules/callrecording/functions.inc.php') . ' 0 ' . escapeshellarg(self::STATE_DIR));
			$patchState = $state === 'patched' ? 'ok' : ($state === 'unpatched' ? 'drift' : 'unknown');
		}

		$writable = array();
		foreach (array(self::STATE_DIR, self::SPOOL_DIR, self::LOG_DIR) as $dir) {
			$writable[$dir] = is_dir($dir) && is_writable($dir);
		}
		$diskPath = is_dir(self::SPOOL_DIR) ? self::SPOOL_DIR : '/var/spool';
		$free = @disk_free_space($diskPath);

		$activation = $this->getActivationStatus();
		$version = $this->getFreePbxVersionString();
		return array(
			'freepbx_version' => $version,
			'php_web' => PHP_VERSION,
			'php_cli' => $cliVersion,
			'web_extensions' => $webExtensions,
			'cli_extensions' => $cliExtensions,
			'modules' => $modules,
			'binaries' => $binaries,
			'asterisk' => $engine,
			'patch_state' => $patchState,
			'globals_state' => $this->globalsState(),
			'activation' => $activation['state'],
			'service_active' => function_exists('exec') ? $this->serviceIsActive() : null,
			'writable' => $writable,
			'disk_free_mb' => $free === false ? null : (int) ($free / 1048576),
		);
	}

	protected function getFreePbxVersionString() {
		if (function_exists('getversion')) {
			return (string) getversion();
		}
		return (string) $this->runQuiet('fwconsole --version');
	}

	/** 'ok' when globals_custom.conf holds exactly the shipped MixMonitor block, else 'outdated' or 'missing'. */
	protected function globalsState() {
		$shipped = trim((string) @file_get_contents(__DIR__ . '/dialplan/globals-custom-mixmon.conf'));
		$existing = (string) @file_get_contents(self::GLOBALS_FILE);
		$pattern = '/' . preg_quote(self::MIXMON_BEGIN, '/') . '.*?' . preg_quote(self::MIXMON_END, '/') . '/s';
		if ($shipped === '' || preg_match($pattern, $existing, $match) !== 1) {
			return 'missing';
		}
		return trim($match[0]) === $shipped ? 'ok' : 'outdated';
	}

	/** HTML-escapes $text and turns every [SS-AREA-NNNN] code into a link to its help article. */
	public function linkifyErrorCodes($text) {
		$escaped = htmlspecialchars((string) $text, ENT_QUOTES, 'UTF-8');
		return preg_replace_callback('/\(?\[?(SS-[A-Z]{3,4}-\d{4})\]?\)?/', function ($m) {
			$url = \Engine\ErrorCatalog::helpUrl($m[1]);
			return '<a href="' . htmlspecialchars($url, ENT_QUOTES, 'UTF-8') . '" target="_blank" rel="noopener">[' . $m[1] . ']</a>';
		}, $escaped);
	}

	/**
	 * Builds the redacted support bundle with the engine's own script and sends it to the browser.
	 * Runs from doConfigPageInit (before any output) and ends the request.
	 */
	protected function streamSupportBundle() {
		$script = __DIR__ . '/engine/bin/support-bundle.php';
		$tmp = tempnam(sys_get_temp_dir(), 'sjb');
		if ($tmp === false || !is_file($script)) {
			$this->lastSaveError = 'The support bundle could not be created (SS-SVC-1003).';
			return;
		}
		$command = 'ARU_CONFIG=' . escapeshellarg(self::CONF_FILE) . ' ' . escapeshellarg($this->phpCli()) . ' ' . escapeshellarg($script) . ' --out=' . escapeshellarg($tmp . '.tar.gz') . ' 2>&1';
		$output = array();
		$status = 1;
		@exec($command, $output, $status);
		@unlink($tmp);
		$bundle = $tmp . '.tar.gz';
		if ($status !== 0 || !is_file($bundle)) {
			@unlink($bundle);
			$this->lastSaveError = 'The support bundle could not be created: ' . $this->safeError(implode(' ', $output)) . ' (SS-SVC-1003)';
			return;
		}
		while (ob_get_level() > 0) {
			@ob_end_clean();
		}
		header('Content-Type: application/gzip');
		header('Content-Disposition: attachment; filename="sedasanj-support-' . gmdate('Ymd-His') . '.tar.gz"');
		header('Content-Length: ' . filesize($bundle));
		header('Cache-Control: no-store');
		readfile($bundle);
		@unlink($bundle);
		exit;
	}

	public function getDependencyReport() {
		return \Engine\DependencyCheck::evaluate($this->collectDependencyEnv());
	}

	protected function depJobDir() {
		$dir = is_dir(self::STATE_DIR) && is_writable(self::STATE_DIR) ? self::STATE_DIR . '/depjobs' : self::DEP_JOB_DIR_FALLBACK;
		if (!is_dir($dir)) {
			@mkdir($dir, 0750, true);
		}
		return $dir;
	}

	/**
	 * One-click install of a missing FreePBX module through Module Admin's own CLI. Only the
	 * allow-listed modules can be requested, one job runs at a time, and the output is polled
	 * with depstatus.
	 */
	protected function startDependencyInstall($module) {
		$module = (string) $module;
		if (!in_array($module, \Engine\DependencyCheck::INSTALLABLE_MODULES, true) || !preg_match('/^[a-z0-9_]+$/', $module)) {
			return array('status' => false, 'message' => 'That module cannot be installed from here.', 'code' => 'SS-DEP-1001');
		}
		$fwconsole = $this->findBinary('fwconsole');
		if ($fwconsole === null) {
			return array('status' => false, 'message' => 'fwconsole was not found; run: fwconsole ma downloadinstall ' . $module, 'code' => 'SS-DEP-1001');
		}
		$dir = $this->depJobDir();
		foreach (glob($dir . '/*.log') ?: array() as $existing) {
			$tail = (string) @file_get_contents($existing);
			if (strpos($tail, "\nEXIT:") === false && @filemtime($existing) > time() - 900) {
				return array('status' => false, 'message' => 'Another module installation is still running.', 'code' => 'SS-DEP-1001');
			}
		}
		$job = bin2hex(random_bytes(8));
		$log = $dir . '/' . $job . '.log';
		$setsid = $this->runQuiet('command -v setsid') ? 'setsid ' : '';
		$inner = escapeshellarg($fwconsole) . ' ma downloadinstall ' . escapeshellarg($module) . '; echo; echo EXIT:$?';
		@exec($setsid . 'nohup sh -c ' . escapeshellarg($inner) . ' > ' . escapeshellarg($log) . ' 2>&1 < /dev/null &');
		return array('status' => true, 'job' => $job, 'module' => $module);
	}

	protected function getDependencyInstallStatus($job) {
		$job = (string) $job;
		if (!preg_match('/^[a-f0-9]{16}$/', $job)) {
			return array('status' => false, 'message' => 'Invalid job.');
		}
		foreach (array($this->depJobDir(), self::STATE_DIR . '/depjobs', self::DEP_JOB_DIR_FALLBACK) as $dir) {
			$log = $dir . '/' . $job . '.log';
			if (!is_file($log)) {
				continue;
			}
			$text = (string) @file_get_contents($log);
			$done = preg_match('/EXIT:(\d+)\s*$/', $text, $m) === 1;
			return array(
				'status' => true,
				'state' => !$done ? 'running' : ($m[1] === '0' ? 'succeeded' : 'failed'),
				'log_tail' => \Engine\Logger::redact(substr($text, -4000)),
			);
		}
		return array('status' => false, 'message' => 'Job not found.');
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
		if (in_array($req, array('getlogs', 'checkupdate', 'releases', 'startupdate', 'updatestatus', 'deps', 'installdep', 'depstatus'), true)) {
			$setting['authenticate'] = true;
			$setting['allowremote'] = false;
			return true;
		}
		return false;
	}

	public function ajaxHandler() {
		$command = isset($_REQUEST['command']) ? (string) $_REQUEST['command'] : '';
		switch ($command) {
			case 'checkupdate':
				return $this->ajaxCheckUpdate(!empty($_REQUEST['force']));
			case 'releases':
				return $this->ajaxReleases();
			case 'deps':
				return array('status' => true) + $this->getDependencyReport();
			case 'installdep':
				if (!$this->csrfValid()) {
					return array('status' => false, 'message' => 'Request rejected: POST with a valid security token is required.');
				}
				return $this->startDependencyInstall(isset($_REQUEST['module']) ? (string) $_REQUEST['module'] : '');
			case 'depstatus':
				return $this->getDependencyInstallStatus(isset($_REQUEST['job']) ? (string) $_REQUEST['job'] : '');
			case 'startupdate':
				if (!$this->csrfValid()) {
					return array('status' => false, 'message' => 'Update request rejected: POST with a valid security token is required.');
				}
				return $this->startUpdate(isset($_REQUEST['release_id']) ? (string) $_REQUEST['release_id'] : '');
			case 'updatestatus':
				return $this->getUpdateStatus(isset($_REQUEST['job']) ? (string) $_REQUEST['job'] : '');
			case 'getlogs':
				break;
			default:
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
	 * Self-update (page banner, Changelog tab, update progress panel).
	 *
	 * checkupdate runs on every page load: it asks the ingest API for the
	 * latest release (doubling as this host's heartbeat) and reports any
	 * update job still in flight so a reloaded page resumes its progress
	 * view. startupdate downloads and verifies the release as asterisk, then
	 * hands the job to the root helper (UPDATE_HELPER) via sudo; the helper
	 * writes status.json, which updatestatus serves to the poller.
	 * ------------------------------------------------------------------ */

	public function getUpdateCapability() {
		$reasons = array();
		if (!function_exists('sodium_crypto_sign_verify_detached')) {
			$reasons[] = 'sodium';
		}
		if (!function_exists('exec')) {
			$reasons[] = 'exec';
		}
		if (!is_file(self::UPDATE_HELPER)) {
			$reasons[] = 'helper';
		}
		if ($this->updatePublicKey() === null) {
			$reasons[] = 'signing_key';
		}
		return array('auto' => !$reasons, 'reasons' => $reasons);
	}

	protected function updatePublicKey() {
		$text = is_readable(self::UPDATE_PUBKEY) ? @file_get_contents(self::UPDATE_PUBKEY) : false;
		return $text === false ? null : \Engine\ModuleUpdate::parsePublicKey($text);
	}

	protected function hostUuid() {
		$uuid = (string) $this->getConfig('recuploader_host_uuid');
		if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $uuid)) {
			$bytes = random_bytes(16);
			$bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
			$bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
			$uuid = vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($bytes), 4));
			$this->setConfig('recuploader_host_uuid', $uuid);
		}
		return $uuid;
	}

	protected function ajaxCheckUpdate($force) {
		$version = $this->getModuleVersion();
		$result = array(
			'status' => true,
			'current' => $version['files'],
			'capability' => $this->getUpdateCapability(),
			'update_available' => false,
			'latest' => null,
			'changelog' => array(),
			'active_job' => null,
		);
		$active = $this->activeUpdateJob();
		if ($active !== null) {
			$result['active_job'] = $active;
		}
		try {
			$data = $this->fetchUpdateInfo($force);
			$result['update_available'] = $data['update_available'];
			$result['latest'] = $data['latest'];
			$result['changelog'] = $data['changelog'];
		} catch (\Throwable $exc) {
			$result['check_error'] = $this->safeError($exc->getMessage());
		}
		return $result;
	}

	protected function ajaxReleases() {
		try {
			$data = $this->updateApiRequest(\Engine\ModuleUpdate::releasesUrl($this->getSettings()['endpoint']));
			$items = array();
			foreach ((isset($data['items']) && is_array($data['items'])) ? $data['items'] : array() as $item) {
				if (is_array($item)) {
					$items[] = $this->cleanChangelogItem($item);
				}
			}
			return array('status' => true, 'current' => $this->getModuleVersion()['files'], 'items' => $items);
		} catch (\Throwable $exc) {
			return array('status' => false, 'message' => $this->safeError($exc->getMessage()));
		}
	}

	/**
	 * GET /module/updates, cached in the KV store for UPDATE_CACHE_SECONDS
	 * so rapid page reloads don't hammer the API. Cache entries are keyed
	 * by the current version so a finished update re-checks immediately.
	 */
	protected function fetchUpdateInfo($force = false) {
		$current = $this->getModuleVersion()['files'];
		$cached = json_decode((string) $this->getConfig('recuploader_update_cache'), true);
		if (!$force && is_array($cached) && ($cached['current'] ?? null) === $current
			&& (int) ($cached['at'] ?? 0) > time() - self::UPDATE_CACHE_SECONDS && is_array($cached['data'] ?? null)) {
			return $cached['data'];
		}
		$freepbx = '';
		try {
			$freepbx = function_exists('getversion') ? (string) getversion() : '';
		} catch (\Throwable $exc) {
		}
		$url = \Engine\ModuleUpdate::updatesUrl($this->getSettings()['endpoint'], array(
			'current' => $current,
			'freepbx' => $freepbx,
			'php' => PHP_VERSION,
			'host_uuid' => $this->hostUuid(),
			'hostname' => (string) gethostname(),
			'service' => $this->getServiceStatus(),
		));
		$raw = $this->updateApiRequest($url);
		$latest = null;
		if (is_array($raw['latest'] ?? null)) {
			$l = $raw['latest'];
			$latest = array(
				'id' => (string) ($l['id'] ?? ''),
				'version' => (string) ($l['version'] ?? ''),
				'severity' => $this->cleanSeverity($l['severity'] ?? ''),
				'title' => (string) ($l['title'] ?? ''),
				'size' => (int) ($l['size'] ?? 0),
				'sha256' => strtolower((string) ($l['sha256'] ?? '')),
				'signature' => (string) ($l['signature'] ?? ''),
				'published_at' => (string) ($l['published_at'] ?? ''),
			);
			if (!\Engine\ModuleUpdate::isReleaseId($latest['id']) || !\Engine\ModuleUpdate::isVersion($latest['version'])) {
				$latest = null;
			}
		}
		$changelog = array();
		foreach (is_array($raw['changelog'] ?? null) ? $raw['changelog'] : array() as $item) {
			if (is_array($item)) {
				$changelog[] = $this->cleanChangelogItem($item);
			}
		}
		$data = array(
			'update_available' => !empty($raw['update_available']) && $latest !== null && version_compare($latest['version'], $current, '>'),
			'latest' => $latest,
			'changelog' => $changelog,
		);
		$this->setConfig('recuploader_update_cache', json_encode(array('at' => time(), 'current' => $current, 'data' => $data)));
		return $data;
	}

	protected function cleanSeverity($value) {
		return in_array($value, array('normal', 'recommended', 'critical', 'security'), true) ? $value : 'normal';
	}

	protected function cleanChangelogItem(array $item) {
		return array(
			'version' => (string) ($item['version'] ?? ''),
			'title' => (string) ($item['title'] ?? ''),
			'severity' => $this->cleanSeverity($item['severity'] ?? ''),
			'html' => $this->sanitizeChangelogHtml((string) ($item['html'] ?? '')),
			'published_at' => (string) ($item['published_at'] ?? ''),
		);
	}

	/**
	 * Second line of defence after the API's own sanitiser: keeps a small
	 * tag allowlist, drops every attribute, and rebuilds links with an
	 * http(s) href only.
	 */
	public function sanitizeChangelogHtml($html) {
		$html = preg_replace('#<(script|style|iframe|object|embed|template)\b.*?</\1\s*>#is', '', $html);
		$html = strip_tags((string) $html, '<h2><h3><h4><p><br><hr><ul><ol><li><strong><b><em><i><u><code><pre><blockquote><a><table><thead><tbody><tr><th><td>');
		return preg_replace_callback('#<(/?)([a-z][a-z0-9]*)\b([^>]*)>#i', function ($m) {
			$tag = strtolower($m[2]);
			if ($m[1] === '/') {
				return '</' . $tag . '>';
			}
			if ($tag === 'a') {
				if (preg_match('#\bhref\s*=\s*(["\']?)(https?://[^"\'\s<>]+)\1#i', $m[3], $href)) {
					return '<a href="' . htmlspecialchars($href[2], ENT_QUOTES, 'UTF-8') . '" target="_blank" rel="noopener noreferrer">';
				}
				return '<a>';
			}
			return '<' . $tag . '>';
		}, $html);
	}

	/**
	 * Calls the ingest API with the uploader's own credentials. With $sink
	 * set, the response body streams into that file handle instead.
	 */
	protected function updateApiRequest($url, $method = 'GET', $body = null, $timeout = 5, $sink = null) {
		if (!function_exists('curl_init')) {
			throw new \RuntimeException('PHP curl extension is unavailable');
		}
		$s = $this->getSettings();
		if ($s['api_key'] === '') {
			throw new \RuntimeException('API key is not configured');
		}
		$headers = array(
			$s['auth_header'] . ': ' . trim($s['auth_scheme'] . ' ' . $s['api_key']),
			'Accept: application/json',
		);
		$options = array(
			CURLOPT_HTTPHEADER => $headers,
			CURLOPT_CONNECTTIMEOUT => min(5, $timeout),
			CURLOPT_TIMEOUT => $timeout,
			CURLOPT_SSL_VERIFYPEER => $s['verify_tls'] === '1',
			CURLOPT_SSL_VERIFYHOST => $s['verify_tls'] === '1' ? 2 : 0,
			// No redirects: X-API-Key style headers would follow them to
			// another host. The API streams release downloads itself.
			CURLOPT_FOLLOWLOCATION => false,
		);
		if ($method === 'POST') {
			$options[CURLOPT_POST] = true;
			$options[CURLOPT_POSTFIELDS] = json_encode($body);
			$options[CURLOPT_HTTPHEADER][] = 'Content-Type: application/json';
		}
		if ($sink !== null) {
			$options[CURLOPT_FILE] = $sink;
		} else {
			$options[CURLOPT_RETURNTRANSFER] = true;
		}
		$ch = curl_init($url);
		curl_setopt_array($ch, $options);
		$response = curl_exec($ch);
		$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$error = curl_error($ch);
		curl_close($ch);
		if ($response === false) {
			throw new \RuntimeException('Update server unreachable: ' . $error);
		}
		if ($status < 200 || $status >= 300) {
			throw new \RuntimeException("Update server returned HTTP {$status}");
		}
		if ($sink !== null) {
			return null;
		}
		$data = json_decode((string) $response, true);
		if (!is_array($data)) {
			throw new \RuntimeException('Update server returned an invalid response');
		}
		return $data;
	}

	protected function startUpdate($releaseId) {
		$capability = $this->getUpdateCapability();
		if (!$capability['auto']) {
			return array('status' => false, 'error' => 'unsupported', 'reasons' => $capability['reasons'], 'message' => 'Automatic update is not available on this server');
		}
		if (!\Engine\ModuleUpdate::isReleaseId($releaseId)) {
			return array('status' => false, 'error' => 'invalid', 'message' => 'Invalid release id');
		}
		if (!is_dir(self::UPDATES_DIR) && !@mkdir(self::UPDATES_DIR, 0750, true)) {
			return array('status' => false, 'error' => 'spool', 'message' => 'Cannot create ' . self::UPDATES_DIR);
		}
		$lock = @fopen(self::UPDATES_DIR . '/.lock', 'c');
		if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
			$active = $this->activeUpdateJob();
			return $active !== null
				? array('status' => true, 'job' => $active['job'], 'resumed' => true)
				: array('status' => false, 'error' => 'busy', 'message' => 'Another update request is being prepared');
		}
		@set_time_limit(0);
		ignore_user_abort(true);
		$jobDir = null;
		try {
			$active = $this->activeUpdateJob();
			if ($active !== null) {
				return array('status' => true, 'job' => $active['job'], 'resumed' => true);
			}
			$info = $this->fetchUpdateInfo(true);
			$release = $info['latest'];
			if (!$info['update_available'] || $release === null || $release['id'] !== $releaseId) {
				throw new \RuntimeException('This release is no longer the latest available update; reload the page');
			}
			$publicKey = $this->updatePublicKey();
			$job = bin2hex(random_bytes(16));
			$jobDir = self::UPDATES_DIR . '/' . $job;
			if (!@mkdir($jobDir, 0750)) {
				throw new \RuntimeException('Cannot create update job directory');
			}
			$zip = $jobDir . '/release.zip';
			$handle = @fopen($zip . '.part', 'wb');
			if ($handle === false) {
				throw new \RuntimeException('Cannot write the release download');
			}
			try {
				$this->updateApiRequest(\Engine\ModuleUpdate::downloadUrl($this->getSettings()['endpoint'], $release['id']), 'GET', null, 300, $handle);
			} finally {
				fclose($handle);
			}
			\Engine\ModuleUpdate::verifyArtifact($zip . '.part', $release, $publicKey);
			if (!@rename($zip . '.part', $zip)) {
				throw new \RuntimeException('Cannot finalize the release download');
			}
			$from = $this->getModuleVersion()['files'];
			$jobInfo = array(
				'job' => $job,
				'release_id' => $release['id'],
				'version' => $release['version'],
				'from_version' => $from,
				'sha256' => $release['sha256'],
				'signature' => $release['signature'],
				'size' => $release['size'],
				'host_uuid' => $this->hostUuid(),
				'created_at' => time(),
			);
			if (@file_put_contents($jobDir . '/job.json', json_encode($jobInfo, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)) === false) {
				throw new \RuntimeException('Cannot write job.json');
			}
			$this->setConfig('recuploader_update_job', $job);
			$this->reportUpdate($release['id'], $from, $release['version'], 'started', '');
			$this->launchUpdateHelper($job, $jobDir);
			$this->pruneUpdateJobs($job);
			return array('status' => true, 'job' => $job);
		} catch (\Throwable $exc) {
			if ($jobDir !== null) {
				$this->shell('rm -rf ' . escapeshellarg($jobDir) . ' 2>&1');
			}
			return array('status' => false, 'error' => 'prepare', 'message' => $this->safeError($exc->getMessage()));
		} finally {
			flock($lock, LOCK_UN);
			fclose($lock);
		}
	}

	/**
	 * Fire-and-forget: the helper re-execs itself under systemd-run so it
	 * survives web server restarts; setsid/nohup keep this request from
	 * waiting on it when systemd-run is unavailable. Launch errors land in
	 * launch.log, which getUpdateStatus() surfaces.
	 */
	protected function launchUpdateHelper($job, $jobDir) {
		$setsid = trim((string) @shell_exec('command -v setsid 2>/dev/null')) !== '' ? 'setsid ' : '';
		$command = $setsid . 'nohup sudo -n ' . escapeshellarg(self::UPDATE_HELPER) . ' ' . escapeshellarg($job)
			. ' > ' . escapeshellarg($jobDir . '/launch.log') . ' 2>&1 < /dev/null &';
		@exec($command);
	}

	protected function reportUpdate($releaseId, $from, $to, $status, $message) {
		try {
			$this->updateApiRequest(\Engine\ModuleUpdate::reportUrl($this->getSettings()['endpoint']), 'POST', array(
				'host_uuid' => $this->hostUuid(),
				'release_id' => $releaseId,
				'from_version' => $from,
				'to_version' => $to,
				'status' => $status,
				'message' => $message,
			), 5);
		} catch (\Throwable $exc) {
			error_log('recuploader: update report failed: ' . $this->safeError($exc->getMessage()));
		}
	}

	/** Keeps the current job plus the newest other one. */
	protected function pruneUpdateJobs($keep) {
		$jobs = array();
		foreach (glob(self::UPDATES_DIR . '/*', GLOB_ONLYDIR) ?: array() as $dir) {
			$name = basename($dir);
			if ($name !== $keep && \Engine\ModuleUpdate::isJobId($name)) {
				$jobs[$dir] = (int) @filemtime($dir);
			}
		}
		arsort($jobs);
		foreach (array_slice(array_keys($jobs), 1) as $dir) {
			$this->shell('rm -rf ' . escapeshellarg($dir) . ' 2>&1');
		}
	}

	/** The last started job while it is still running (or waiting for the helper to start). */
	protected function activeUpdateJob() {
		$job = (string) $this->getConfig('recuploader_update_job');
		if (!\Engine\ModuleUpdate::isJobId($job)) {
			return null;
		}
		$status = $this->getUpdateStatus($job);
		if (empty($status['status']) || !in_array($status['state'], array('queued', 'running'), true)) {
			return null;
		}
		if ((int) ($status['updated_at'] ?? 0) < time() - self::UPDATE_STALE_SECONDS) {
			return null;
		}
		return array('job' => $job, 'state' => $status['state'], 'to_version' => $status['to_version'] ?? '');
	}

	public function getUpdateStatus($job) {
		if (!\Engine\ModuleUpdate::isJobId($job)) {
			return array('status' => false, 'message' => 'Invalid job id');
		}
		$data = json_decode((string) @file_get_contents(self::UPDATE_STATUS_DIR . '/' . $job . '/status.json'), true);
		if (is_array($data) && isset($data['state'])) {
			$data['status'] = true;
			$data['job'] = $job;
			$data['log_tail'] = $this->safeError((string) ($data['log_tail'] ?? ''));
			return $data;
		}
		$jobDir = self::UPDATES_DIR . '/' . $job;
		$jobInfo = json_decode((string) @file_get_contents($jobDir . '/job.json'), true);
		if (!is_array($jobInfo)) {
			return array('status' => false, 'message' => 'Unknown update job');
		}
		$launchLog = trim((string) @file_get_contents($jobDir . '/launch.log'));
		$age = time() - (int) ($jobInfo['created_at'] ?? 0);
		$failed = ($launchLog !== '' && $age > 5) || $age > 120;
		return array(
			'status' => true,
			'job' => $job,
			'state' => $failed ? 'failed' : 'queued',
			'step' => $failed ? 'verify' : '',
			'steps' => array(),
			'percent' => 0,
			'from_version' => (string) ($jobInfo['from_version'] ?? ''),
			'to_version' => (string) ($jobInfo['version'] ?? ''),
			'message' => $failed ? 'The update helper did not start (check the sudoers entry for ' . self::UPDATE_HELPER . ')' : '',
			'log_tail' => $this->safeError($launchLog),
			'updated_at' => (int) ($jobInfo['created_at'] ?? 0),
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

	/**
	 * Server-side validation of the manual settings form, mirroring the
	 * limits ConfigProfile enforces for imports. Values are written raw into
	 * config.ini, so a newline or NUL would inject extra keys, and a
	 * non-numeric timeout silently became 0 (= no timeout).
	 * Returns an error message, or null when the submitted values are valid.
	 */
	public function validateManualSettings(array $request) {
		$ints = array(
			'timeout_seconds' => array(1, 3600),
			'immediate_retries' => array(0, 10),
			'min_file_age_seconds' => array(0, 86400),
			'max_retries' => array(0, 10000),
			'retry_base_seconds' => array(0, 86400),
			'retry_max_seconds' => array(0, 604800),
			'credit_retry_seconds' => array(60, 86400),
			'sweep_interval_seconds' => array(10, 86400),
			'stale_processing_seconds' => array(60, 86400),
			'retention_days' => array(0, 3650),
			'missed_calls_poll_interval_seconds' => array(10, 3600),
			'voicemail_sweep_interval_seconds' => array(10, 86400),
		);
		foreach ($this->defaults() as $key => $unused) {
			if (!isset($request[$key])) {
				continue;
			}
			$value = trim((string) $request[$key]);
			if (preg_match('/[\r\n\0]/', $value)) {
				return "Field {$key} must not contain line breaks.";
			}
			if (isset($ints[$key])) {
				if (!preg_match('/^\d+$/', $value) || (int) $value < $ints[$key][0] || (int) $value > $ints[$key][1]) {
					return "Field {$key} must be a whole number between {$ints[$key][0]} and {$ints[$key][1]}.";
				}
			}
		}
		if (isset($request['endpoint'])) {
			$endpoint = trim((string) $request['endpoint']);
			$parts = parse_url($endpoint);
			if ($parts === false || !isset($parts['scheme'], $parts['host']) || strtolower($parts['scheme']) !== 'https') {
				return 'The upload endpoint must be an https:// URL.';
			}
		}
		$enums = array(
			'on_success' => array('keep', 'move', 'delete'),
			'log_level' => array('DEBUG', 'INFO', 'WARNING', 'ERROR'),
			'upload_format' => array('wav', 'gzip', 'zip'),
		);
		foreach ($enums as $key => $allowed) {
			if (isset($request[$key]) && !in_array(trim((string) $request[$key]), $allowed, true)) {
				return "Field {$key} must be one of: " . implode(', ', $allowed) . '.';
			}
		}
		if (isset($request['archive_format']) && !preg_match('/^[a-z0-9]{2,8}$/', trim((string) $request['archive_format']))) {
			return 'Field archive_format must be a short file extension such as gsm, wav or mp3.';
		}
		foreach (array('filename_pattern', 'exclude_patterns') as $key) {
			if (isset($request[$key])) {
				$pattern = trim((string) $request[$key]);
				if ($pattern !== '' && @preg_match('#' . str_replace('#', '\\#', $pattern) . '#', '') === false) {
					return "Field {$key} is not a valid regular expression.";
				}
			}
		}
		foreach (array('watch_dir', 'move_dir', 'voicemail_spool_dir') as $key) {
			if (isset($request[$key])) {
				$path = trim((string) $request[$key]);
				if ($path === '' || $path[0] !== '/' || strpos($path, '/../') !== false || substr($path, -3) === '/..') {
					return "Field {$key} must be an absolute path without '..'.";
				}
			}
		}
		return null;
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
			self::UPDATES_DIR,
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
		// The update helper is launched from the GUI with no TTY, which
		// older SNG7 sudoers configs reject via "Defaults requiretty".
		$line = "Defaults:asterisk !requiretty\n"
			. "asterisk ALL=(root) NOPASSWD: /bin/systemctl start " . self::SERVICE_NAME . ", "
			. "/bin/systemctl stop " . self::SERVICE_NAME . ", "
			. "/bin/systemctl restart " . self::SERVICE_NAME . ", "
			. "/bin/systemctl enable " . self::SERVICE_NAME . ", "
			. "/bin/systemctl disable " . self::SERVICE_NAME . ", "
			. "/bin/systemctl status " . self::SERVICE_NAME . ", "
			. self::UPDATE_HELPER . "\n";
		if (@file_put_contents(self::SUDOERS_FILE, $line) === false) {
			error_log('recuploader: failed to write ' . self::SUDOERS_FILE . ' - check ownership/permissions');
		}
		@chmod(self::SUDOERS_FILE, 0440);
	}

	/**
	 * Installs the root-owned self-update helper and the release signing
	 * key. Needs root (fwconsole/install.sh); under the Module Admin GUI
	 * these silently fail and the page falls back to manual download.
	 */
	protected function installUpdateHelper() {
		$helper = __DIR__ . '/bin/sedasanj-recuploader-update.sh';
		$pubkey = __DIR__ . '/assets/release-signing.pub';
		if (!is_file($helper) || !is_file($pubkey)) {
			error_log('recuploader: update helper or signing key missing from the module package - auto-update disabled');
			return;
		}
		$this->shell('install -d -o root -g root -m 0755 ' . escapeshellarg(self::UPDATE_ROOT_DIR)
			. ' ' . escapeshellarg(dirname(self::UPDATE_STATUS_DIR)) . ' ' . escapeshellarg(self::UPDATE_STATUS_DIR) . ' 2>&1');
		$this->shell('install -o root -g root -m 0755 ' . escapeshellarg($helper) . ' ' . escapeshellarg(self::UPDATE_HELPER) . ' 2>&1');
		$this->shell('install -o root -g root -m 0644 ' . escapeshellarg($pubkey) . ' ' . escapeshellarg(self::UPDATE_ROOT_DIR . '/release-signing.pub') . ' 2>&1');
		$this->shell('install -o asterisk -g asterisk -m 0644 ' . escapeshellarg($pubkey) . ' ' . escapeshellarg(self::UPDATE_PUBKEY) . ' 2>&1');
		if (!function_exists('sodium_crypto_sign_verify_detached')) {
			error_log('recuploader: PHP sodium extension is missing - automatic updates are disabled until php-sodium is installed');
		}
	}

	protected function serviceControl($action) {
		// Try direct first (works when running as root, e.g. via
		// `fwconsole ma installlocal`), fall back to sudo (works when the
		// GUI process is the asterisk user and installSudoers() ran ok).
		$this->shell('systemctl ' . escapeshellarg($action) . ' ' . self::SERVICE_NAME . ' 2>&1');
		$this->shell('sudo -n systemctl ' . escapeshellarg($action) . ' ' . self::SERVICE_NAME . ' 2>&1');
	}

	public function getServiceStatus() {
		return $this->serviceIsActive() ? 'running' : 'stopped';
	}

	/**
	 * 'files' is the version of the code actually deployed (module.xml next
	 * to this class); 'installed' is what FreePBX has registered in its
	 * modules table. They differ only when files were copied in without a
	 * `fwconsole ma install`, which the page flags.
	 */
	public function getModuleVersion() {
		$xml = @simplexml_load_file(__DIR__ . '/module.xml');
		$files = ($xml !== false && isset($xml->version)) ? trim((string) $xml->version) : '';
		$installed = '';
		try {
			$stmt = $this->FreePBX->Database->prepare('SELECT version FROM modules WHERE modulename = ?');
			$stmt->execute(array('recuploader'));
			$installed = trim((string) $stmt->fetchColumn());
		} catch (\Throwable $e) {
			$installed = '';
		}
		return array('files' => $files !== '' ? $files : $installed, 'installed' => $installed);
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
		// Single source of truth: the shipped dialplan/globals-custom-mixmon.conf
		// (it uses the SS=$ indirection and FILTER() on every caller-controlled
		// value). A previously installed block that differs - e.g. the unfiltered
		// MIXMON_POST of releases before 1.3.9 - is replaced, not kept.
		$source = __DIR__ . '/dialplan/globals-custom-mixmon.conf';
		$shipped = is_file($source) ? trim((string) file_get_contents($source)) : '';
		if ($shipped === '' || strpos($shipped, self::MIXMON_BEGIN) !== 0 || strpos($shipped, self::MIXMON_END) === false) {
			throw new \RuntimeException('The bundled MixMonitor globals block is missing or malformed.');
		}
		$existing = file_exists(self::GLOBALS_FILE) ? file_get_contents(self::GLOBALS_FILE) : '';
		$pattern = '/\n?' . preg_quote(self::MIXMON_BEGIN, '/') . '.*?' . preg_quote(self::MIXMON_END, '/') . '\n?/s';
		if (preg_match($pattern, $existing, $match) === 1 && trim($match[0]) === $shipped) {
			return; // already current
		}
		$stripped = preg_replace($pattern, "\n", $existing);
		if (@file_put_contents(self::GLOBALS_FILE, rtrim($stripped) . "\n\n" . $shipped . "\n") === false) {
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
