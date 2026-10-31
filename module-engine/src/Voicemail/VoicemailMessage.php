<?php

namespace Engine\Voicemail;

use Engine\StagingError;

class VoicemailMessage
{
    public static function fromTextFile(string $root, string $textPath, array $audioPreference): ?array
    {
        $realRoot = realpath($root);
        $realText = realpath($textPath);
        if ($realRoot === false || $realText === false || !str_starts_with($realText, rtrim($realRoot, '/') . '/')) {
            return null;
        }
        $folderPath = dirname($realText);
        $mailboxPath = dirname($folderPath);
        $contextPath = dirname($mailboxPath);
        $folder = basename($folderPath);
        $mailbox = basename($mailboxPath);
        $context = basename($contextPath);
        if (strtolower($folder) === 'tmp' || !self::safePart($folder) || !self::safePart($mailbox) || !self::safePart($context)) {
            return null;
        }
        $data = @parse_ini_file($realText, true, INI_SCANNER_RAW);
        $message = is_array($data) ? ($data['message'] ?? null) : null;
        if (!is_array($message) || !isset($message['origtime']) || !is_numeric($message['origtime'])) {
            throw new StagingError("Voicemail metadata is missing a numeric origtime: {$realText}");
        }
        $stem = pathinfo($realText, PATHINFO_FILENAME);
        if (preg_match('/^msg\d+$/', $stem) !== 1) {
            return null;
        }
        $audioPath = null;
        foreach ($audioPreference as $extension) {
            $candidate = dirname($realText) . '/' . $stem . '.' . $extension;
            if (is_file($candidate) && !is_link($candidate) && filesize($candidate) > 0) {
                $audioPath = $candidate;
                break;
            }
        }
        if ($audioPath === null) {
            return null;
        }
        $callerId = trim((string) ($message['callerid'] ?? ''));
        $callerNumber = null;
        if (preg_match('/<([^<>]+)>\s*$/', $callerId, $match) === 1) {
            $candidate = trim($match[1]);
            if ($candidate !== '' && strtolower($candidate) !== 'unknown') {
                $callerNumber = $candidate;
            }
        } elseif ($callerId !== '' && strtolower($callerId) !== 'unknown') {
            $candidate = preg_replace('/^\s*".*?"\s*/', '', $callerId);
            if (preg_match('/[+\d][+\d(). -]*/', (string) $candidate, $match) === 1) {
                $callerNumber = trim($match[0]);
            }
        }
        $origtime = (int) $message['origtime'];
        $duration = isset($message['duration']) && is_numeric($message['duration'])
            ? max(0, (int) $message['duration'])
            : 0;
        $messageId = trim((string) ($message['msg_id'] ?? ''));
        $audioHash = hash_file('sha256', $audioPath);
        $logicalId = $messageId !== ''
            ? $messageId
            : substr(hash('sha256', $origtime . ':' . $callerId . ':' . $audioHash), 0, 40);
        $stateKey = 'vm:' . $context . '/' . $mailbox . '/' . $logicalId;
        return [
            'state_key' => $stateKey,
            'uniqueid' => 'vm-' . hash('sha256', $stateKey),
            'context' => $context,
            'mailbox' => $mailbox,
            'folder' => $folder,
            'message_id' => $messageId !== '' ? $messageId : null,
            'caller_number' => $callerNumber,
            'started_epoch' => $origtime,
            'duration_seconds' => $duration,
            'text_path' => $realText,
            'audio_path' => $audioPath,
        ];
    }

    private static function safePart(string $value): bool
    {
        return $value !== '' && $value !== '.' && $value !== '..'
            && preg_match('/^[A-Za-z0-9_.+-]{1,120}$/', $value) === 1;
    }
}
