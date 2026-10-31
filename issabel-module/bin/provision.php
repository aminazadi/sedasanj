#!/usr/bin/env php
<?php
if (PHP_SAPI !== 'cli' || !function_exists('posix_geteuid') || posix_geteuid() !== 0) { exit(1); }
require __DIR__ . '/../engine/autoload.php';
use Engine\IssabelSettings;

function sj_exec(array $args): void {
    passthru(implode(' ', array_map('escapeshellarg', $args)), $exit);
    if ($exit !== 0) { throw new RuntimeException('SS-SYS-1012: Installation command failed; restore the verified backup.'); }
}
function sj_copy(string $from, string $to): void {
    if (is_link($from)) { throw new RuntimeException('SS-SYS-1012: Build a self-contained release before installation.'); }
    if (is_dir($from)) {
        if (!is_dir($to)) { mkdir($to, 0750, true); }
        foreach (new DirectoryIterator($from) as $item) {
            if (!$item->isDot()) { sj_copy($item->getPathname(), $to . '/' . $item->getFilename()); }
        }
    } elseif (!copy($from, $to)) { throw new RuntimeException('SS-SYS-1007'); }
    chmod($to, fileperms($from) & 0777); chown($to, fileowner($from)); chgrp($to, filegroup($from));
}
function sj_binary(string $path): string {
    $real = realpath($path);
    if (!$real || !is_executable($real) || !is_file($real)) { throw new RuntimeException('SS-SYS-1011'); }
    $check = $real;
    while ($check !== '/') {
        if (fileowner($check) !== 0 || (fileperms($check) & 0022)) { throw new RuntimeException('SS-SYS-1011: PHP and its parents must be root-owned and not group/world writable.'); }
        $check = dirname($check);
    }
    return $real;
}
function sj_backup(array $paths): string {
    $root = '/var/backups/sedasanj-recuploader';
    if (!is_dir($root)) { mkdir($root, 0700, true); }
    $dir = $root . '/issabel-' . gmdate('Ymd-His') . '-' . bin2hex(random_bytes(4));
    mkdir($dir, 0700);
    $manifest = [];
    foreach ($paths as $path) {
        $manifest[$path] = file_exists($path);
        if (file_exists($path)) { sj_copy($path, $dir . '/files/' . ltrim($path, '/')); }
    }
    IssabelSettings::atomic($dir . '/manifest.json', json_encode($manifest), 0600);
    IssabelSettings::atomic($dir . '/service.json', json_encode([
        'enabled' => trim((string) shell_exec('systemctl is-enabled asterisk-recording-uploader.service 2>/dev/null')) === 'enabled',
        'running' => trim((string) shell_exec('systemctl is-active asterisk-recording-uploader.service 2>/dev/null')) === 'active',
    ]), 0600);
    $hashes = [];
    foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS)) as $file) {
        if ($file->isFile()) { $hashes[substr($file->getPathname(), strlen($dir) + 1)] = hash_file('sha256', $file->getPathname()); }
    }
    IssabelSettings::atomic($dir . '/checksums.json', json_encode($hashes), 0600);
    sj_verify_backup($dir);
    return $dir;
}
function sj_verify_backup(string $dir): void {
    $hashes = json_decode((string) @file_get_contents($dir . '/checksums.json'), true);
    if (!is_array($hashes) || !isset($hashes['manifest.json'], $hashes['service.json'])) { throw new RuntimeException('SS-SYS-1012: Backup manifest or checksums are invalid.'); }
    foreach ($hashes as $path => $hash) {
        if (!is_string($path) || $path === '' || $path[0] === '/' || in_array('..', explode('/', $path), true)
            || !is_string($hash) || !is_file($dir . '/' . $path) || is_link($dir . '/' . $path)
            || !hash_equals($hash, hash_file('sha256', $dir . '/' . $path))) { throw new RuntimeException('SS-SYS-1012: Backup checksum mismatch.'); }
    }
}
function sj_remove(string $path): void {
    if (!file_exists($path) && !is_link($path)) { return; }
    if (is_link($path) || !is_dir($path)) { unlink($path); return; }
    foreach (new DirectoryIterator($path) as $item) {
        if (!$item->isDot()) { sj_remove($item->getPathname()); }
    }
    rmdir($path);
}
function sj_restore(string $dir): void {
    sj_verify_backup($dir);
    @shell_exec('systemctl stop asterisk-recording-uploader.service 2>/dev/null');
    @shell_exec('systemctl disable asterisk-recording-uploader.service 2>/dev/null');
    foreach (json_decode((string) file_get_contents($dir . '/manifest.json'), true) as $path => $exists) {
        sj_remove($path);
        if ($exists) { sj_copy($dir . '/files/' . ltrim($path, '/'), $path); }
    }
    sj_exec(['systemctl', 'daemon-reload']);
    $service = json_decode((string) file_get_contents($dir . '/service.json'), true);
    if (!empty($service['enabled'])) { sj_exec(['systemctl', 'enable', 'asterisk-recording-uploader.service']); }
    if (!empty($service['running'])) { sj_exec(['systemctl', 'start', 'asterisk-recording-uploader.service']); }
}
try {
    $source = $argv[1] ?? '';
    if ($source === '--restore') {
        $restore = realpath($argv[2] ?? '');
        if (!$restore || strpos($restore, '/var/backups/sedasanj-recuploader/issabel-') !== 0 || fileowner($restore) !== 0 || (fileperms($restore) & 0077)) { throw new RuntimeException('SS-SYS-1012'); }
        sj_verify_backup($restore);
        $manifest = json_decode((string) file_get_contents($restore . '/manifest.json'), true);
        foreach (array_keys($manifest) as $path) {
            if (!in_array($path, ['/etc/sedasanj-recuploader-update', '/usr/local/lib/sedasanj-issabel', '/usr/local/bin/asterisk-recording-uploader', '/etc/asterisk-recording-uploader', '/etc/systemd/system/asterisk-recording-uploader.service', '/etc/sudoers.d/sedasanj-issabel', '/usr/local/sbin/sedasanj-recording-hook', '/usr/local/sbin/sedasanj-issabel-control'], true) && !preg_match('~^/[A-Za-z0-9_/-]+/admin/modules/recuploader$~', $path)) { throw new RuntimeException('SS-SYS-1012'); }
        }
        sj_backup(array_keys($manifest));
        @shell_exec('systemctl stop asterisk-recording-uploader.service 2>/dev/null');
        sj_restore($restore);
        $restoredHost = json_decode((string) @file_get_contents('/etc/sedasanj-recuploader-update/host.json'), true);
        if (is_array($restoredHost)) {
            sj_exec(['/usr/bin/php', $restoredHost['ampbin'] . '/module_admin', 'install', 'recuploader']);
            sj_exec(['/usr/bin/php', $restoredHost['ampbin'] . '/module_admin', 'reload']);
            sj_exec(['systemctl', 'restart', 'asterisk-recording-uploader.service']);
        }
        echo "Verified backup restored. Place a test call before returning to production.\n"; exit;
    }
    $uninstall = $source === '--uninstall';
    $php = sj_binary($uninstall ? PHP_BINARY : ($argv[2] ?? PHP_BINARY));
    if (PHP_VERSION_ID < 70400) { throw new RuntimeException('SS-SYS-1011: Install a separate PHP CLI 7.4+ and pass its path.'); }
    foreach (['curl', 'json', 'zlib', 'pdo_mysql', 'pdo_sqlite', 'simplexml', 'ctype'] as $extension) {
        if (!extension_loaded($extension)) { throw new RuntimeException('SS-DEP-1002: Install CLI extension ' . $extension . ' and run activation again.'); }
    }
    $inventory = $uninstall ? json_decode((string) file_get_contents('/etc/sedasanj-recuploader-update/host.json'), true) : json_decode(stream_get_contents(STDIN, 1048576), true);
    if (!is_array($inventory) || !in_array($inventory['issabel_version'] ?? '', ['4', '5'], true)
        || !preg_match('/^2\.(11|12)\./', $inventory['framework_version'] ?? '')) { throw new RuntimeException('SS-SYS-1010: Unsupported Issabel profile; check the compatibility guide.'); }
    foreach (['webroot', 'ampbin', 'monitor_dir'] as $key) {
        if (!preg_match('~^/[A-Za-z0-9_./-]+$~', $inventory[$key] ?? '') || strpos($inventory[$key], '..') !== false) { throw new RuntimeException('SS-SYS-1010'); }
    }
    if (!$uninstall) {
        exec('asterisk -rx ' . escapeshellarg('core show version') . ' 2>/dev/null', $asteriskOutput, $asteriskExit);
        if ($asteriskExit !== 0 || !preg_match('/Asterisk\s+(\d+)/', implode(' ', $asteriskOutput), $asteriskMatch)
            || !in_array((int) $asteriskMatch[1], $inventory['issabel_version'] === '4' ? [11, 13, 16] : [16, 18], true)) {
            throw new RuntimeException('SS-SYS-1010: Check the running Asterisk version against the Issabel compatibility matrix.');
        }
        $inventory['asterisk_version'] = implode(' ', $asteriskOutput);
    }
    if (!$uninstall && (($inventory['recording_format'] ?? '') !== 'wav' || trim($inventory['post_hook'] ?? '') !== '')) { throw new RuntimeException('SS-HOOK-1010: Set WAV recordings and resolve the existing post-record command before activation.'); }
    $module = $inventory['webroot'] . '/admin/modules/recuploader';
    $control = '/etc/sedasanj-recuploader-update';
    $library = '/usr/local/lib/sedasanj-issabel';
    $engine = '/usr/local/bin/asterisk-recording-uploader';
    $config = '/etc/asterisk-recording-uploader';
    if (!$uninstall && is_file($module . '/module.xml') && (string) simplexml_load_file($module . '/module.xml')->product !== 'issabel-recuploader') { throw new RuntimeException('SS-SYS-1010: Another PBX product already owns recuploader; use its matching package.'); }
    $paths = [$module, $control, $library, $engine, $config, '/etc/systemd/system/asterisk-recording-uploader.service', '/etc/sudoers.d/sedasanj-issabel', '/usr/local/sbin/sedasanj-recording-hook', '/usr/local/sbin/sedasanj-issabel-control'];
    if (!$uninstall) {
        if (empty($inventory['legacy_ready'])) { throw new RuntimeException('SS-SYS-1011: Enable JSON, OpenSSL and proc_open in the legacy PHP runtime.'); }
        foreach (['lsof', 'sudo', 'visudo', 'systemctl', 'systemd-run'] as $tool) {
            if (trim((string) shell_exec('command -v ' . escapeshellarg($tool) . ' 2>/dev/null')) === '') { throw new RuntimeException('SS-DEP-1002: Install ' . $tool . ' before activation.'); }
        }
    }
    $backup = sj_backup($paths);
    $wasRunning = trim((string) shell_exec('systemctl is-active asterisk-recording-uploader.service 2>/dev/null')) === 'active';
    try {
        if ($uninstall) {
            sj_exec(['systemctl', 'stop', 'asterisk-recording-uploader.service']);
            sj_exec(['systemctl', 'disable', 'asterisk-recording-uploader.service']);
            @unlink($control . '/issabel-active');
            sj_exec(['/usr/bin/php', $inventory['ampbin'] . '/module_admin', 'uninstall', 'recuploader']);
            sj_exec(['/usr/bin/php', $inventory['ampbin'] . '/module_admin', 'reload']);
            foreach (array_slice($paths, 5) as $path) { sj_remove($path); }
            sj_exec(['systemctl', 'daemon-reload']);
            echo "Removed service and integration; configuration, queue and backups retained.\n"; exit;
        }
        if (disk_free_space('/var') < 1073741824) { throw new RuntimeException('SS-SYS-1005: Free at least 1 GiB before activation.'); }
        if (!is_readable($source . '/engine/autoload.php')) { throw new RuntimeException('SS-SYS-1010'); }
        // Check CDR connectivity before changing the running installation.
        $adapter = new Engine\Host\Issabel($inventory); $adapter->cdr();
        foreach ([$config, $control, $library, '/var/lib/asterisk-recording-uploader', '/var/log/asterisk-recording-uploader', '/var/spool/asterisk-recording-uploader'] as $dir) {
            if (!is_dir($dir)) { mkdir($dir, 0750, true); }
        }
        chmod($control, 0755); chown($control, 0); chgrp($control, 0);
        if (realpath($source) !== realpath($module)) {
            $stage = $module . '.new-' . getmypid(); sj_copy($source, $stage);
            if (file_exists($module)) { sj_remove($module); }
            rename($stage, $module);
        }
        // Store a root-owned copy for privileged operations. Never run update validation from a web-writable tree.
        $libraryStage = $library . '.new-' . getmypid(); sj_copy($module, $libraryStage);
        sj_remove($library); rename($libraryStage, $library); sj_exec(['chown', '-R', 'root:root', $library]);
        sj_remove($engine); sj_copy($module . '/engine', $engine);
        $previousHost = json_decode((string) @file_get_contents($control . '/host.json'), true);
        $inventory['activated_at'] = $previousHost['activated_at'] ?? time();
        $inventory['php_cli'] = $php; $inventory['system_php'] = '/usr/bin/php';
        $inventory['module_dir'] = $module; $inventory['version'] = (string) simplexml_load_file($module . '/module.xml')->version;
        IssabelSettings::atomic($config . '/host.json', json_encode($inventory));
        sj_exec(['chown', 'root:asterisk', $config . '/host.json']);
        if (!is_file($config . '/config.ini')) { IssabelSettings::write(Engine\IssabelSettings::defaults(), $config . '/config.ini'); }
        IssabelSettings::atomic($control . '/host.json', json_encode(array_diff_key($inventory, ['cdr' => true, 'extensions' => true])), 0644);
        IssabelSettings::atomic($control . '/php-path', $php . "\n", 0644);
        $key = $module . '/assets/release-signing.pub';
        if (!is_file($control . '/release-signing.pub')) { copy($key, $control . '/release-signing.pub'); chmod($control . '/release-signing.pub', 0644); }
        $unit = "[Unit]\nDescription=Seda Sanj Issabel recording uploader\nAfter=network-online.target asterisk.service\nWants=network-online.target\n[Service]\nType=simple\nUser=asterisk\nGroup=asterisk\nUMask=0027\nEnvironment=ARU_CONFIG=$config/config.ini\nExecStart=$php $engine/bin/service.php\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=true\nProtectSystem=full\nProtectHome=true\n[Install]\nWantedBy=multi-user.target\n";
        IssabelSettings::atomic('/etc/systemd/system/asterisk-recording-uploader.service', $unit, 0644);
        IssabelSettings::atomic('/usr/local/sbin/sedasanj-recording-hook', "#!/bin/bash\nexec " . escapeshellarg($php) . ' ' . escapeshellarg($engine . '/bin/issabel-record.php') . ' "$@"' . "\n", 0755);
        $helper = "#!/bin/bash\nset -euo pipefail\nexport PATH=/usr/sbin:/usr/bin:/sbin:/bin\ncase \"\${1:-}\" in\nrestart|start|stop) [ \"\$#\" -eq 1 ]; exec systemctl \"\$1\" asterisk-recording-uploader.service ;;\nupdate) [ \"\$#\" -eq 2 ]; [[ \"\$2\" =~ ^[a-f0-9]{32}\$ ]]; exec systemd-run --quiet --unit=sedasanj-issabel-update-\"\$2\" " . escapeshellarg($php) . " $library/bin/update.php \"\$2\" ;;\n*) exit 2 ;;\nesac\n";
        IssabelSettings::atomic('/usr/local/sbin/sedasanj-issabel-control', $helper, 0755);
        IssabelSettings::atomic('/etc/sudoers.d/sedasanj-issabel', "Defaults:asterisk !requiretty\nasterisk ALL=(root) NOPASSWD: /usr/local/sbin/sedasanj-issabel-control\n", 0440);
        sj_exec(['visudo', '-cf', '/etc/sudoers.d/sedasanj-issabel']);
        sj_exec(['chown', '-R', 'asterisk:asterisk', $module, $engine, '/var/lib/asterisk-recording-uploader', '/var/log/asterisk-recording-uploader', '/var/spool/asterisk-recording-uploader']);
        sj_exec(['chown', 'asterisk:asterisk', $config . '/config.ini']);
        sj_exec(['chown', 'root:asterisk', $config]); chmod($config, 0770);
        sj_exec(['/usr/bin/php', $inventory['ampbin'] . '/module_admin', 'install', 'recuploader']);
        IssabelSettings::atomic($control . '/issabel-active', "1\n", 0644);
        @unlink('/var/lib/asterisk-recording-uploader/issabel-hook-error');
        sj_exec(['/usr/bin/php', $inventory['ampbin'] . '/module_admin', 'reload']);
        if (is_file('/var/lib/asterisk-recording-uploader/issabel-hook-error')) { throw new RuntimeException('SS-HOOK-1010: Recording layout conflicts; resolve the post hook and run activation.'); }
        sj_exec(['systemctl', 'daemon-reload']);
        sj_exec(['systemctl', 'enable', 'asterisk-recording-uploader.service']);
        sj_exec(['systemctl', 'restart', 'asterisk-recording-uploader.service']);
        sj_exec(['systemctl', 'is-active', '--quiet', 'asterisk-recording-uploader.service']);
        echo "Activation complete. Verify a test call in Issabel and Seda Sanj before production use.\n";
    } catch (Throwable $error) {
        @shell_exec('systemctl stop asterisk-recording-uploader.service 2>/dev/null');
        $previousManifest = json_decode((string) file_get_contents($backup . '/manifest.json'), true);
        if (empty($previousManifest[$module])) { @shell_exec('/usr/bin/php ' . escapeshellarg($inventory['ampbin'] . '/module_admin') . ' uninstall recuploader >/dev/null 2>&1'); }
        sj_restore($backup);
        if (!empty($previousManifest[$module])) { @shell_exec('/usr/bin/php ' . escapeshellarg($inventory['ampbin'] . '/module_admin') . ' install recuploader >/dev/null 2>&1'); }
        if ($wasRunning) { @shell_exec('systemctl restart asterisk-recording-uploader.service 2>/dev/null'); }
        @shell_exec('/usr/bin/php ' . escapeshellarg($inventory['ampbin'] . '/module_admin') . ' reload >/dev/null 2>&1');
        throw $error;
    }
} catch (Throwable $error) {
    $message = preg_match('/SS-[A-Z]+-[0-9]{4}/', $error->getMessage(), $match) ? $match[0] : 'SS-SYS-1012';
    fwrite(STDERR, $message . ": Activation failed. Review the compatibility guide and restore the verified backup if needed.\n");
    exit(1);
}
