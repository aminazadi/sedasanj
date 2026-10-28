#!/usr/bin/env php
<?php
/**
 * bin/service.php - combined queue-worker + sweeper service, one process
 * / one systemd unit (asterisk-recording-uploader.service), ported from
 * service.py.
 *
 * PHP CLI has no equivalent of Python's lightweight `threading` module
 * (pthreads isn't part of a standard PHP-CLI build), so this runs a
 * single-process cooperative event loop instead of two real threads:
 * every 1s tick, the queue worker runs (its own 5s cadence), and the
 * sweeper runs on its own cadence (state.sweep_interval_seconds).
 * Functionally this matches service.py's two-loop model - both run on
 * their own schedule, on one shared clock - without needing a threading
 * extension most target boxes won't have.
 *
 * Clean SIGTERM/SIGINT handling uses pcntl when available; if pcntl is
 * missing, the service just relies on systemd's SIGKILL after
 * TimeoutStopSec instead of a clean in-process stop (degrades gracefully,
 * not a hard requirement - see plan.md §3.1).
 */

require __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\Logger;
use Engine\MissedCallPoller;
use Engine\Queue;
use Engine\QueueWorker;
use Engine\Sweeper;
use Engine\VoicemailSweeper;

$GLOBALS['aru_stop'] = false;

function aru_request_stop(): void
{
    $GLOBALS['aru_stop'] = true;
}

function service_main(array $argv): int
{
    $configPath = getenv('ARU_CONFIG') ?: null;
    if (isset($argv[1])) {
        $configPath = $argv[1];
    }

    try {
        $cfg = Config::load($configPath);
    } catch (ConfigError $exc) {
        fwrite(STDERR, "Config error: {$exc->getMessage()}\n");
        return 1;
    }
    $log = new Logger($cfg, 'aru.service');
    $log->info('Starting combined asterisk-recording-uploader service (queue + sweeper)');

    // One-time JSON->SQLite backlog migration on startup (plan.md §3.5).
    try {
        $migrated = Queue::migrateJsonBacklog($cfg);
        if ($migrated > 0) {
            $log->info("Migrated {$migrated} pre-existing JSON job file(s) into the SQLite queue");
        }
    } catch (\Throwable $exc) {
        $log->warning("JSON->SQLite job migration skipped: {$exc->getMessage()}");
    }
    try {
        $recovered = Queue::recoverStagedOrphans($cfg);
        if ($recovered) {
            $log->warning("Recovered {$recovered} staged recording(s) after interrupted processing");
        }
    } catch (\Throwable $exc) {
        $log->warning("Staged orphan recovery skipped: {$exc->getMessage()}");
    }

    $hasPcntl = extension_loaded('pcntl');
    if ($hasPcntl) {
        pcntl_async_signals(true);
        pcntl_signal(SIGTERM, function ($signum) use ($log) {
            $log->info("Received signal {$signum}, shutting down");
            aru_request_stop();
        });
        pcntl_signal(SIGINT, function ($signum) use ($log) {
            $log->info("Received signal {$signum}, shutting down");
            aru_request_stop();
        });
    } else {
        $log->warning('pcntl extension not available; relying on systemd SIGKILL for shutdown');
    }

    $queueIntervalSeconds = 5;
    $sweepIntervalSeconds = $cfg['state']['sweep_interval_seconds'];
    $voicemailIntervalSeconds = $cfg['voicemail']['sweep_interval_seconds'];
    $missedCallsIntervalSeconds = $cfg['missed_calls']['poll_interval_seconds'];

    $nextQueueTick = 0.0;
    $nextSweepTick = 0.0;
    $nextVoicemailTick = 0.0;
    $nextMissedCallsTick = 0.0;

    $log->info("Queue worker loop started, spool_dir={$cfg['queue']['spool_dir']}");
    $log->info("Sweeper loop started, watch_dir={$cfg['watcher']['watch_dir']} interval={$sweepIntervalSeconds}s");
    $log->info("Voicemail sweeper loop started, enabled=" . (empty($cfg['voicemail']['enabled']) ? 'false' : 'true') . " interval={$voicemailIntervalSeconds}s");
    $log->info("Missed-call poller started, enabled=" . (empty($cfg['missed_calls']['enabled']) ? 'false' : 'true') . " interval={$missedCallsIntervalSeconds}s");

    while (!$GLOBALS['aru_stop']) {
        $now = microtime(true);

        if ($now >= $nextQueueTick) {
            try {
                QueueWorker::tick($cfg, $log);
            } catch (\Throwable $exc) {
                $log->error('Unexpected error in queue worker loop: ' . $exc->getMessage());
            }
            $nextQueueTick = $now + $queueIntervalSeconds;
        }

        if ($now >= $nextSweepTick) {
            try {
                $summary = Sweeper::sweepOnce($cfg, $log, false);
                $log->info('Sweep complete: ' . json_encode($summary));
            } catch (\Throwable $exc) {
                $log->error('Unexpected error during sweep: ' . $exc->getMessage());
            }
            $nextSweepTick = $now + $sweepIntervalSeconds;
        }

        if ($now >= $nextVoicemailTick) {
            try {
                $summary = VoicemailSweeper::sweepOnce($cfg, $log, false);
                if (!empty($cfg['voicemail']['enabled'])) {
                    $log->info('Voicemail sweep complete: ' . json_encode($summary));
                }
            } catch (\Throwable $exc) {
                $log->error('Unexpected error during voicemail sweep: ' . $exc->getMessage());
            }
            $nextVoicemailTick = $now + $voicemailIntervalSeconds;
        }

        if ($now >= $nextMissedCallsTick) {
            if (!empty($cfg['missed_calls']['enabled'])) {
                try {
                    $summary = MissedCallPoller::tick($cfg, $log);
                    $log->info('Missed-call poll complete: ' . json_encode($summary));
                } catch (\Throwable $exc) {
                    $log->error('Unexpected error during missed-call poll: ' . $exc->getMessage());
                }
            }
            $nextMissedCallsTick = $now + $missedCallsIntervalSeconds;
        }

        $sleepUntil = min($nextQueueTick, $nextSweepTick, $nextVoicemailTick, $nextMissedCallsTick);
        $sleepFor = max(0.0, min(1.0, $sleepUntil - microtime(true)));
        usleep((int) ($sleepFor * 1_000_000));
    }

    $log->info('Service stopped');
    return 0;
}

exit(service_main($argv));
