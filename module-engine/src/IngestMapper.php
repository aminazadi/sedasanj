<?php
/**
 * IngestMapper.php - maps internal/legacy metadata onto the ingest
 * endpoint's field names. Ported from common.to_ingest_form() /
 * common._parse_time() / common._format_z().
 */

namespace Engine;

class IngestMapper
{
    /**
     * Accepts both old-style keys (uniqueid, src, dst, start_time,
     * duration_seconds, ...) and already-API-shaped keys
     * (asterisk_uniqueid, caller_number, ...) so spooled jobs / cached
     * state written by an older build keep working.
     *
     * Output (only non-null keys are returned):
     *   required: asterisk_uniqueid, caller_number, dialed_number,
     *             started_at, ended_at
     *   optional: direction, agent_extension
     */
    public static function toIngestForm(array $metadata): array
    {
        $pick = function (array $keys) use ($metadata) {
            foreach ($keys as $k) {
                $v = $metadata[$k] ?? null;
                if ($v !== null && $v !== '') {
                    return $v;
                }
            }
            return null;
        };

        $out = [];

        $filename = basename((string) ($metadata['source_filename'] ?? ''));
        $filenameCaller = null;
        $filenameDialed = null;
        $filenameDirection = null;
        if (preg_match('/^stereo_(in|out|exten)-([^-]+)-([^-]+)-/', $filename, $match) === 1) {
            $filenameDirection = $match[1] === 'in' ? 'inbound' : ($match[1] === 'out' ? 'outbound' : 'internal');
            $filenameDialed = $match[2];
            $filenameCaller = $match[3];
        }

        $out['asterisk_uniqueid'] = $pick(['asterisk_uniqueid', 'uniqueid', 'linkedid']);
        $out['caller_number'] = $pick(['caller_number', 'src', 'callerid', 'from']) ?? $filenameCaller;
        $dialedNumber = $pick(['dialed_number', 'dst', 'extension', 'to']) ?? $filenameDialed;
        $agentExt = $pick(['agent_extension', 'agent']);
        // Old failed jobs may contain a dialplan label and a punctuation-stripped
        // filename. Resolve the answered extension at send time as well as in the hook.
        $inbound = ($metadata['direction'] ?? $filenameDirection) === 'inbound'
            || preg_match('/^stereo_in(?:-|s[0-9])/', $filename) === 1;
        if ($agentExt === null && $inbound && preg_match('/[0-9]/', (string) $dialedNumber) !== 1) {
            $agentExt = AnsweredExtension::lookup((string) ($out['asterisk_uniqueid'] ?? ''));
        }
        if (preg_match('/[\p{Nd}]/u', (string) $dialedNumber) !== 1 && $agentExt !== null) {
            $dialedNumber = $agentExt;
        }
        $out['dialed_number'] = $dialedNumber;

        $startedRaw = $pick(['started_at', 'start_time', 'start']);
        $startedEpoch = null;
        $startedIso = null;
        if ($startedRaw !== null) {
            try {
                $startedEpoch = self::parseTime($startedRaw);
                $startedIso = self::formatZ($startedEpoch);
            } catch (\Exception $e) {
                $startedIso = (string) $startedRaw;
            }
        }
        if ($startedIso !== null) {
            $out['started_at'] = $startedIso;
        }

        $endedIso = null;
        $endedRaw = $pick(['ended_at', 'end_time', 'end']);
        if ($endedRaw !== null) {
            try {
                $endedIso = self::formatZ(self::parseTime($endedRaw));
            } catch (\Exception $e) {
                $endedIso = (string) $endedRaw;
            }
        } elseif ($startedEpoch !== null) {
            $dur = $pick(['duration_seconds', 'duration']);
            if ($dur !== null && is_numeric($dur)) {
                $endedIso = self::formatZ($startedEpoch + (float) $dur);
            }
        }
        if ($endedIso !== null) {
            $out['ended_at'] = $endedIso;
        }

        $direction = $pick(['direction']) ?? $filenameDirection ?? ($inbound ? 'inbound' : null);
        if ($direction) {
            $out['direction'] = (string) $direction;
        }

        if ($agentExt) {
            $out['agent_extension'] = (string) $agentExt;
        }

        if (!empty($metadata['_voicemail'])) {
            $out['mailbox'] = (string) ($metadata['mailbox'] ?? $out['dialed_number'] ?? '');
            $out['context'] = (string) ($metadata['voicemail_context'] ?? 'default');
            $out['folder'] = (string) ($metadata['voicemail_folder'] ?? 'INBOX');
            $out['message_id'] = (string) ($metadata['voicemail_message_id'] ?? '');
            $out['caller_number'] = (string) ($out['caller_number'] ?? '');
            $out['started_at'] = (string) ($out['started_at'] ?? '');
        }

        return array_filter($out, fn($v) => $v !== null);
    }

    /**
     * Parse a timestamp into a Unix epoch (float, UTC). Accepts Unix
     * epoch (int/float/numeric string) or ISO 8601 (with or without
     * trailing 'Z' / explicit offset). Naive datetimes are assumed UTC.
     *
     * @throws \Exception on failure
     */
    public static function parseTime($value): float
    {
        if (is_int($value) || is_float($value)) {
            return (float) $value;
        }
        $s = trim((string) $value);
        if ($s === '') {
            throw new \InvalidArgumentException('empty timestamp');
        }
        if (is_numeric($s)) {
            return (float) $s;
        }
        $iso = $s;
        if (substr($iso, -1) === 'Z') {
            $iso = substr($iso, 0, -1) . '+00:00';
        }
        $dt = new \DateTimeImmutable($iso, new \DateTimeZone('UTC'));
        return (float) $dt->format('U');
    }

    public static function formatZ(float $epoch): string
    {
        $dt = (new \DateTimeImmutable('@' . (int) $epoch))->setTimezone(new \DateTimeZone('UTC'));
        return $dt->format('Y-m-d\TH:i:s\Z');
    }
}
