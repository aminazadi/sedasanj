<?php
/* The adapter changes generated objects only; installed core files remain intact. */
class SedaSanjDialplan
{
    public static function apply($ext, $enabled, $monitorDir) {
        if (!$enabled) { return true; }
        $targets = array();
        if (!isset($ext->_exts['sub-record-check'])) { return false; }
        foreach (array('s', 'record', 'recq') as $extension) {
            $commands = isset($ext->_exts['sub-record-check'][' ' . $extension . ' ']) ? $ext->_exts['sub-record-check'][' ' . $extension . ' '] : array();
            $count = 0;
            foreach ($commands as $priority => $entry) {
                if (!isset($entry['cmd']) || !is_object($entry['cmd']) || get_class($entry['cmd']) !== 'ext_mixmonitor') { continue; }
                $command = $entry['cmd'];
                $vars = get_object_vars($command);
                if (!isset($vars['file'], $vars['options'], $vars['postcommand'])) { return false; }
                $parts = array($vars['file'], $vars['options'], $vars['postcommand']);
                if (count($parts) !== 3 || $parts[2] !== '${MIXMON_POST}' || !in_array($parts[0], array('${MIXMON_DIR}${YEAR}/${MONTH}/${DAY}/${CALLFILENAME}.${MIXMON_FORMAT}', '${MONITOR_FILENAME}.${MIXMON_FORMAT}'), true)) { return false; }
                $targets[] = array($extension, $priority, $parts); $count++;
            }
            if ($count !== 1) { return false; }
        }
        if (!preg_match('~^/[A-Za-z0-9_./-]+$~', $monitorDir)) { return false; }
        foreach ($targets as $target) {
            list($extension, $priority, $parts) = $target;
            $base = rtrim($monitorDir, '/') . '/${YEAR}/${MONTH}/${DAY}/';
            $options = $parts[1] . 'r(' . $base . 'recv_${CALLFILENAME}.wav)t(' . $base . 'trans_${CALLFILENAME}.wav)';
            $post = '/usr/local/sbin/sedasanj-recording-hook "' . rtrim($monitorDir, '/') . '/${YEAR}/${MONTH}/${DAY}/" "${FILTER(0-9A-Za-z*#+_.\\x2d,${CALLFILENAME})}" "${FILTER(0-9.,${UNIQUEID})}" "${FILTER(0-9A-Za-z*#+_.\\x2d,${CALLERID(num)})}" "${FILTER(0-9A-Za-z*#+_.\\x2d,${CDR(dnid)})}" "${FILTER(0-9.,${CDR(duration)})}" "${FILTER(0-9A-Za-z*#+_.\\x2d,${CDR(dst)})}" "${FILTER(0-9A-Za-z*#+_.\\x2d,${FROM_DID})}"';
            $ext->replace('sub-record-check', $extension, $priority, new ext_mixmonitor($parts[0], $options, $post));
        }
        return true;
    }
}
