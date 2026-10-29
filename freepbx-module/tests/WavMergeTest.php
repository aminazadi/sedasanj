<?php
ini_set('memory_limit', '256M'); // the hook runs with 768M; one hour of audio must fit far below that
// mergeStereo(): interleaving is sample-exact for unequal legs, and fast enough for long calls.
require __DIR__ . '/../engine/autoload.php';

use Engine\Audio\Wav;
use Engine\Audio\WavFile;

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$reference = function (WavFile $l, WavFile $r): string {
	$b = $l->bytesPerSample();
	$frames = max(intdiv(strlen($l->data), $b), intdiv(strlen($r->data), $b));
	$ld = str_pad($l->data, $frames * $b, "\x00");
	$rd = str_pad($r->data, $frames * $b, "\x00");
	$out = '';
	for ($i = 0; $i < $frames; $i++) { $out .= substr($ld, $i * $b, $b) . substr($rd, $i * $b, $b); }
	return $out;
};
mt_srand(7);
foreach ([[0, 0], [1, 5], [8192, 8192], [8193, 100], [20000, 20123], [3, 0]] as [$a, $b]) {
	$left = new WavFile(1, 8000, 16, ($a ? random_bytes($a * 2) : ''));
	$right = new WavFile(1, 8000, 16, ($b ? random_bytes($b * 2) : ''));
	if (Wav::mergeStereo($left, $right)->data !== $reference($left, $right)) { $fail("16-bit merge differs for $a/$b samples"); }
}
$l8 = new WavFile(1, 8000, 8, random_bytes(1000));
$r8 = new WavFile(1, 8000, 8, random_bytes(900));
if (Wav::mergeStereo($l8, $r8)->data !== $reference($l8, $r8)) { $fail('8-bit merge differs'); }

// The streaming writer produces byte-identical files to mergeStereo() + write().
$tmp = sys_get_temp_dir() . '/aru-wav-' . getmypid();
foreach ([[0, 0], [5, 9], [8193, 100], [30000, 29999]] as [$a, $b]) {
	$left = new WavFile(1, 8000, 16, $a ? random_bytes($a * 2) : '');
	$right = new WavFile(1, 8000, 16, $b ? random_bytes($b * 2) : '');
	Wav::write("$tmp.a", Wav::mergeStereo($left, $right));
	Wav::mergeStereoToFile($left, $right, "$tmp.b");
	if (file_get_contents("$tmp.a") !== file_get_contents("$tmp.b")) { $fail("streamed file differs for $a/$b"); }
	if (Wav::read("$tmp.b")->channels !== 2) { $fail('streamed file is not a readable stereo WAV'); }
}
@unlink("$tmp.a"); @unlink("$tmp.b");

// One hour at 8 kHz per leg must merge in a few seconds and a bounded amount of memory.
$hour = 8000 * 3600;
$left = new WavFile(1, 8000, 16, random_bytes($hour * 2));
$right = new WavFile(1, 8000, 16, random_bytes($hour * 2));
$t = microtime(true);
Wav::mergeStereoToFile($left, $right, "$tmp.hour");
$elapsed = microtime(true) - $t;
if (filesize("$tmp.hour") !== $hour * 4 + 44) { $fail('merged length'); }
@unlink("$tmp.hour");
if ($elapsed > 60) { $fail(sprintf('merging one hour took %.1fs', $elapsed)); }
fwrite(STDOUT, sprintf("one hour merged in %.1fs, peak memory %d MB\n", $elapsed, memory_get_peak_usage(true) / 1048576));
echo "Wav merge passed.\n";
