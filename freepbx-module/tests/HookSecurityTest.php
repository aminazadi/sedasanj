<?php
// Contract tests for the 1.3.9 security hotfix. Run: php tests/HookSecurityTest.php

$root = dirname(__DIR__);
$fail = function ($message) {
	fwrite(STDERR, "FAIL: {$message}\n");
	exit(1);
};

// 1. Every caller-controlled dialplan value must be wrapped in FILTER().
$conf = file_get_contents($root . '/dialplan/globals-custom-mixmon.conf');
$post = '';
foreach (explode("\n", $conf) as $line) {
	if (strpos($line, 'MIXMON_POST=') === 0) {
		$post = $line;
	}
}
if ($post === '') {
	$fail('MIXMON_POST line not found');
}
foreach (array('CALLFILENAME', 'UNIQUEID', 'CALLERID(num)', 'CDR(dnid)', 'CDR(duration)', 'CDR(dst)', 'FROM_DID') as $variable) {
	$wrapped = '{FILTER(';
	$needle = '${SS}{' . $variable . '}';
	$count = substr_count($post, $needle);
	$inFilter = preg_match_all('/\{FILTER\([^,]+,\$\{SS\}\{' . preg_quote($variable, '/') . '\}\)\}/', $post);
	if ($count !== 1 || $inFilter !== 1) {
		$fail("{$variable} must appear exactly once, inside FILTER()");
	}
}

// 2. The PHP module must install that same file (single source of truth).
$class = file_get_contents($root . '/Recuploader.class.php');
if (strpos($class, "dialplan/globals-custom-mixmon.conf") === false || strpos($class, 'CALLERID(num)') !== false) {
	$fail('Recuploader::injectMixmonGlobals must read the shipped dialplan file, not embed its own block');
}

// 3. CSRF: POST + token for save, import and update start.
foreach (array('csrfValid', 'hash_equals', "'sj_csrf'", 'HTTP_X_SJ_CSRF') as $marker) {
	if (strpos($class, $marker) === false) {
		$fail("missing CSRF marker {$marker}");
	}
}
$page = file_get_contents($root . '/page.recuploader.php');
if (strpos($page, 'name="sj_csrf"') === false || strpos($page, 'X-SJ-CSRF') === false) {
	$fail('page.recuploader.php must send the CSRF token with the form and with AJAX calls');
}

// 4. mix-stereo.php rejects shell metacharacters before touching any file.
$php = PHP_BINARY;
$cases = array(
	array('/tmp/', 'in-100-$(touch /tmp/pwned)-1.1', '1.1', '100', '100', '', '', ''),
	array('/tmp/', 'in-100-200-1.1', '1.1', '`id`', '100', '', '', ''),
	array('/tmp/../etc/', 'in-100-200-1.1', '1.1', '100', '100', '', '', ''),
	array('/tmp/', 'in-100-200-1.1', '1.1;id', '100', '100', '', '', ''),
);
foreach ($cases as $args) {
	$command = escapeshellarg($php) . ' ' . escapeshellarg($root . '/engine/bin/mix-stereo.php');
	foreach ($args as $arg) {
		$command .= ' ' . escapeshellarg($arg);
	}
	$output = array();
	$status = 0;
	exec($command . ' 2>&1', $output, $status);
	if ($status !== 1 || strpos(implode("\n", $output), 'rejected unsafe') === false) {
		$fail('mix-stereo.php accepted unsafe arguments: ' . json_encode($args));
	}
}
if (file_exists('/tmp/pwned')) {
	$fail('injection side effect observed');
}

echo "Hook security contract passed.\n";
