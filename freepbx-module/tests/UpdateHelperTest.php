<?php
// The root update helper's embedded verifier: signature, signed manifest, expiry, version/digest/size
// binding, key rotation and the downgrade check. The PHP library is extracted from the shell script.
if (!function_exists('sodium_crypto_sign_keypair')) { echo "sodium missing; skipped\n"; exit(0); }
$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };

$script = file_get_contents(__DIR__ . '/../bin/sedasanj-recuploader-update.sh');
if (!preg_match("/<<'PHP'\n(.*?)\nPHP\n/s", $script, $m)) { $fail('embedded PHP library not found'); }
$dir = sys_get_temp_dir() . '/aru-helper-' . getmypid();
@mkdir($dir);
file_put_contents("$dir/lib.php", $m[1]);

$pair = sodium_crypto_sign_keypair();
$secret = sodium_crypto_sign_secretkey($pair);
$public = sodium_crypto_sign_publickey($pair);
$other = sodium_crypto_sign_publickey(sodium_crypto_sign_keypair());
file_put_contents("$dir/release.zip", str_repeat('Z', 4096));
$sha = hash_file('sha256', "$dir/release.zip");
$sign = function (string $data) use ($secret) { return base64_encode(sodium_crypto_sign_detached($data, $secret)); };
$manifest = function (array $over = []) use ($sha) {
	return json_encode($over + ['product' => 'freepbx-recuploader', 'rawname' => 'recuploader', 'version' => '1.4.1', 'sha256' => $sha,
		'size' => 4096, 'channel' => 'stable', 'min_freepbx_major' => 15, 'min_from_version' => null,
		'issued_at' => gmdate('Y-m-d\TH:i:s\Z', time() - 60), 'expires_at' => gmdate('Y-m-d\TH:i:s\Z', time() + 86400)], JSON_UNESCAPED_SLASHES);
};
$verify = function (string $mf, ?string $mfSig = null, string $keys = null, string $version = '1.4.1', ?string $zipSig = null) use ($dir, $sha, $sign, $public, $manifest) {
	file_put_contents("$dir/pub", ($keys ?? base64_encode($public)) . "\n");
	$cmd = escapeshellarg(PHP_BINARY) . " $dir/lib.php verify $dir/release.zip $sha " . escapeshellarg($zipSig ?? $sign($sha)) . " $dir/pub "
		. escapeshellarg($mf) . ' ' . escapeshellarg($mfSig ?? $sign("sedasanj-module-manifest-v1\n" . $mf)) . ' ' . escapeshellarg($version) . ' 2>&1';
	exec($cmd, $out, $code);
	return [$code, implode("\n", $out)];
};

[$c, $o] = $verify($manifest());
if ($c !== 0) { $fail("valid release rejected: $o"); }
[$c] = $verify($manifest(['version' => '1.4.0']));
if ($c === 0) { $fail('manifest for another version accepted (replay of an older release)'); }
[$c] = $verify($manifest(['sha256' => str_repeat('0', 64)]));
if ($c === 0) { $fail('manifest digest mismatch accepted'); }
[$c] = $verify($manifest(['size' => 1]));
if ($c === 0) { $fail('manifest size mismatch accepted'); }
[$c, $o] = $verify($manifest(['expires_at' => gmdate('Y-m-d\TH:i:s\Z', time() - 10)]));
if ($c === 0 || strpos($o, 'expired') === false) { $fail("expired manifest accepted: $o"); }
[$c] = $verify($manifest(['issued_at' => gmdate('Y-m-d\TH:i:s\Z', time() + 7200)]));
if ($c === 0) { $fail('manifest from the future accepted'); }
[$c] = $verify($manifest(['rawname' => 'other']));
if ($c === 0) { $fail('manifest for another module accepted'); }
[$c] = $verify($manifest(), $sign($manifest()));  // signature without the domain prefix
if ($c === 0) { $fail('manifest signature without domain separation accepted'); }
[$c] = $verify($manifest(), null, null, '1.4.1', $sign(str_repeat('f', 64)));
if ($c === 0) { $fail('bad zip signature accepted'); }
[$c] = $verify($manifest(), null, base64_encode($other));
if ($c === 0) { $fail('signature by an untrusted key accepted'); }
// Rotation: both the old (other) and the real key may be listed together.
[$c, $o] = $verify($manifest(), null, base64_encode($other) . "\n" . base64_encode($public));
if ($c !== 0) { $fail("rotation with two keys rejected: $o"); }
[$c] = $verify($manifest(), null, "REPLACE_WITH_BASE64_ED25519_PUBLIC_KEY");
if ($c === 0) { $fail('placeholder key accepted'); }

// Downgrade/replay: only strictly newer versions pass.
$newer = function (string $a, string $b) use ($dir) { exec(escapeshellarg(PHP_BINARY) . " $dir/lib.php newer $a $b", $o, $code); return $code === 0; };
if (!$newer('1.4.1', '1.4.0') || $newer('1.4.0', '1.4.0') || $newer('1.3.9', '1.4.0') || !$newer('1.10.0', '1.9.9')) { $fail('version comparison'); }

// job.json validation requires the manifest fields.
$job = ['release_id' => 'r1', 'version' => '1.4.1', 'from_version' => '1.4.0', 'sha256' => $sha, 'signature' => $sign($sha),
	'host_uuid' => '123e4567-e89b-12d3-a456-426614174000', 'manifest' => $manifest(), 'manifest_signature' => $sign("sedasanj-module-manifest-v1\n" . $manifest())];
file_put_contents("$dir/job.json", json_encode($job));
exec(escapeshellarg(PHP_BINARY) . " $dir/lib.php job $dir/job.json 2>&1", $out, $code);
if ($code !== 0 || count($out) !== 8) { $fail('valid job rejected: ' . implode("\n", $out)); }
unset($job['manifest']);
file_put_contents("$dir/job.json", json_encode($job));
exec(escapeshellarg(PHP_BINARY) . " $dir/lib.php job $dir/job.json 2>&1", $out2, $code);
if ($code === 0) { $fail('job without a manifest accepted'); }

exec('rm -rf ' . escapeshellarg($dir));
echo "Update helper verification passed.\n";
