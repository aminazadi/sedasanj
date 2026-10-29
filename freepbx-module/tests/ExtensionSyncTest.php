<?php
require __DIR__ . '/../engine/autoload.php';

use Engine\ErrorCatalog;
use Engine\ExtensionSync;
use Engine\ModuleUpdate;

function check($condition, $message) {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

check(
    ModuleUpdate::extensionsSyncUrl('https://api.sedasanj.ir/v1/ingest/calls') === 'https://api.sedasanj.ir/v1/ingest/extensions/sync',
    'extensions sync URL'
);

$payload = ExtensionSync::buildPayload(array(
    array('102', 'Sara', 'novm'),
    array('extension' => '101', 'name' => "  Ali\n  Rezaei "),
    array('101', 'duplicate wins last'),
    array('abc', 'bad'),
    array('*97', 'feature code'),
    array('', 'empty'),
    'not-an-array',
    array('2001'),
));
$exts = array_map(function ($i) { return $i['extension']; }, $payload['extensions']);
check($exts === array('101', '102', '2001'), 'sorted, deduplicated, digits only: ' . implode(',', $exts));
check($payload['extensions'][0]['name'] === 'duplicate wins last', 'last duplicate wins');
check($payload['extensions'][2]['name'] === '', 'missing name becomes empty');
check(ExtensionSync::buildPayload(array()) === array('extensions' => array()), 'empty list');

$long = ExtensionSync::buildPayload(array(array('101', str_repeat('a', 500))));
check(strlen($long['extensions'][0]['name']) === 200, 'name truncated to 200');

foreach (array('SS-EXT-1001', 'SS-EXT-1002', 'SS-EXT-1003') as $code) {
    check(isset(ErrorCatalog::ENTRIES[$code]), "$code in catalog");
}
echo "ExtensionSyncTest OK\n";
