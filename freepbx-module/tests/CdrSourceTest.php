<?php
require __DIR__ . '/../engine/autoload.php';

function assertCdr($condition, $message) {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

$dir = sys_get_temp_dir() . '/sj-cdr-test-' . bin2hex(random_bytes(4));
mkdir($dir);
file_put_contents(
    $dir . '/cdr.conf',
    "[general]\n#include cdr_general_additional.conf\n#include \"cdr_general_custom.conf\"\n"
);
file_put_contents($dir . '/cdr_general_additional.conf', "unanswered=no\ncongestion=no\n");
file_put_contents($dir . '/cdr_general_custom.conf', "unanswered=yes\ncongestion=yes\n");

$settings = Engine\CdrSource::cdrSettings($dir . '/cdr.conf');
assertCdr(($settings['unanswered'] ?? null) === 'yes', 'custom unanswered setting');
assertCdr(($settings['congestion'] ?? null) === 'yes', 'custom congestion setting');

file_put_contents($dir . '/cdr.conf', "[general]\n#include unsupported-syntax\n");
$settings = Engine\CdrSource::cdrSettings($dir . '/cdr.conf');
assertCdr(($settings['unanswered'] ?? null) === 'yes', 'direct FreePBX custom fallback');
assertCdr(($settings['congestion'] ?? null) === 'yes', 'direct FreePBX congestion fallback');

unlink($dir . '/cdr_general_custom.conf');
file_put_contents($dir . '/recursive.conf', "#include recursive.conf\nunanswered=yes\n");
file_put_contents($dir . '/cdr.conf', "[general]\n#tryinclude missing.conf\n#include recursive.conf\n");
$settings = Engine\CdrSource::cdrSettings($dir . '/cdr.conf');
assertCdr(($settings['unanswered'] ?? null) === 'yes', 'recursive include guard');

array_map('unlink', glob($dir . '/*'));
rmdir($dir);

echo "CDR settings verification passed.\n";
