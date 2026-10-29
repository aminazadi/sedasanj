#!/usr/bin/env php
<?php
/**
 * bin/uploader.php - upload a finished call recording. Same flags as the
 * old uploader.py, so mix-stereo.php (and any manual/scripted invocation)
 * carries over unchanged. See plan.md §4 step 5.
 */

require __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\Logger;
use Engine\Pipeline;
use Engine\Staging;
use Engine\StateStore;

function aru_parse_args(array $argv): array
{
    $opts = [
        'file' => null, 'config' => null, 'uniqueid' => null, 'linkedid' => null,
        'callerid' => null, 'src' => null, 'dst' => null, 'direction' => null,
        'agent-extension' => null, 'start' => null, 'end' => null, 'duration' => null,
        'context' => null, 'extra' => [], 'no-spool' => false,
    ];
    $i = 1;
    $n = count($argv);
    while ($i < $n) {
        $arg = $argv[$i];
        if ($arg === '--no-spool') {
            $opts['no-spool'] = true;
            $i++;
            continue;
        }
        if (str_starts_with($arg, '--') && $i + 1 < $n) {
            $key = substr($arg, 2);
            $val = $argv[$i + 1];
            if ($key === 'extra') {
                $opts['extra'][] = $val;
            } else {
                $opts[$key] = $val;
            }
            $i += 2;
            continue;
        }
        $i++;
    }
    return $opts;
}

function aru_build_metadata(array $opts): array
{
    $meta = [
        'uniqueid' => $opts['uniqueid'],
        'linkedid' => $opts['linkedid'],
        'callerid' => $opts['callerid'],
        'src' => $opts['src'],
        'dst' => $opts['dst'],
        'direction' => $opts['direction'],
        'agent_extension' => $opts['agent-extension'],
        'start_time' => $opts['start'],
        'end_time' => $opts['end'],
        'duration_seconds' => $opts['duration'],
        'context' => $opts['context'],
        'source_filename' => basename($opts['file']),
    ];
    foreach ($opts['extra'] as $item) {
        if (strpos($item, '=') !== false) {
            [$k, $v] = explode('=', $item, 2);
            $meta[$k] = $v;
        }
    }
    return array_filter($meta, fn($v) => $v !== null && $v !== '');
}

function aru_main(array $argv): int
{
    $opts = aru_parse_args($argv);

    if (empty($opts['file'])) {
        fwrite(STDERR, "uploader.php: --file is required\n");
        return 1;
    }

    try {
        $cfg = Config::load($opts['config']);
    } catch (ConfigError $exc) {
        fwrite(STDERR, "Config error: {$exc->getMessage()}\n");
        return 1;
    }

    $log = new Logger($cfg, 'aru');

    if (!is_file($opts['file'])) {
        $log->error("Recording file does not exist: {$opts['file']}");
        return 1;
    }

    $metadata = aru_build_metadata($opts);
    $metadata['_sidecar_path'] = $opts['file'] . '.metadata.json';
    $log->info("Starting upload for {$opts['file']} with metadata=" . json_encode($metadata));

    // State is tracked under the *original* stereo path throughout this
    // call's lifetime, even after that exact file is renamed away/deleted
    // by prepareRecording() below - it's just an identifier string.
    StateStore::record($cfg, $opts['file'], 'uploading', ['metadata' => $metadata, 'source' => 'uploader']);

    try {
        [$stagedPath, $archivePath] = Staging::prepareRecording($cfg, $opts['file'], $log->asClosure('DEBUG'));
    } catch (\Throwable $exc) {
        // The original stereo file is still in place, so the sweeper will
        // retry the whole pipeline later.
        $log->error("Could not stage/archive recording {$opts['file']}: {$exc->getMessage()}");
        StateStore::record($cfg, $opts['file'], 'failed', [
            'source' => 'uploader',
            'last_error' => "prepare_recording failed: {$exc->getMessage()}",
        ]);
        return 1;
    }

    // Queue jobs update the same state row as this process (keyed by the original path).
    $metadata['_state_key'] = $opts['file'];
    [$outcome, $jobId, $error] = Pipeline::deliverStaged(
        $cfg, $stagedPath, $archivePath, $metadata, !$opts['no-spool'], $log
    );

    if ($outcome === 'uploaded') {
        @unlink($metadata['_sidecar_path']);
        StateStore::record($cfg, $opts['file'], 'uploaded', ['source' => 'uploader']);
        return 0;
    }
    if ($outcome === 'spooled') {
        StateStore::record($cfg, $opts['file'], 'spooled', [
            'source' => 'uploader', 'job_id' => $jobId, 'last_error' => $error,
        ]);
        return 2;
    }
    StateStore::record($cfg, $opts['file'], 'failed', ['source' => 'uploader', 'last_error' => $error]);
    return 1;
}

exit(aru_main($argv));
