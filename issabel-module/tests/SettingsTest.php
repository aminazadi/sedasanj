<?php
require __DIR__ . '/../engine/autoload.php';
use Engine\IssabelSettings;
$cfg = IssabelSettings::defaults();
$cfg['general']['api_key'] = 'sk_live_fixture';
$cfg['general']['archive_password'] = 'test"${value}';
$file = tempnam(sys_get_temp_dir(), 'sj-settings-');
try {
    IssabelSettings::write($cfg, $file);
    $loaded = Engine\Config::load($file);
    if ($loaded !== $cfg) { throw new Exception('Settings must survive INI roundtrip'); }
    $saved = IssabelSettings::validate(['general' => ['api_key' => '']], $cfg);
    if ($saved['general']['api_key'] !== 'sk_live_fixture') { throw new Exception('Blank secret must retain its value'); }
    foreach ([['general' => ['endpoint' => 'http://example.com/v1/ingest/calls']], ['watcher' => ['watch_dir' => '/etc']], ['queue' => ['max_retries' => -1]], ['evil' => ['key' => 'value']]] as $input) {
        try { IssabelSettings::validate($input, $cfg); throw new Exception('Invalid configuration was accepted'); }
        catch (RuntimeException $exception) { if (strpos($exception->getMessage(), 'SS-CFG-') !== 0) { throw $exception; } }
    }
    $adapter = new Engine\Host\Issabel(['extensions' => [['101', 'Test']]]);
    if ($adapter->extensions()[0][0] !== '101') { throw new Exception('Extension mapping changed'); }
    try { $adapter->cdr(); throw new Exception('Missing credentials accepted'); }
    catch (RuntimeException $exception) { if (strpos($exception->getMessage(), 'SS-CDR-1003') !== 0) { throw $exception; } }
} finally { unlink($file); }
echo "Issabel settings and adapter tests passed\n";
