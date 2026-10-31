<?php
/**
 * DependencyCheck.php - turns an inventory of the host (FreePBX version, PHP, extensions, FreePBX
 * modules, tools, patch and activation state) into the rows of the module page's "Health &
 * Dependencies" tab. Pure logic with no side effects, so it is unit tested; Recuploader
 * collects the inventory from the live system.
 *
 * A row is: id, group, label, required (bool), status (ok|warn|fail), detail, code (SS-...), action,
 * install_module (FreePBX module rawname that can be installed with one click, or null).
 */

namespace Engine;

class DependencyCheck
{
    const MIN_PHP = '7.4.0';
    /** FreePBX modules without which the recording path cannot work => minimum version. */
    const REQUIRED_MODULES = ['core' => '15.0', 'callrecording' => '15.0', 'cdr' => '15.0'];
    /** FreePBX modules that only enable an optional feature. */
    const OPTIONAL_MODULES = ['voicemail' => 'voicemail upload'];
    /** Modules the one-click installer is allowed to fetch. */
    const INSTALLABLE_MODULES = ['core', 'callrecording', 'cdr', 'voicemail'];

    const WEB_EXTENSIONS = ['curl', 'zlib', 'json', 'simplexml'];
    const CLI_EXTENSIONS_REQUIRED = ['curl', 'zlib', 'json', 'pdo_sqlite', 'ctype'];
    const CLI_EXTENSIONS_OPTIONAL = ['pcntl' => 'clean service stop', 'sodium' => 'automatic updates'];

    /**
     * @param array<string,mixed> $env see the keys read below; missing keys are treated as "unknown"
     * @return array{rows:array<int,array<string,mixed>>,blocking:int,warnings:int,ok:bool}
     */
    public static function evaluate(array $env): array
    {
        $rows = [];
        $add = function (string $id, string $group, string $label, bool $required, string $status, string $detail, string $code = '', string $action = '', ?string $installModule = null) use (&$rows) {
            $rows[] = ['id' => $id, 'group' => $group, 'label' => $label, 'required' => $required, 'status' => $status,
                'detail' => $detail, 'code' => $code, 'action' => $action, 'install_module' => $installModule];
        };

        // FreePBX
        $freepbx = (string) ($env['freepbx_version'] ?? '');
        if (preg_match('/^(\d+)\./', $freepbx, $m) && in_array((int) $m[1], [15, 16, 17], true)) {
            $add('freepbx', 'System', 'FreePBX version', true, 'ok', $freepbx);
        } else {
            $add('freepbx', 'System', 'FreePBX version', true, 'fail', $freepbx !== '' ? $freepbx : 'unknown', 'SS-SYS-1003', 'Supported: FreePBX 15, 16 and 17.');
        }

        // PHP (web = the GUI and BMO class; CLI = the engine, hook and uploader)
        $web = (string) ($env['php_web'] ?? '');
        $add('php_web', 'System', 'PHP (web)', true, $web !== '' && version_compare($web, self::MIN_PHP, '>=') ? 'ok' : 'fail', $web,
            'SS-SYS-1001', 'The module needs PHP ' . self::MIN_PHP . ' or newer in the FreePBX web PHP.');
        $cli = $env['php_cli'] ?? null;
        if ($cli === null || $cli === '') {
            $add('php_cli', 'System', 'PHP (command line)', true, 'fail', 'php not found on PATH', 'SS-SYS-1001', 'Install php-cli so the engine can run.');
        } else {
            $add('php_cli', 'System', 'PHP (command line)', true, version_compare((string) $cli, self::MIN_PHP, '>=') ? 'ok' : 'fail', (string) $cli,
                'SS-SYS-1001', 'The engine needs the CLI PHP ' . self::MIN_PHP . ' or newer (on FreePBX 15 install PHP 7.4 next to the system PHP and put it first on PATH).');
        }

        // PHP extensions
        $webExt = (array) ($env['web_extensions'] ?? []);
        foreach (self::WEB_EXTENSIONS as $ext) {
            $loaded = !empty($webExt[$ext]);
            $add('web_ext_' . $ext, 'PHP extensions', "web: {$ext}", true, $loaded ? 'ok' : 'fail', $loaded ? 'loaded' : 'missing',
                'SS-DEP-1002', "Install the PHP {$ext} extension and restart Apache/PHP-FPM.");
        }
        $cliExt = $env['cli_extensions'] ?? null;
        foreach (self::CLI_EXTENSIONS_REQUIRED as $ext) {
            if ($cliExt === null) {
                $add('cli_ext_' . $ext, 'PHP extensions', "cli: {$ext}", true, 'warn', 'could not be checked');
                continue;
            }
            $loaded = !empty($cliExt[$ext]);
            $add('cli_ext_' . $ext, 'PHP extensions', "cli: {$ext}", true, $loaded ? 'ok' : 'fail', $loaded ? 'loaded' : 'missing',
                'SS-DEP-1002', "Install the PHP {$ext} extension for the command-line PHP.");
        }
        foreach (self::CLI_EXTENSIONS_OPTIONAL as $ext => $purpose) {
            if ($cliExt === null) {
                continue;
            }
            $loaded = !empty($cliExt[$ext]);
            $add('cli_ext_' . $ext, 'PHP extensions', "cli: {$ext}", false, $loaded ? 'ok' : 'warn', $loaded ? 'loaded' : "missing ({$purpose} unavailable)",
                'SS-DEP-1003', "Install the PHP {$ext} extension to enable {$purpose}.");
        }

        // FreePBX modules
        $modules = (array) ($env['modules'] ?? []);
        foreach (self::REQUIRED_MODULES as $name => $minimum) {
            $info = $modules[$name] ?? ['status' => 'missing', 'version' => ''];
            $status = (string) ($info['status'] ?? 'missing');
            $version = (string) ($info['version'] ?? '');
            if ($status === 'enabled' && ($version === '' || version_compare($version, $minimum, '>='))) {
                $add('module_' . $name, 'FreePBX modules', $name, true, 'ok', $version !== '' ? "v{$version}" : 'enabled');
            } else {
                $detail = $status === 'enabled' ? "v{$version} is older than {$minimum}" : $status;
                $add('module_' . $name, 'FreePBX modules', $name, true, 'fail', $detail, 'SS-DEP-1001',
                    $status === 'missing' ? "Install the {$name} module." : "Enable or upgrade the {$name} module.", in_array($name, self::INSTALLABLE_MODULES, true) ? $name : null);
            }
        }
        foreach (self::OPTIONAL_MODULES as $name => $purpose) {
            $info = $modules[$name] ?? ['status' => 'missing', 'version' => ''];
            $ok = ($info['status'] ?? 'missing') === 'enabled';
            $add('module_' . $name, 'FreePBX modules', $name, false, $ok ? 'ok' : 'warn',
                $ok ? 'v' . ($info['version'] ?? '') : (string) ($info['status'] ?? 'missing') . " ({$purpose} unavailable)",
                'SS-DEP-1003', "Install the {$name} module if you want {$purpose}.", $ok ? null : $name);
        }

        // Tools
        $bins = (array) ($env['binaries'] ?? []);
        $tool = function (string $key, string $label, bool $required, string $why) use ($bins, $add) {
            $path = $bins[$key] ?? null;
            $add('bin_' . $key, 'Tools', $label, $required, $path ? 'ok' : ($required ? 'fail' : 'warn'),
                $path ? (string) $path : "not found ({$why})", $required ? 'SS-DEP-1002' : 'SS-DEP-1003', "Install {$label}: {$why}");
        };
        $tool('unzip', 'unzip', true, 'Module Admin and the update helper unpack ZIP releases with it');
        $tool('sudo', 'sudo', false, 'lets the GUI start/stop the service and run updates');
        $tool('systemctl', 'systemctl', true, 'the background service is a systemd unit');
        $tool('flock', 'flock', false, 'serialises updates');
        $tool('ffmpeg', 'ffmpeg', false, 'needed only for non-GSM archive copies and voicemail conversion (a bundled copy is used when present)');
        $tool('gsm', 'GSM encoder', false, 'needed only for the GSM local archive copy (a bundled encoder is used when present)');

        // Asterisk
        $asterisk = $env['asterisk'] ?? null;
        $add('asterisk', 'System', 'Asterisk', true, $asterisk ? 'ok' : 'warn', $asterisk ? (string) $asterisk : 'version could not be read');

        // Recording hook health
        $patch = (string) ($env['patch_state'] ?? 'unknown');
        if ($patch === 'ok') {
            $add('patch', 'Recording hook', 'FreePBX callrecording patch', true, 'ok', 'applied');
        } elseif ($patch === 'drift') {
            $add('patch', 'Recording hook', 'FreePBX callrecording patch', true, 'fail', 'missing - callrecording was updated or the module is not activated',
                'SS-HOOK-1005', 'Run the activation command as root; until then recordings are not passing through the hook.');
        } else {
            $add('patch', 'Recording hook', 'FreePBX callrecording patch', true, 'warn', 'could not be verified');
        }
        $globals = (string) ($env['globals_state'] ?? 'unknown');
        $add('globals', 'Recording hook', 'MixMonitor globals block', true, $globals === 'ok' ? 'ok' : (in_array($globals, ['outdated', 'missing'], true) ? 'fail' : 'warn'),
            $globals === 'ok' ? 'current' : ($globals === 'outdated' ? 'present but not the shipped version' : ($globals === 'missing' ? 'not installed' : $globals)),
            'SS-HOOK-1005', 'Run the activation command as root to rewrite the globals block.');

        // Activation and service
        $activation = (string) ($env['activation'] ?? 'pending');
        $add('activation', 'Service', 'Root activation', true, $activation === 'ok' ? 'ok' : 'fail', $activation === 'ok' ? 'done' : $activation,
            'SS-SYS-1004', 'Run the activation command shown at the top of the page as root.');
        $service = $env['service_active'] ?? null;
        $add('service', 'Service', 'Background service', true, $service === true ? 'ok' : ($service === false ? 'fail' : 'warn'),
            $service === true ? 'running' : ($service === false ? 'not running' : 'unknown'), 'SS-SVC-1001', 'Check the service log; start it from the page or with systemctl.');

        // Storage
        foreach ((array) ($env['writable'] ?? []) as $path => $writable) {
            $add('dir_' . md5((string) $path), 'Storage', (string) $path, true, $writable ? 'ok' : 'fail', $writable ? 'writable' : 'not writable by asterisk',
                'SS-SYS-1007', 'chown -R asterisk:asterisk ' . $path);
        }
        $free = $env['disk_free_mb'] ?? null;
        if ($free !== null) {
            $status = $free < 500 ? 'fail' : ($free < 2048 ? 'warn' : 'ok');
            $add('disk', 'Storage', 'Free disk space (spool)', true, $status, (int) $free . ' MB', 'SS-SYS-1005', 'Free space on the volume holding /var/spool and /var/lib.');
        }

        $blocking = 0;
        $warnings = 0;
        foreach ($rows as $row) {
            if ($row['status'] === 'fail' && $row['required']) {
                $blocking++;
            } elseif ($row['status'] !== 'ok') {
                $warnings++;
            }
        }
        return ['rows' => $rows, 'blocking' => $blocking, 'warnings' => $warnings, 'ok' => $blocking === 0];
    }
}
