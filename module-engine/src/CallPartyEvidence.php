<?php

namespace Engine;

class CallPartyEvidence
{
    public static function endpoint(string $channel): ?string
    {
        return preg_match('~^(?:PJSIP|SIP)/([0-9]{1,8})-[a-f0-9]{8}$~i', $channel, $match)
            ? $match[1] : null;
    }

    public static function fromRows(array $rows, string $direction): array
    {
        $origins = [];
        $destinations = [];
        foreach ($rows as $row) {
            if (strtoupper((string) ($row['disposition'] ?? '')) !== 'ANSWERED') {
                continue;
            }
            $origin = self::endpoint((string) ($row['channel'] ?? ''));
            $destination = self::endpoint((string) ($row['dstchannel'] ?? ''));
            if ($origin !== null) {
                $origins[$origin] = true;
            }
            if ($destination !== null) {
                $destinations[$destination] = true;
            }
        }

        $needsOrigin = $direction !== 'inbound';
        $needsDestination = $direction !== 'outbound';
        if (($needsOrigin && count($origins) > 1) || ($needsDestination && count($destinations) > 1)) {
            return ['pbx_evidence' => 'ambiguous'];
        }
        $origin = $needsOrigin && $origins ? (string) array_key_first($origins) : null;
        $destination = $needsDestination && $destinations ? (string) array_key_first($destinations) : null;
        if ($origin === null && $destination === null) {
            return [];
        }
        return array_filter([
            'pbx_evidence' => 'cdr',
            'caller_extension' => $origin,
            'dialed_extension' => $destination,
            'agent_extension' => $direction === 'outbound' ? $origin : $destination,
        ], static function ($value) {
            return $value !== null;
        });
    }

    public static function lookup(string $uniqueId, string $filename, string $direction): array
    {
        if ($uniqueId === '' || !in_array($direction, ['inbound', 'outbound', 'internal'], true)) {
            return [];
        }
        try {
            [$db, $table] = Host\Factory::create()->cdr();
            if (!preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $table)) {
                return [];
            }
            $filename = preg_replace('/^stereo_/', '', basename($filename));
            $stem = pathinfo($filename, PATHINFO_FILENAME);
            $recording = $stem === '' ? '' : $stem . '.wav';
            $statement = $db->prepare(
                'SELECT disposition, channel, dstchannel, uniqueid, recordingfile FROM `' . $table
                . '` WHERE uniqueid = :uniqueid OR linkedid = :linkedid LIMIT 101'
            );
            for ($attempt = 0; $attempt < 3; $attempt++) {
                $statement->execute(['uniqueid' => $uniqueId, 'linkedid' => $uniqueId]);
                $rows = $statement->fetchAll(\PDO::FETCH_ASSOC);
                if (count($rows) > 100) {
                    return ['pbx_evidence' => 'ambiguous'];
                }
                $matching = array_filter($rows, static function (array $row) use ($recording): bool {
                    return $recording !== '' && basename((string) $row['recordingfile']) === $recording;
                });
                if (!$matching) {
                    $matching = array_filter($rows, static function (array $row) use ($uniqueId): bool {
                        return $row['uniqueid'] === $uniqueId;
                    });
                }
                $evidence = self::fromRows($matching, $direction);
                if ($evidence) {
                    return $evidence;
                }
                if ($attempt < 2) {
                    usleep(250000);
                }
            }
        } catch (\Throwable $exc) {
            return [];
        }
        return [];
    }
}
