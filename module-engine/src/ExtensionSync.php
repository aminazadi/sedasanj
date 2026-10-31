<?php

namespace Engine;

/**
 * Builds the payload for POST /v1/ingest/extensions/sync from the extension rows FreePBX
 * returns (core_users_list(): [extension, name, voicemail]). Host-agnostic so
 * tests/ExtensionSyncTest.php can run without FreePBX.
 */
class ExtensionSync
{
    const MAX_EXTENSIONS = 5000;

    /**
     * @param array $rows each row is [extension, name, ...] or ['extension' => .., 'name' => ..]
     * @return array{extensions: array<int, array{extension: string, name: string}>}
     */
    public static function buildPayload(array $rows): array
    {
        $seen = array();
        foreach ($rows as $row) {
            if (!is_array($row)) {
                continue;
            }
            $extension = trim((string) (isset($row['extension']) ? $row['extension'] : (isset($row[0]) ? $row[0] : '')));
            if (preg_match('/^[0-9]{1,8}$/', $extension) !== 1) {
                continue;
            }
            $name = trim((string) (isset($row['name']) ? $row['name'] : (isset($row[1]) ? $row[1] : '')));
            $name = trim(preg_replace('/[\x00-\x1f\x7f]+/', ' ', $name));
            $seen[$extension] = function_exists('mb_substr') ? mb_substr($name, 0, 200, 'UTF-8') : substr($name, 0, 200);
        }
        ksort($seen, SORT_NUMERIC);
        $items = array();
        foreach ($seen as $extension => $name) {
            $items[] = array('extension' => (string) $extension, 'name' => $name);
            if (count($items) >= self::MAX_EXTENSIONS) {
                break;
            }
        }
        return array('extensions' => $items);
    }
}
