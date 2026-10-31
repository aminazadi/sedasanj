<?php
/* Fixed-command, bounded IPC for the legacy web PHP and PBX bridge. */
class SedaSanjProcess
{
    public static function run($arguments, $input, $timeout) {
        $parts = array();
        foreach ($arguments as $argument) { $parts[] = escapeshellarg($argument); }
        $process = proc_open('exec ' . implode(' ', $parts), array(0 => array('pipe', 'r'), 1 => array('pipe', 'w'), 2 => array('file', '/dev/null', 'a')), $pipes);
        if (!is_resource($process)) { throw new Exception('SS-SYS-1011'); }
        stream_set_blocking($pipes[0], false);
        stream_set_blocking($pipes[1], false);
        $start = microtime(true); $output = ''; $offset = 0; $stdinOpen = true; $exit = -1;
        while (true) {
            if ($stdinOpen) {
                $written = fwrite($pipes[0], substr($input, $offset, 8192));
                if ($written !== false) { $offset += $written; }
                if ($offset >= strlen($input)) { fclose($pipes[0]); $stdinOpen = false; }
            }
            $output .= stream_get_contents($pipes[1]);
            $status = proc_get_status($process);
            if (strlen($output) > 1048576 || microtime(true) - $start > $timeout) {
                proc_terminate($process, 9); fclose($pipes[1]);
                if ($stdinOpen) { fclose($pipes[0]); }
                proc_close($process); throw new Exception('SS-SYS-1011');
            }
            if (!$status['running']) { $exit = $status['exitcode']; break; }
            usleep(10000);
        }
        $output .= stream_get_contents($pipes[1]); fclose($pipes[1]);
        if ($stdinOpen) { fclose($pipes[0]); }
        proc_close($process);
        if ($exit !== 0) { throw new Exception('SS-SYS-1011'); }
        return $output;
    }
}
