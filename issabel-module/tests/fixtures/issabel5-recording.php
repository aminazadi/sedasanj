<?php
// Source: https://github.com/IssabelFoundation/issabelPBX/blob/0f77edaade296e929f2159f3165ceecc7f74b267/core/functions.inc.php
// GPLv3+; Copyright Schmooze Com Inc. and Issabel Foundation.
$context = 'sub-record-check';
$exten = 's';
$ext->add($context, $exten, '', new ext_mixmonitor('${MIXMON_DIR}${YEAR}/${MONTH}/${DAY}/${CALLFILENAME}.${MIXMON_FORMAT}','a','${MIXMON_POST}'));
$exten = 'record';
$ext->add($context, $exten, '', new ext_mixmonitor('${MIXMON_DIR}${YEAR}/${MONTH}/${DAY}/${CALLFILENAME}.${MIXMON_FORMAT}','','${MIXMON_POST}'));
$exten = 'recq';
$ext->add($context, $exten, '', new ext_mixmonitor('${MONITOR_FILENAME}.${MIXMON_FORMAT}','${MONITOR_OPTIONS}','${MIXMON_POST}'));
