<?php
// module.xml: parseable, versions agree everywhere, and every <depends> entry matches the syntax that
// FreePBX's module_functions::checkdepends() understands (verified against FreePBX 17 source).
$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = dirname(__DIR__);
$xml = simplexml_load_file($root . '/module.xml');
if ($xml === false) { $fail('module.xml does not parse'); }
if ((string) $xml->rawname !== 'recuploader') { $fail('rawname'); }
$version = (string) $xml->version;
if (!preg_match('/^\d+\.\d+\.\d+$/', $version)) { $fail("version '$version' must be x.y.z"); }
if (strpos((string) file_get_contents($root . '/changelog.md'), "## $version ") === false) { $fail('changelog.md has no entry for ' . $version); }
if (strpos((string) file_get_contents($root . '/README.md'), "Module $version") === false) { $fail('README title version'); }
if (strpos((string) $xml->changelog, "*$version*") === false) { $fail('inline <changelog> must start with the current version'); }
if (trim((string) $xml->changelog) === 'changelog.md') { $fail('<changelog> must be inline text, not a file name'); }

$op = '(lt|le|gt|ge|==|=|eq|!=|ne)';
foreach ($xml->depends->module as $m) {
	if (!preg_match('/^([a-z0-9_]+)(\s+' . $op . '?\s*(\d+(\.\d*[beta|alpha|rc|RC]*\d+)+))?$/i', trim((string) $m))) { $fail("bad <module> dependency '$m'"); }
}
foreach ($xml->depends->phpcomponent as $c) {
	if (!preg_match('/^[a-z0-9_]+$/i', trim((string) $c))) { $fail("bad <phpcomponent> '$c'"); }
}
if (!preg_match('/^' . $op . '?\s*\d+(\.[^.]+)*$/i', trim((string) $xml->depends->phpversion))) { $fail('bad <phpversion>'); }
foreach (['callrecording', 'cdr', 'core'] as $needed) {
	$found = false;
	foreach ($xml->depends->module as $m) { if (strpos(trim((string) $m), $needed) === 0) { $found = true; } }
	if (!$found) { $fail("missing <module>$needed</module> dependency"); }
}
$supported = array();
foreach ($xml->supported->version as $v) { $supported[] = (string) $v; }
if ($supported !== array('15.0', '16.0', '17.0')) { $fail('supported versions: ' . implode(',', $supported)); }
echo "module.xml passed.\n";
