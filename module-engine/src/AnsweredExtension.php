<?php

namespace Engine;

class AnsweredExtension
{
    public static function fromCdrRows(array $rows): ?string
    {
        $extensions = [];
        foreach ($rows as $row) {
            if (strtoupper((string) ($row['disposition'] ?? '')) !== 'ANSWERED') {
                continue;
            }
            $channel = (string) ($row['dstchannel'] ?? '');
            if (preg_match('~^(?:PJSIP|SIP)/([0-9]{2,8})-[A-Za-z0-9]+$~i', $channel, $match) !== 1) {
                continue;
            }
            $extensions[$match[1]] = true;
        }
        return count($extensions) === 1 ? (string) array_key_first($extensions) : null;
    }

    public static function lookup(string $uniqueId): ?string
    {
        if ($uniqueId === '') {
            return null;
        }
        try {
            [$cdrDb, $table] = \Engine\Host\Factory::create()->cdr();
            if (preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $table) !== 1) {
                return null;
            }
            $stmt = $cdrDb->prepare(
                'SELECT disposition, dstchannel FROM `' . $table . '` WHERE uniqueid = :uniqueid LIMIT 50'
            );
            $stmt->execute(['uniqueid' => $uniqueId]);
            return self::fromCdrRows($stmt->fetchAll(\PDO::FETCH_ASSOC));
        } catch (\Throwable $exc) {
            return null;
        }
    }
}
