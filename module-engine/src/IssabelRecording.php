<?php
namespace Engine;

class IssabelRecording
{
    public static function process(array $args, array $cfg, array $host): int
    {
        $directory = realpath((string) ($args[1] ?? ''));
        $root = realpath($host['monitor_dir'] ?? '');
        $name = (string) ($args[2] ?? '');
        if ($directory === false || $root === false || strpos($directory . '/', $root . '/') !== 0
            || !preg_match('/^[0-9A-Za-z*#+_.-]+$/', $name) || strpos($name, '..') !== false) {
            throw new \RuntimeException('SS-HOOK-1002');
        }
        if (!is_file($directory . '/' . $name . '.wav')) {
            $matches = [];
            foreach (glob($directory . '/*.wav') ?: [] as $candidate) {
                if (str_replace('-', '', basename($candidate, '.wav')) === str_replace('-', '', $name)) { $matches[] = basename($candidate, '.wav'); }
            }
            if (count($matches) !== 1) { throw new \RuntimeException('SS-HOOK-1011'); }
            $name = $matches[0]; $args[2] = $name;
        }
        // Do not copy a recording still opened by another MixMonitor leg after a transfer.
        exec('lsof -t -- ' . escapeshellarg($directory . '/' . $name . '.wav') . ' 2>/dev/null', $open, $status);
        if ($status === 0) { return 1; }
        if ($status !== 1) { throw new \RuntimeException('SS-HOOK-1011'); }
        $work = rtrim($cfg['watcher']['watch_dir'], '/') . '/' . hash('sha256', $directory . '/' . $name);
        if (!is_dir($work) && !mkdir($work, 0750, true) && !is_dir($work)) { throw new \RuntimeException('SS-SYS-1007'); }
        $lock = fopen($work . '/recording.lock', 'c');
        if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) { return 0; }
        try {
            if (is_file($work . '/prepared')) { return 0; }
            foreach (['', 'recv_', 'trans_'] as $prefix) {
                $source = $directory . '/' . $prefix . $name . '.wav';
                if (is_file($source) && !is_link($source) && !copy($source, $work . '/' . $prefix . $name . '.wav')) { throw new \RuntimeException('SS-STG-1001'); }
            }
            $args[1] = $work . '/';
            try {
                $rows = CdrSource::connect()->recordingRows((string) ($args[3] ?? ''));
                $row = $rows[0] ?? [];
                $known = [];
                foreach (($host['extensions'] ?? []) as $extension) { $known[(string) ($extension[0] ?? $extension['extension'] ?? '')] = true; }
                $src = (string) ($row['src'] ?? ''); $dst = (string) ($row['dst'] ?? '');
                if ($src !== '' && isset($known[$src])) { $args[9] = isset($known[$dst]) ? 'internal' : 'outbound'; }
                elseif ($dst !== '' && isset($known[$dst])) { $args[9] = 'inbound'; }
                elseif (strpos((string) ($row['dcontext'] ?? ''), 'from-internal') === 0) { $args[9] = 'outbound'; }
                if (preg_match('/^[0-9A-Za-z*#+_.-]+$/', $src)) { $args[4] = $src; }
                if (($args[9] ?? '') !== 'inbound' && preg_match('/^[0-9A-Za-z*#+_.-]+$/', $dst)) { $args[5] = $dst; }
            } catch (\Throwable $exception) {
                // Missing or late CDR does not discard the original or block audio delivery.
            }
            ksort($args);
            $arguments = array_merge([PHP_BINARY, __DIR__ . '/../bin/mix-stereo.php'], array_slice($args, 1));
            $command = implode(' ', array_map('escapeshellarg', $arguments));
            passthru($command, $exit);
            // A sidecar or tracked state proves that recovery can finish a failed first attempt.
            $stereo = $work . '/stereo_' . $name . '.wav';
            if ($exit === 0 || is_file($stereo) || StateStore::statusOf($cfg, $stereo) !== null) {
                IssabelSettings::atomic($work . '/prepared', gmdate('c'));
                @unlink($directory . '/recv_' . $name . '.wav');
                @unlink($directory . '/trans_' . $name . '.wav');
            }
            return $exit;
        } finally { flock($lock, LOCK_UN); fclose($lock); }
    }

    public static function recover(array $cfg, Logger $log): void
    {
        $host = json_decode((string) @file_get_contents(\Engine\Host\Factory::CONFIG), true);
        if (!is_array($host) || !is_dir($host['monitor_dir'] ?? '')) { return; }
        $iterator = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($host['monitor_dir'], \FilesystemIterator::SKIP_DOTS));
        foreach ($iterator as $file) {
            if ($file->getMTime() < ($host['activated_at'] ?? 0)) { continue; }
            if (!$file->isFile() || $file->isLink() || $file->getExtension() !== 'wav' || time() - $file->getMTime() < 60) { continue; }
            $name = $file->getBasename('.wav');
            if (!preg_match('/^(in|out|exten|q|internal)-([^-]+)-([^-]+)-(\d{8})-(\d{6})-([\d.]+)$/', $name, $m)) { continue; }
            try {
                ob_start();
                self::process(['hook', $file->getPath(), $name, $m[6], $m[3], $m[2], '', $m[2], ''], $cfg, $host);
                ob_end_clean();
            } catch (\Throwable $exception) {
                if (ob_get_level()) { ob_end_clean(); }
                $log->coded('SS-HOOK-1011', 'Recording recovery failed; run the Issabel health checks.');
            }
        }
    }
}
