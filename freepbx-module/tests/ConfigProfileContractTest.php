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

$ini = tempnam(sys_get_temp_dir(), 'sj-config-');
$voicemailSpool = '/var/spool/asterisk/voicemail';
$voicemailFolders = 'INBOX,Old,Urgent';
file_put_contents($ini, "[voicemail]\nspool_dir=\"\"\nspool_dir_b64=\"" . base64_encode($voicemailSpool)
    . "\"\nfolders=\"\"\nfolders_b64=\"" . base64_encode($voicemailFolders) . "\"\n");
$runtime = Engine\Config::load($ini);
unlink($ini);
if ($runtime['voicemail']['spool_dir'] !== $voicemailSpool
    || $runtime['voicemail']['folders'] !== $voicemailFolders) {
    throw new RuntimeException('Base64 voicemail settings did not survive parse-back.');
}

echo "FreePBX configuration contract passed.\n";
