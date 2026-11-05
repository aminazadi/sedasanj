<?php

require __DIR__ . '/../engine/src/CallPartyEvidence.php';

use Engine\CallPartyEvidence;

$answered = [
    'disposition' => 'ANSWERED',
    'channel' => 'PJSIP/provider-000001ab',
    'dstchannel' => 'PJSIP/0101-000001ac',
];
$anotherAgent = array_replace($answered, ['dstchannel' => 'PJSIP/102-000001ad']);
$noAnswer = array_replace($anotherAgent, ['disposition' => 'NO ANSWER']);
if (CallPartyEvidence::fromRows([$answered, $noAnswer], 'inbound') !== [
    'pbx_evidence' => 'cdr', 'dialed_extension' => '0101', 'agent_extension' => '0101',
]) {
    throw new RuntimeException('An unanswered ring group member displaced the answering endpoint');
}
if (CallPartyEvidence::fromRows([$answered, $anotherAgent], 'inbound') !== [
    'pbx_evidence' => 'ambiguous',
]) {
    throw new RuntimeException('A transfer with two plausible answerers was resolved arbitrarily');
}
$outbound = array_replace($answered, ['channel' => 'SIP/0101-000001ab', 'dstchannel' => 'PJSIP/provider-000001ac']);
if ((CallPartyEvidence::fromRows([$outbound], 'outbound')['caller_extension'] ?? null) !== '0101') {
    throw new RuntimeException('Outbound attribution did not use the originating channel');
}
$internal = array_replace($answered, ['channel' => 'PJSIP/102-000001ab']);
$parties = CallPartyEvidence::fromRows([$internal], 'internal');
if (($parties['caller_extension'] ?? null) !== '102' || ($parties['dialed_extension'] ?? null) !== '0101') {
    throw new RuntimeException('An internal recording must retain both endpoints');
}
echo "Call party evidence passed.\n";
