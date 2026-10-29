<?php
// patch-callrecording.php against the real callrecording functions.inc.php of FreePBX 15, 16 and 17:
// apply, idempotence, restore (byte-identical), and the "already patched upstream" state.
$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$helper = dirname(__DIR__) . '/patch-callrecording.php';
$run = function (string $action, string $file, int $major, string $state) use ($helper) {
	$cmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($helper) . ' ' . $action . ' ' . escapeshellarg($file) . ' ' . $major . ' ' . escapeshellarg($state) . ' 2>&1';
	exec($cmd, $out, $code);
	return [$code, implode("\n", $out)];
};
foreach ([15, 16, 17] as $major) {
	$dir = sys_get_temp_dir() . "/aru-patch-$major-" . getmypid();
	@mkdir("$dir/state", 0755, true);
	$file = "$dir/functions.inc.php";
	copy(__DIR__ . "/fixtures/callrecording-$major.functions.inc.php", $file);
	$original = file_get_contents($file);

	[$code, $out] = $run('status', $file, $major, "$dir/state");
	if ($code !== 0 || trim($out) !== 'unpatched') { $fail("$major status before patch: $out"); }
	[$code, $out] = $run('apply', $file, $major, "$dir/state");
	if ($code !== 0) { $fail("$major apply: $out"); }
	[$code, $out] = $run('status', $file, $major, "$dir/state");
	if (trim($out) !== 'patched') { $fail("$major status after patch: $out"); }
	$patched = file_get_contents($file);
	if ($patched === $original || substr_count($patched, '${EVAL(${MIXMON_POST})}') !== substr_count($original, '${EVAL(${MIXMON_POST})}') + 1) {
		$fail("$major: patched content unexpected");
	}
	[$code, $out] = $run('apply', $file, $major, "$dir/state");
	if ($code !== 0 || file_get_contents($file) !== $patched) { $fail("$major second apply not idempotent: $out"); }
	[$code, $out] = $run('restore', $file, $major, "$dir/state");
	if ($code !== 0 || file_get_contents($file) !== $original) { $fail("$major restore is not byte-identical: $out"); }

	// Upstream already ships the patched form (no state, no backup): must not abort, must not touch the file.
	file_put_contents($file, $patched);
	@unlink("$dir/state/core-patch.json");
	[$code, $out] = $run('apply', $file, $major, "$dir/state");
	if ($code !== 0 || file_get_contents($file) !== $patched) { $fail("$major already-patched-upstream: $out"); }
	[$code, $out] = $run('restore', $file, $major, "$dir/state");
	if ($code !== 0 || file_get_contents($file) !== $patched) { $fail("$major restore touched an upstream-patched file: $out"); }

	// An unknown core file is refused rather than guessed at.
	file_put_contents($file, "<?php // different\n");
	[, $out] = $run('status', $file, $major, "$dir/state");
	if (trim($out) !== 'unknown') { $fail("$major status of unknown file: $out"); }
	[$code] = $run('apply', $file, $major, "$dir/state");
	if ($code === 0) { $fail("$major unknown file accepted"); }
	exec('rm -rf ' . escapeshellarg($dir));
}
echo "callrecording patch passed on FreePBX 15, 16 and 17 sources.\n";
