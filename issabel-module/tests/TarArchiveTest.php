<?php
require __DIR__ . '/../engine/autoload.php';
function sj_tar($name, $body, $type = '0') {
    $header = str_pad($name, 100, "\0") . sprintf('%07o', 0644) . "\0" . str_repeat("0000000\0", 2)
        . sprintf('%011o', strlen($body)) . "\0" . "00000000000\0" . str_repeat(' ', 8) . $type
        . str_repeat("\0", 100) . "ustar\00000" . str_repeat("\0", 249);
    $header = str_pad(substr($header, 0, 512), 512, "\0");
    $sum = 0; for ($i = 0; $i < 512; $i++) { $sum += ord($header[$i]); }
    $header = substr_replace($header, sprintf('%06o', $sum) . "\0 ", 148, 8);
    return $header . $body . str_repeat("\0", (512 - strlen($body) % 512) % 512);
}
$base = sys_get_temp_dir() . '/sj-tar-' . bin2hex(random_bytes(8)); mkdir($base);
$good = sj_tar('recuploader/module.xml', '<module/>');
file_put_contents($base . '/good.tgz', gzencode($good . str_repeat("\0", 1024)));
Engine\TarArchive::extract($base . '/good.tgz', $base . '/good');
if (file_get_contents($base . '/good/recuploader/module.xml') !== '<module/>') { throw new Exception('Extraction failed'); }
foreach (['recuploader/../../etc/passwd', '/recuploader/a', 'other/file'] as $i => $path) {
    file_put_contents($base . '/bad.tgz', gzencode(sj_tar($path, 'bad') . $good));
    try { Engine\TarArchive::extract($base . '/bad.tgz', $base . '/bad-' . $i); throw new Exception('Unsafe path accepted'); }
    catch (RuntimeException $exception) { if ($exception->getMessage() !== 'SS-UPD-1010') { throw $exception; } }
}
foreach (['1','2','3','6','x'] as $type) {
    file_put_contents($base . '/bad.tgz', gzencode(sj_tar('recuploader/link', '', $type) . $good));
    try { Engine\TarArchive::extract($base . '/bad.tgz', $base . '/type-' . $type); throw new Exception('Unsafe type accepted'); }
    catch (RuntimeException $exception) { if ($exception->getMessage() !== 'SS-UPD-1010') { throw $exception; } }
}
echo "Strict tgz extraction passed\n";
