#!/usr/bin/env php
<?php
require __DIR__ . '/../autoload.php';
try {
    $host = json_decode((string) file_get_contents(\Engine\Host\Factory::CONFIG), true);
    exit(\Engine\IssabelRecording::process($argv, \Engine\Config::load(), $host));
} catch (\Throwable $exception) {
    fwrite(STDERR, "SS-HOOK-1011: Run the Issabel health checks; the original recording is preserved.\n");
    exit(1);
}
