<?php
require __DIR__ . '/../engine/autoload.php';

use Engine\ModuleUpdate;
use Engine\ModuleUpdateError;

function check($condition, $message) {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

function throws(callable $fn) {
    try {
        $fn();
    } catch (ModuleUpdateError $exc) {
        return $exc->getMessage();
    }
    return null;
}

// ---- URL derivation -------------------------------------------------------
$endpoint = 'https://api.sedasanj.ir/v1/ingest/calls';
check(ModuleUpdate::releasesUrl($endpoint) === 'https://api.sedasanj.ir/v1/ingest/module/releases', 'releases URL');
check(ModuleUpdate::releasesUrl($endpoint . '/') === 'https://api.sedasanj.ir/v1/ingest/module/releases', 'releases URL with trailing slash');
check(ModuleUpdate::reportUrl($endpoint) === 'https://api.sedasanj.ir/v1/ingest/module/update-report', 'report URL');
check(ModuleUpdate::downloadUrl($endpoint, 'a1b2-c3') === 'https://api.sedasanj.ir/v1/ingest/module/releases/a1b2-c3/download', 'download URL');
check(ModuleUpdate::updatesUrl($endpoint, array('current' => '1.3.0', 'hostname' => 'pbx one'))
    === 'https://api.sedasanj.ir/v1/ingest/module/updates?current=1.3.0&hostname=pbx%20one', 'updates URL query');
check(throws(function () { ModuleUpdate::releasesUrl('https://api.sedasanj.ir/v1/ingest/voicemails'); }) !== null, 'endpoint without /calls must be rejected');
check(throws(function () use ($endpoint) { ModuleUpdate::downloadUrl($endpoint, '../admin'); }) !== null, 'unsafe release id must be rejected');
check(ModuleUpdate::isJobId(str_repeat('ab', 16)) && !ModuleUpdate::isJobId('../' . str_repeat('a', 29)), 'job id validation');

// ---- Signing (same scheme as the API: base64 32-byte seed) ---------------
$seed = random_bytes(SODIUM_CRYPTO_SIGN_SEEDBYTES);
$keypair = sodium_crypto_sign_seed_keypair($seed);
$secret = sodium_crypto_sign_secretkey($keypair);
$public = sodium_crypto_sign_publickey($keypair);
$pubFile = "# comment line\n" . base64_encode($public) . "\n";
check(ModuleUpdate::parsePublicKey($pubFile) === $public, 'public key file parsing');
check(ModuleUpdate::parsePublicKey(file_get_contents(__DIR__ . '/../assets/release-signing.pub')) === null
    || strlen(ModuleUpdate::parsePublicKey(file_get_contents(__DIR__ . '/../assets/release-signing.pub'))) === 32, 'bundled key is a placeholder or a valid key');
check(ModuleUpdate::parsePublicKey("REPLACE_WITH_BASE64_ED25519_PUBLIC_KEY\n") === null, 'placeholder key must not parse');

$dir = sys_get_temp_dir() . '/sj-update-test-' . bin2hex(random_bytes(4));
mkdir($dir);
$zip = $dir . '/release.zip';
file_put_contents($zip, random_bytes(4096));
$sha = hash_file('sha256', $zip);
$signature = base64_encode(sodium_crypto_sign_detached($sha, $secret));
$release = array('sha256' => $sha, 'signature' => $signature, 'size' => 4096);

check(ModuleUpdate::verifySignature($sha, $signature, $public), 'valid signature');
check(!ModuleUpdate::verifySignature(hash('sha256', 'other'), $signature, $public), 'signature over another digest');
check(!ModuleUpdate::verifySignature($sha, $signature, sodium_crypto_sign_publickey(sodium_crypto_sign_keypair())), 'signature with another key');
check(!ModuleUpdate::verifySignature($sha, 'not base64!', $public), 'malformed signature');
check(throws(function () use ($zip, $release, $public) { ModuleUpdate::verifyArtifact($zip, $release, $public); }) === null, 'valid artifact');
check(throws(function () use ($zip, $release, $public) { ModuleUpdate::verifyArtifact($zip, array('size' => 1) + $release, $public); }) !== null, 'size mismatch');
file_put_contents($zip, 'tampered', FILE_APPEND);
check(throws(function () use ($zip, $release, $public) { ModuleUpdate::verifyArtifact($zip, array('size' => 0) + $release, $public); }) === 'Downloaded release checksum does not match', 'tampered artifact');

// ---- The root helper's own verifier (embedded lib.php) --------------------
$helper = file_get_contents(__DIR__ . '/../bin/sedasanj-recuploader-update.sh');
check(preg_match("/<<'PHP'\n(.*?)\nPHP\n/s", $helper, $m) === 1, 'helper embeds lib.php');
$lib = $dir . '/lib.php';
file_put_contents($lib, $m[1]);
file_put_contents($zip, random_bytes(2048));
$sha = hash_file('sha256', $zip);
$signature = base64_encode(sodium_crypto_sign_detached($sha, $secret));
file_put_contents($dir . '/release.pub', $pubFile);
$run = function (array $args) use ($lib) {
    $cmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($lib);
    foreach ($args as $arg) {
        $cmd .= ' ' . escapeshellarg($arg);
    }
    exec($cmd . ' 2>&1', $out, $status);
    return array($status, implode("\n", $out));
};
// Verification of the signed manifest, rotation and expiry is covered by UpdateHelperTest.php.
file_put_contents($dir . '/job.json', json_encode(array('release_id' => 'r1; rm -rf /', 'version' => '1.3.1')));
list($status) = $run(array('job', $dir . '/job.json'));
check($status !== 0, 'helper rejects unsafe job.json fields');

array_map('unlink', glob($dir . '/*'));
rmdir($dir);

echo "Module update verification passed.\n";
