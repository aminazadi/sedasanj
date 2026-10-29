<?php

namespace Engine;

use Engine\Voicemail\VoicemailMessage;

class VoicemailSweeper
{
    /** Minimum gap between retries of a voicemail message whose processing failed. */
    const FAILURE_RETRY_SECONDS = 21600;

    private static function directories(string $path): array
    {
        if (!is_dir($path) || is_link($path)) {
            return [];
        }
        $items = [];
        foreach (new \DirectoryIterator($path) as $entry) {
            if (!$entry->isDot() && $entry->isDir() && !$entry->isLink()) {
                $items[] = $entry->getPathname();
            }
        }
        return $items;
    }

    private static function enableEpoch(array $cfg): int
    {
        $path = dirname($cfg['state']['state_file']) . '/voicemail-enabled-at';
        $wasExisting = is_file($path);
        if (!$wasExisting && is_dir(dirname($path)) && is_writable(dirname($path))) {
            $stateStore = StateStore::create($cfg);
            $firstObserved = null;
            foreach (self::directories($cfg['voicemail']['spool_dir']) as $contextPath) {
                foreach (self::directories($contextPath) as $mailboxPath) {
                    foreach (self::directories($mailboxPath) as $folderPath) {
                        foreach (self::textFiles($folderPath) as $textPath) {
                            $message = @VoicemailMessage::fromTextFile(
                                $cfg['voicemail']['spool_dir'],
                                $textPath,
                                array_values(array_filter(array_map('trim', explode(',', $cfg['voicemail']['audio_preference']))))
                            );
                            if ($message === null || $stateStore->get($message['state_key']) !== null) {
                                continue;
                            }
                            $audioMtime = @filemtime($message['audio_path']) ?: 0;
                            $textMtime = @filemtime($message['text_path']) ?: 0;
                            $firstObserved = max($firstObserved ?? 0, $audioMtime, $textMtime);
                        }
                    }
                }
            }
            $epoch = $firstObserved ?? time();
            @file_put_contents($path, (string) $epoch, LOCK_EX);
            @chmod($path, 0640);
            return $epoch;
        }
        if (!is_file($path)) {
            @file_put_contents($path, (string) time(), LOCK_EX);
            @chmod($path, 0640);
        }
        return $wasExisting ? (int) trim((string) @file_get_contents($path)) : time();
    }

    private static function textFiles(string $folder): array
    {
        return glob(rtrim($folder, '/') . '/msg[0-9]*.txt') ?: [];
    }

    private static function folders(array $cfg): array
    {
        return array_values(array_filter(array_map('trim', explode(',', $cfg['voicemail']['folders'])), fn($v) => $v !== '' && strtolower($v) !== 'tmp'));
    }

    public static function sweepOnce(array $cfg, Logger $log, bool $dryRun = false): array
    {
        $summary = ['enabled' => !empty($cfg['voicemail']['enabled']), 'uploaded' => 0, 'spooled' => 0, 'ignored' => 0, 'too_fresh' => 0, 'pending' => 0, 'problems' => []];
        if (empty($cfg['voicemail']['enabled'])) {
            return $summary;
        }
        $root = $cfg['voicemail']['spool_dir'];
        if (!is_dir($root) || !is_readable($root)) {
            $summary['problems'][] = ['path' => $root, 'error' => 'voicemail spool is missing or unreadable'];
            return $summary;
        }
        $allowedFolders = self::folders($cfg);
        $mailboxFilter = array_values(array_filter(array_map('trim', explode(',', $cfg['voicemail']['mailbox_filter']))));
        $preference = array_values(array_filter(array_map('trim', explode(',', $cfg['voicemail']['audio_preference']))));
        $minAge = (int) $cfg['watcher']['min_file_age_seconds'];
        $enabledAt = !empty($cfg['voicemail']['backfill']) ? 0 : self::enableEpoch($cfg);
        $store = StateStore::create($cfg);
        $queue = Queue::create($cfg);
        $now = time();

        foreach (self::directories($root) as $contextPath) {
            foreach (self::directories($contextPath) as $mailboxPath) {
                $mailbox = basename($mailboxPath);
                if ($mailboxFilter && !in_array($mailbox, $mailboxFilter, true)) {
                    continue;
                }
                foreach (self::directories($mailboxPath) as $folderPath) {
                    $folder = basename($folderPath);
                    if (!in_array($folder, $allowedFolders, true) || strtolower($folder) === 'tmp') {
                        continue;
                    }
                    foreach (self::textFiles($folderPath) as $textPath) {
                        $message = null;
                        try {
                            $message = VoicemailMessage::fromTextFile($root, $textPath, $preference);
                            if ($message === null) {
                                continue;
                            }
                            $state = $store->get($message['state_key']);
                            if (in_array($state['status'] ?? '', ['ignored', 'uploaded'], true)) {
                                $summary['ignored']++;
                                continue;
                            }
                            $audioMtime = @filemtime($message['audio_path']) ?: 0;
                            $textMtime = @filemtime($message['text_path']) ?: 0;
                            if ($now - min($audioMtime, $textMtime) < $minAge) {
                                $summary['too_fresh']++;
                                continue;
                            }
                            if ($enabledAt > 0 && max($audioMtime, $textMtime) <= $enabledAt) {
                                StateStore::record($cfg, $message['state_key'], 'ignored', ['source' => 'voicemail_sweeper', 'metadata' => ['mailbox' => $message['mailbox'], 'folder' => $message['folder']]]);
                                $summary['ignored']++;
                                continue;
                            }
                            // A message that failed (staging, conversion, permanent upload error) is
                            // retried at most every FAILURE_RETRY_SECONDS instead of every sweep, which
                            // used to re-run ffmpeg and the upload each minute and fill the failed folder.
                            if (($state['status'] ?? '') === 'failed'
                                && $now - (float) ($state['last_updated_epoch'] ?? 0) < self::FAILURE_RETRY_SECONDS) {
                                $summary['quarantined'] = ($summary['quarantined'] ?? 0) + 1;
                                continue;
                            }
                            if (($state['status'] ?? '') === 'spooled' && !empty($state['job_id']) && $queue->get($state['job_id']) !== null) {
                                $summary['pending']++;
                                continue;
                            }
                            if ($dryRun) {
                                $summary['problems'][] = ['state_key' => $message['state_key'], 'status' => $state['status'] ?? 'new'];
                                continue;
                            }
                            $metadata = [
                                '_voicemail' => true,
                                '_state_key' => $message['state_key'],
                                '_vm_source_dir' => dirname($message['text_path']),
                                'uniqueid' => $message['uniqueid'],
                                'asterisk_uniqueid' => $message['uniqueid'],
                                'caller_number' => $message['caller_number'] ?? '',
                                'dialed_number' => $message['mailbox'],
                                'mailbox' => $message['mailbox'],
                                'voicemail_context' => $message['context'],
                                'voicemail_folder' => $message['folder'],
                                'voicemail_message_id' => $message['message_id'] ?? '',
                                'direction' => 'inbound',
                                'started_at' => $message['started_epoch'],
                                'duration_seconds' => $message['duration_seconds'],
                            ];
                            StateStore::record($cfg, $message['state_key'], 'uploading', ['source' => 'voicemail_sweeper', 'metadata' => $metadata]);
                            $stagedPath = Staging::prepareVoicemail($cfg, $message['audio_path'], $message['state_key'], $log->asClosure('DEBUG'));
                            [$outcome, $jobId, $error] = Pipeline::deliverStaged($cfg, $stagedPath, null, $metadata, true, $log);
                            if ($outcome === 'uploaded') {
                                StateStore::record($cfg, $message['state_key'], 'uploaded', ['source' => 'voicemail_sweeper']);
                                $summary['uploaded']++;
                            } elseif ($outcome === 'spooled') {
                                StateStore::record($cfg, $message['state_key'], 'spooled', ['source' => 'voicemail_sweeper', 'job_id' => $jobId, 'last_error' => $error]);
                                $summary['spooled']++;
                            } else {
                                StateStore::record($cfg, $message['state_key'], 'failed', ['source' => 'voicemail_sweeper', 'last_error' => $error]);
                                $summary['problems'][] = ['state_key' => $message['state_key'], 'error' => $error];
                            }
                        } catch (\Throwable $exc) {
                            $summary['problems'][] = ['file' => $textPath, 'error' => $exc->getMessage()];
                            $log->coded('SS-VMX-1003', "Voicemail processing failed for {$textPath}: {$exc->getMessage()}");
                            if (isset($message) && is_array($message)) {
                                StateStore::record($cfg, $message['state_key'], 'failed', ['source' => 'voicemail_sweeper', 'last_error' => $exc->getMessage()]);
                            }
                        }
                    }
                }
            }
        }
        return $summary;
    }
}
