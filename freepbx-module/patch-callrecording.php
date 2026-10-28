#!/usr/bin/env php
<?php

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "CLI only\n");
    exit(2);
}

$action = $argv[1] ?? '';
$path = $argv[2] ?? '/var/www/html/admin/modules/callrecording/functions.inc.php';
$major = isset($argv[3]) ? (int) $argv[3] : 0;
$stateDir = $argv[4] ?? '/var/lib/asterisk-recording-uploader';
$statePath = rtrim($stateDir, '/') . '/core-patch.json';
$backupPath = rtrim($stateDir, '/') . '/callrecording.functions.inc.php.backup';

$fixtures = [
    [
        'name' => 'main_mixmonitor',
        'before' => '\'a${MONITOR_REC_OPTION}i(${LOCAL_MIXMON_ID})${MIXMON_BEEP}\',\'${MIXMON_POST}\'',
        'before_hash' => '6cd5d1e2582bc6ca7f6534a38427568b10bcc411ed50f35167f07c4666bab72f',
        'after' => '\'a${EVAL(${MONITOR_REC_OPTION})}i(${LOCAL_MIXMON_ID})${MIXMON_BEEP}\',\'${EVAL(${MIXMON_POST})}\'',
        'after_hash' => '6f272e32b646bf30dd6403fe498ee3e4c77a7778f5f0cf223fe3af35f108bdb7',
    ],
    [
        'name' => 'manual_mixmonitor',
        'before' => '\'ai(LOCAL_MIXMON_ID)${MIXMON_BEEP}\',\'${EVAL(${MIXMON_POST})}\'',
        'before_hash' => '556c52dfe13c53d120830cecfc2b6795b63ada228b44324ef5b0682be331b94d',
        'after' => '\'a${EVAL(${MONITOR_REC_OPTION})}i(LOCAL_MIXMON_ID)${MIXMON_BEEP}\',\'${EVAL(${MIXMON_POST})}\'',
        'after_hash' => '855e571c134d5223950dbcd197d0f1a80c0660032afa23d1b4705f29a04066ba',
    ],
];

function atomicReplace(string $path, string $content, int $mode): void
{
    $temporary = tempnam(dirname($path), '.recuploader-core-');
    if ($temporary === false || file_put_contents($temporary, $content, LOCK_EX) === false) {
        throw new RuntimeException('Could not write a temporary core patch file');
    }
    chmod($temporary, $mode);
    if (!rename($temporary, $path)) {
        @unlink($temporary);
        throw new RuntimeException('Could not atomically replace the core file');
    }
}

try {
    if ($action === 'apply' || $action === 'verify') {
        if (!in_array($major, [16, 17], true)) {
            throw new RuntimeException("Unsupported FreePBX major version: {$major}");
        }
        $content = @file_get_contents($path);
        if ($content === false) {
            throw new RuntimeException("Could not read {$path}");
        }
        $updated = $content;
        $beforeFixtures = 0;
        $afterFixtures = 0;
        foreach ($fixtures as $fixture) {
            if (!hash_equals($fixture['before_hash'], hash('sha256', $fixture['before']))
                || !hash_equals($fixture['after_hash'], hash('sha256', $fixture['after']))) {
                throw new RuntimeException("Fixture hash verification failed: {$fixture['name']}");
            }
            $beforeCount = substr_count($content, $fixture['before']);
            $afterCount = substr_count($content, $fixture['after']);
            if ($beforeCount === 1 && $afterCount === 0) {
                $beforeFixtures++;
            } elseif ($beforeCount === 0 && $afterCount === 1) {
                $afterFixtures++;
            } else {
                throw new RuntimeException("Unknown callrecording fixture: {$fixture['name']}");
            }
        }
        if ($beforeFixtures !== count($fixtures) && $afterFixtures !== count($fixtures)) {
            throw new RuntimeException('Callrecording fixtures are in a mixed or partially patched state');
        }
        if ($afterFixtures === count($fixtures)) {
            $state = json_decode((string) @file_get_contents($statePath), true);
            if (is_array($state)) {
                if (!hash_equals((string) ($state['patched_sha256'] ?? ''), hash('sha256', $content))) {
                    throw new RuntimeException('Callrecording patch state does not match the installed core file');
                }
                exit(0);
            }

            $verifiedLegacyBackup = null;
            foreach ([$backupPath, $path . '.orig'] as $candidatePath) {
                if (!is_file($candidatePath)) {
                    continue;
                }
                $candidate = @file_get_contents($candidatePath);
                if ($candidate === false) {
                    continue;
                }
                $candidatePatched = $candidate;
                $candidateValid = true;
                foreach ($fixtures as $fixture) {
                    if (substr_count($candidate, $fixture['before']) !== 1
                        || substr_count($candidate, $fixture['after']) !== 0) {
                        $candidateValid = false;
                        break;
                    }
                    $candidatePatched = str_replace($fixture['before'], $fixture['after'], $candidatePatched);
                }
                if ($candidateValid && hash_equals(hash('sha256', $content), hash('sha256', $candidatePatched))) {
                    $verifiedLegacyBackup = ['path' => $candidatePath, 'content' => $candidate];
                    break;
                }
            }
            if ($verifiedLegacyBackup === null) {
                throw new RuntimeException('Callrecording is already patched, but no verified legacy rollback backup was found');
            }
            if ($action === 'verify') {
                exit(0);
            }
            if (!is_dir($stateDir) && !mkdir($stateDir, 0750, true)) {
                throw new RuntimeException("Could not create {$stateDir}");
            }
            atomicReplace($backupPath, $verifiedLegacyBackup['content'], 0600);
            $state = [
                'path' => $path,
                'freepbx_major' => $major,
                'original_sha256' => hash('sha256', $verifiedLegacyBackup['content']),
                'patched_sha256' => hash('sha256', $content),
                'backup' => $backupPath,
                'patched_at' => gmdate('c'),
                'migrated_from' => $verifiedLegacyBackup['path'],
            ];
            $encodedState = json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
            if ($encodedState === false) {
                throw new RuntimeException('Could not encode migrated core patch state');
            }
            atomicReplace($statePath, $encodedState, 0600);
            exit(0);
        }
        foreach ($fixtures as $fixture) {
            $updated = str_replace($fixture['before'], $fixture['after'], $updated);
        }
        if ($action === 'verify') {
            exit(0);
        }
        if (!is_dir($stateDir) && !mkdir($stateDir, 0750, true)) {
            throw new RuntimeException("Could not create {$stateDir}");
        }
        if (file_put_contents($backupPath, $content, LOCK_EX) === false) {
            throw new RuntimeException('Could not create the core backup');
        }
        $mode = fileperms($path) & 0777;
        atomicReplace($path, $updated, $mode);
        $state = [
            'path' => $path,
            'freepbx_major' => $major,
            'original_sha256' => hash('sha256', $content),
            'patched_sha256' => hash('sha256', $updated),
            'backup' => $backupPath,
            'patched_at' => gmdate('c'),
        ];
        $encodedState = json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encodedState === false) {
            atomicReplace($path, $content, $mode);
            throw new RuntimeException('Could not encode patch state; the core file was restored');
        }
        try {
            atomicReplace($statePath, $encodedState, 0600);
        } catch (Throwable $exc) {
            atomicReplace($path, $content, $mode);
            throw new RuntimeException('Could not record patch state; the core file was restored', 0, $exc);
        }
        exit(0);
    }

    if ($action === 'restore') {
        $state = json_decode((string) @file_get_contents($statePath), true);
        if (!is_array($state) || !is_file($backupPath) || !is_file($path)) {
            exit(0);
        }
        $current = file_get_contents($path);
        $backup = file_get_contents($backupPath);
        if (!hash_equals((string) $state['patched_sha256'], hash('sha256', $current))
            || !hash_equals((string) $state['original_sha256'], hash('sha256', $backup))) {
            throw new RuntimeException('Core or backup hash changed; refusing unsafe restore');
        }
        atomicReplace($path, $backup, fileperms($path) & 0777);
        @unlink($statePath);
        @unlink($backupPath);
        exit(0);
    }

    throw new RuntimeException('Usage: patch-callrecording.php apply|restore [path] [major] [state-dir]');
} catch (Throwable $exc) {
    fwrite(STDERR, 'ERROR: ' . $exc->getMessage() . "\n");
    exit(2);
}
