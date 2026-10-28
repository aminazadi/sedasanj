<?php
require __DIR__ . '/../engine/autoload.php';

$fixture = file_get_contents(__DIR__ . '/fixtures/freepbx-config.v1.json');
$settings = Engine\ConfigProfile::parse($fixture);
if (($settings['missed_calls_enabled'] ?? null) !== '0' || ($settings['missed_calls_poll_interval_seconds'] ?? null) !== '30') {
    throw new RuntimeException('Missed-call fixture settings were not parsed correctly.');
}

$legacy = json_decode($fixture, true);
unset($legacy['settings']['missed_calls']);
$legacySettings = Engine\ConfigProfile::parse(json_encode($legacy));
if (($legacySettings['missed_calls_enabled'] ?? null) !== '0') {
    throw new RuntimeException('Configuration without missed_calls did not receive the disabled default.');
}

echo "FreePBX configuration contract passed.\n";
