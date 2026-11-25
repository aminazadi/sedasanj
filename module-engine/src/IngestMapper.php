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
     *   optional: direction, agent_extension, caller_extension,
     *             dialed_extension, pbx_evidence
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

        $out['asterisk_uniqueid'] = self::scalar($pick(['asterisk_uniqueid', 'uniqueid', 'linkedid']));

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

        $direction = self::scalar($pick(['direction'])) ?? $filenameDirection;
        if ($direction === null && preg_match('/^stereo_in(?:-|s[0-9])/', $filename) === 1) {
            $direction = 'inbound';
        }
        if (!in_array($direction, ['inbound', 'outbound', 'internal'], true)) {
            $direction = null;
        }
        if ($direction !== null) {
            $out['direction'] = $direction;
        }

        $out = array_filter(
            $out + self::resolveParties(
                $metadata,
                $filename,
                $filenameCaller,
                $filenameDialed,
                (string) ($direction ?? ''),
                $startedEpoch
            ),
            fn($v) => $v !== null && $v !== ''
        );

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

        if (!empty($metadata['_voicemail'])) {
            $out['mailbox'] = (string) ($metadata['mailbox'] ?? $out['dialed_number'] ?? '');
            $out['context'] = (string) ($metadata['voicemail_context'] ?? 'default');
            $out['folder'] = (string) ($metadata['voicemail_folder'] ?? 'INBOX');
            $out['message_id'] = (string) ($metadata['voicemail_message_id'] ?? '');
            $out['caller_number'] = (string) ($out['caller_number'] ?? '');
            $out['started_at'] = (string) ($out['started_at'] ?? '');
        }

        return $out;
    }

    /**
     * Resolves caller/dialed values without ever forwarding a dialplan label
     * (for example "recordcheck" or "ivr2") as a phone number. CDR evidence is
     * used when the captured values are missing or non-numeric; an ambiguous
     * CDR answer is surfaced instead of guessed.
     *
     * @return array<string,string>
     */
    private static function resolveParties(
        array $metadata,
        string $filename,
        $filenameCaller,
        $filenameDialed,
        string $direction,
        ?float $startedEpoch
    ): array {
        $uniqueId = self::scalar(
            $metadata['asterisk_uniqueid'] ?? $metadata['uniqueid'] ?? $metadata['linkedid'] ?? null
        ) ?? '';

        $caller = self::number($metadata['caller_number'] ?? null)
            ?? self::number($metadata['src'] ?? null)
            ?? self::number($metadata['callerid'] ?? null)
            ?? self::number($metadata['from'] ?? null)
            ?? self::number($filenameCaller);
        $dialed = self::number($metadata['dialed_number'] ?? null)
            ?? self::number($metadata['dst'] ?? null)
            ?? self::number($metadata['extension'] ?? null)
            ?? self::number($metadata['to'] ?? null)
            ?? self::number($filenameDialed);
        $agent = self::number($metadata['agent_extension'] ?? null)
            ?? self::number($metadata['agent'] ?? null);
        $pbx = self::scalar($metadata['pbx_evidence'] ?? null);

        $evidence = [];
        if (empty($metadata['_voicemail']) && $uniqueId !== ''
            && in_array($direction, ['inbound', 'outbound', 'internal'], true)) {
            $evidence = CallPartyEvidence::lookup(
                $uniqueId,
                $filename,
                $direction,
                $startedEpoch === null ? null : (int) $startedEpoch
            );
        }
        $ambiguous = ($evidence['pbx_evidence'] ?? '') === 'ambiguous';
        if (!$ambiguous) {
            $caller = $caller ?? self::number($evidence['caller_extension'] ?? null);
            $dialed = $dialed ?? self::number($evidence['dialed_extension'] ?? null);
            $agent = $agent ?? self::number($evidence['agent_extension'] ?? null);
            if (isset($evidence['pbx_evidence'])) {
                $pbx = (string) $evidence['pbx_evidence'];
            }
        } else {
            $pbx = 'ambiguous';
        }

        // Legacy inbound path: the answered extension is the product's dialed
        // destination when the dialplan supplied a label.
        if ($direction === 'inbound' && $dialed === null) {
            $answered = self::number(AnsweredExtension::lookup($uniqueId));
            if ($answered !== null) {
                $dialed = $answered;
                $agent = $agent ?? $answered;
                $pbx = 'cdr';
            }
        }
        // Last resort for inbound: the DID is still better than dropping the call.
        if ($direction === 'inbound' && $dialed === null) {
            $fromDid = self::number($metadata['from_did'] ?? null)
                ?? self::number($metadata['did'] ?? null);
            if ($fromDid !== null) {
                $dialed = $fromDid;
                $pbx = 'direct';
            }
        }

        return array_filter([
            'caller_number' => $caller,
            'dialed_number' => $dialed,
            'agent_extension' => $agent,
            'caller_extension' => $ambiguous ? null : self::number($evidence['caller_extension'] ?? null),
            'dialed_extension' => $ambiguous ? null : self::number($evidence['dialed_extension'] ?? null),
            'pbx_evidence' => in_array($pbx, ['cdr', 'ambiguous', 'direct'], true) ? $pbx : null,
        ], fn($v) => $v !== null && $v !== '');
    }

    /** Trim a metadata value to a non-empty string; arrays/objects are ignored. */
    private static function scalar($value): ?string
    {
        if ($value === null || is_array($value) || is_object($value)) {
            return null;
        }
        $text = trim((string) $value);
        return $text === '' ? null : $text;
    }

    /**
     * A value is a call number only when it is made of digits and dialing
     * symbols. Dialplan labels such as "recordcheck" or "ivr2" are rejected.
     */
    private static function number($value): ?string
    {
        $text = self::scalar($value);
        if ($text === null) {
            return null;
        }
        $text = trim($text, "\"'");
        return preg_match('/^[0-9*#+]+$/', $text) === 1 && preg_match('/[0-9]/', $text) === 1
            ? $text
            : null;
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
