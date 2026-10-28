<?php

namespace Engine;

class MissedCallPoller
{
    private const TYPES = [
        'NO ANSWER' => 'no_answer', 'NOANSWER' => 'no_answer',
        'BUSY' => 'busy', 'CONGESTION' => 'congestion', 'FAILED' => 'failed',
        'CANCEL' => 'canceled', 'CANCELED' => 'canceled',
    ];

    public static function tick(array $cfg, Logger $log): array
    {
        if (empty($cfg['missed_calls']['enabled'])) {
            return ['disabled' => true, 'queued' => 0, 'delivered' => 0];
        }
        $cursorPath = $cfg['missed_calls']['cursor_file'];
        $stateDir = dirname($cursorPath);
        $sentDir = $stateDir . '/sent';
        $queueDir = $cfg['missed_calls']['spool_dir'];
        $failedDir = $cfg['missed_calls']['failed_dir'];
        if (!is_dir($stateDir) && !mkdir($stateDir, 0750, true) && !is_dir($stateDir)) {
            throw new \RuntimeException('Cannot create missed-call state directory');
        }
        foreach ([$queueDir, $failedDir, $sentDir] as $dir) {
            if (!is_dir($dir) && !mkdir($dir, 0750, true) && !is_dir($dir)) {
                throw new \RuntimeException('Cannot create missed-call spool directory');
            }
        }
        self::pruneSentMarkers($sentDir, time() - (int) $cfg['missed_calls']['overlap_seconds'] - (int) $cfg['missed_calls']['settle_seconds']);
        self::flushQueue($cfg, $queueDir, $failedDir, $sentDir, $log);
        $now = time();
        $settle = (int) $cfg['missed_calls']['settle_seconds'];
        $overlap = (int) $cfg['missed_calls']['overlap_seconds'];
        $cursor = self::readCursor($cursorPath);
        if (empty($cursor['initialized'])) {
            $cursor = [
                'epoch' => max(0, $now - $settle),
                'initialized' => true,
            ];
        }
        try {
            $source = CdrSource::connect();
        } catch (\Throwable $exc) {
            $log->warning('CDR connection failed; retrying on next poll: ' . $exc->getMessage());
            return ['candidates' => 0, 'queued' => 0, 'delivered' => 0, 'source_error' => true];
        }
        $diagnostics = $source->diagnostics();
        if (!$diagnostics['available']) {
            throw new \RuntimeException('CDR source unavailable: ' . json_encode($diagnostics));
        }
        $windowStart = isset($cursor['window_start'])
            ? (int) $cursor['window_start']
            : max(0, (int) $cursor['epoch'] - $overlap);
        $afterEpoch = isset($cursor['page_epoch'])
            ? (int) $cursor['page_epoch']
            : $windowStart - 1;
        $afterLinkedId = isset($cursor['page_linkedid']) ? (string) $cursor['page_linkedid'] : '';
        $rows = $source->candidates($windowStart, $afterEpoch, $afterLinkedId, $now);
        $queued = 0;
        $maxEpoch = (int) $cursor['epoch'];
        foreach ($rows as $candidate) {
            $linkedid = (string) $candidate['linkedid'];
            $epoch = (int) $candidate['latest_epoch'];
            if ($epoch > $now - $settle) {
                continue;
            }
            $maxEpoch = max($maxEpoch, $epoch);
            $group = $source->group($linkedid);
            $event = self::toEvent($group, $linkedid);
            if ($event === null) {
                continue;
            }
            $sentMarker = $sentDir . '/' . hash('sha256', $linkedid) . '.json';
            if (is_file($sentMarker)) {
                continue;
            }
            $file = $queueDir . '/' . hash('sha256', $linkedid) . '.json';
            if (!is_file($file)) {
                self::atomicJson($file, $event);
                $queued++;
            }
        }
        if (count($rows) >= 500) {
            $last = end($rows);
            self::atomicJson($cursorPath, [
                'epoch' => $maxEpoch,
                'initialized' => true,
                'window_start' => $windowStart,
                'page_epoch' => (int) $last['latest_epoch'],
                'page_linkedid' => (string) $last['linkedid'],
                'updated_at' => gmdate(DATE_ATOM),
            ]);
        } else {
            $maxEpoch = max($maxEpoch, $now - $settle);
            self::atomicJson($cursorPath, ['epoch' => $maxEpoch, 'initialized' => true, 'updated_at' => gmdate(DATE_ATOM)]);
        }
        $delivered = self::flushQueue($cfg, $queueDir, $failedDir, $sentDir, $log);
        return ['candidates' => count($rows), 'queued' => $queued, 'delivered' => $delivered];
    }

    public static function toEvent(array $rows, string $linkedid): ?array
    {
        if (!$rows) {
            return null;
        }
        foreach ($rows as $row) {
            if (strtoupper((string) $row['disposition']) === 'ANSWERED') {
                return null;
            }
        }
        $rows = array_values(array_filter($rows, static function ($row) {
            return strtoupper(trim((string) $row['disposition'])) !== 'ANSWERED';
        }));
        $root = array_values(array_filter($rows, static function ($row) use ($linkedid) {
            return (string) $row['uniqueid'] === $linkedid;
        }));
        $row = $root ? end($root) : end($rows);
        $type = self::TYPES[strtoupper(trim((string) $row['disposition']))] ?? null;
        if ($type === null) {
            return null;
        }
        $started = isset($row['call_epoch']) ? (int) $row['call_epoch'] : false;
        if ($started === false) {
            return null;
        }
        $duration = max(0, (int) $row['duration']);
        $src = trim((string) $row['src']);
        $dst = trim((string) $row['dst']);
        if ($src === '' || $dst === '') {
            return null;
        }
        $context = strtolower((string) ($row['dcontext'] ?? ''));
        $direction = null;
        if (strpos($context, 'ext-local') !== false) {
            $direction = 'internal';
        } elseif (strpos($context, 'from-trunk') !== false || strpos($context, 'ext-did') !== false) {
            $direction = 'inbound';
        }
        $extensionCandidates = [];
        foreach ($rows as $candidate) {
            if (strpos(strtolower((string) ($candidate['dcontext'] ?? '')), 'ext-local') !== false) {
                $candidateExtension = trim((string) $candidate['dst']);
                if (preg_match('/^[0-9*#]{1,20}$/', $candidateExtension)) {
                    $extensionCandidates[$candidateExtension] = true;
                }
            }
        }
        $extension = count($extensionCandidates) === 1 ? (string) array_key_first($extensionCandidates) : null;
        return [
            'asterisk_uniqueid' => $linkedid,
            'call_type' => $type,
            'caller_number' => substr($src, 0, 80),
            'dialed_number' => substr($dst, 0, 80),
            'started_at' => gmdate('c', $started),
            'ended_at' => gmdate('c', $started + $duration),
            'direction' => $direction,
            'agent_extension' => $extension,
            'source' => 'freepbx-cdr',
            'external_reference' => $linkedid,
        ];
    }

    private static function flushQueue(array $cfg, string $queueDir, string $failedDir, string $sentDir, Logger $log): int
    {
        $delivered = 0;
        foreach (glob($queueDir . '/*.json') ?: [] as $path) {
            $event = json_decode((string) file_get_contents($path), true);
            if (!is_array($event)) {
                rename($path, $failedDir . '/' . basename($path));
                continue;
            }
            try {
                Uploader::uploadMissedCall($cfg, $event, $log->asClosure('WARNING'));
                self::atomicJson($sentDir . '/' . hash('sha256', (string) $event['asterisk_uniqueid']) . '.json', [
                    'asterisk_uniqueid' => $event['asterisk_uniqueid'],
                    'sent_at' => gmdate(DATE_ATOM),
                ]);
                unlink($path);
                $delivered++;
            } catch (\Throwable $exc) {
                $retryable = !($exc instanceof UploadError) || $exc->retryable;
                if (!$retryable) {
                    rename($path, $failedDir . '/' . basename($path));
                    $log->error('Permanent missed-call upload failure: ' . $exc->getMessage());
                } else {
                    $log->warning('Missed-call upload will retry: ' . $exc->getMessage());
                }
            }
        }
        return $delivered;
    }

    private static function readCursor(string $path): array
    {
        $value = is_file($path) ? json_decode((string) file_get_contents($path), true) : null;
        return is_array($value) && isset($value['epoch']) ? $value : ['epoch' => 0, 'initialized' => false];
    }

    private static function pruneSentMarkers(string $sentDir, int $olderThan): void
    {
        foreach (glob($sentDir . '/*.json') ?: [] as $path) {
            $marker = json_decode((string) @file_get_contents($path), true);
            $sentAt = is_array($marker) && isset($marker['sent_at']) ? strtotime((string) $marker['sent_at']) : false;
            if ($sentAt !== false && $sentAt < $olderThan) {
                @unlink($path);
            }
        }
    }

    private static function atomicJson(string $path, array $value): void
    {
        $tmp = $path . '.' . bin2hex(random_bytes(5)) . '.tmp';
        if (file_put_contents($tmp, json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), LOCK_EX) === false
            || !rename($tmp, $path)) {
            @unlink($tmp);
            throw new \RuntimeException('Unable to persist missed-call state');
        }
    }
}
