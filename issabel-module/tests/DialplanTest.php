<?php
require __DIR__ . '/fixtures/ext_mixmonitor.php';
require __DIR__ . '/../lib/Dialplan.php';
function sj_assert($condition, $message) { if (!$condition) { throw new Exception($message); } }
class TestExtensions {
    public $_exts = array();
    public function add($context, $extension, $tag, $command) { $this->_exts[$context][' ' . $extension . ' '][] = array('tag' => $tag, 'cmd' => $command); }
    public function replace($context, $extension, $priority, $command) { $this->_exts[$context][' ' . $extension . ' '][$priority]['cmd'] = $command; }
}
foreach (array('4', '5') as $version) {
    $ext = new TestExtensions(); require __DIR__ . '/fixtures/issabel' . $version . '-recording.php';
    $before = serialize($ext);
    sj_assert(SedaSanjDialplan::apply($ext, false, '/var/spool/asterisk/monitor'), 'Disabled adapter must succeed');
    sj_assert(serialize($ext) === $before, 'Disabled adapter must not change the PBX');
    sj_assert(SedaSanjDialplan::apply($ext, true, '/var/spool/asterisk/monitor'), 'Official fixture must be recognised');
    foreach ($ext->_exts['sub-record-check'] as $commands) {
        $command = $commands[0]['cmd'];
        sj_assert(strpos($command->options, 'r(') !== false && strpos($command->options, 't(') !== false, 'Stereo legs required');
        sj_assert(strpos($command->postcommand, 'FILTER(') !== false, 'Caller input must be filtered');
        sj_assert(strpos($command->postcommand, 'sedasanj-recording-hook') !== false, 'Use the installed runtime launcher');
    }
    $ext = new TestExtensions(); require __DIR__ . '/fixtures/issabel' . $version . '-recording.php';
    $ext->_exts['sub-record-check'][' recq '][0]['cmd']->postcommand = 'custom-hook';
    $before = serialize($ext);
    sj_assert(!SedaSanjDialplan::apply($ext, true, '/var/spool/asterisk/monitor'), 'Unknown post command must fail closed');
    sj_assert(serialize($ext) === $before, 'All target checks must happen before any mutation');
}
echo "Issabel dialplan fixtures passed\n";
