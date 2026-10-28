#!/usr/bin/env php
<?php
/**
 * bin/sweeper.php - reconcile recordings against the state store.
 * Same --config/--once/--report flags as the old sweeper.py.
 */

require __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\Logger;
use Engine\Sweeper;
use Engine\VoicemailSweeper;

function sweeper_print_report(array $summary): void
{
    echo "Sweeper report\n";
    echo "--------------\n";
    echo "  OK (uploaded/spooled-and-verified): {$summary['ok']}\n";
    echo "  Ignored (excluded patterns):         {$summary['ignored']}\n";
    echo "  Too fresh to evaluate yet:           {$summary['too_fresh']}\n";
    if ($summary['problems']) {
        $count = count($summary['problems']);
        echo "  PROBLEM files needing attention:     {$count}\n";
        foreach ($summary['problems'] as $p) {
            echo "    - {$p['file']}  (state: {$p['status']})\n";
        }
    } else {
        echo "  PROBLEM files needing attention:     0\n";
    }
}

function sweeper_main(array $argv): int
{
    $configPath = null;
    $once = false;
    $report = false;
    $voicemail = false;
    foreach (array_slice($argv, 1) as $arg) {
        if ($arg === '--once') {
            $once = true;
        } elseif ($arg === '--report') {
            $report = true;
        } elseif ($arg === '--voicemail') {
            $voicemail = true;
        } elseif (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, strlen('--config='));
        }
    }

    try {
        $cfg = Config::load($configPath);
    } catch (ConfigError $exc) {
        fwrite(STDERR, "Config error: {$exc->getMessage()}\n");
        return 1;
    }
    $log = new Logger($cfg, 'aru.sweeper');

    if ($report) {
        $summary = $voicemail
            ? VoicemailSweeper::sweepOnce($cfg, $log, true)
            : Sweeper::sweepOnce($cfg, $log, true);
        sweeper_print_report($summary);
        return $summary['problems'] ? 1 : 0;
    }

    if ($once) {
        $summary = $voicemail
            ? VoicemailSweeper::sweepOnce($cfg, $log, false)
            : Sweeper::sweepOnce($cfg, $log, false);
        $log->info('Sweep complete: ' . json_encode($summary));
        return 0;
    }

    $interval = $voicemail ? $cfg['voicemail']['sweep_interval_seconds'] : $cfg['state']['sweep_interval_seconds'];
    $log->info("Starting sweeper, watch_dir={$cfg['watcher']['watch_dir']} interval={$interval}s");
    while (true) {
        try {
            $summary = $voicemail
                ? VoicemailSweeper::sweepOnce($cfg, $log, false)
                : Sweeper::sweepOnce($cfg, $log, false);
            $log->info('Sweep complete: ' . json_encode($summary));
        } catch (\Throwable $exc) {
            $log->error('Unexpected error during sweep: ' . $exc->getMessage());
        }
        sleep($interval);
    }
}

exit(sweeper_main($argv));
