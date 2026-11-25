<?php
namespace Engine;

// Isolate CDR access while exercising mapping of real legacy failed-job metadata.
class AnsweredExtension
{
    public static function lookup(string $uniqueId): ?string
    {
        return $uniqueId === '1793426858.840' ? '219' : null;
    }
}

class CallPartyEvidence
{
    public static function lookup(string $uniqueId, string $filename, string $direction, ?int $started): array
    {
        if ($uniqueId === '1793426858.900') {
            return [
                'pbx_evidence' => 'cdr',
                'caller_extension' => '0101',
                'dialed_extension' => '0203',
                'agent_extension' => '0203',
            ];
        }
        if ($uniqueId === '1793426858.901') {
            return ['pbx_evidence' => 'ambiguous'];
        }
        return [];
    }
}
require __DIR__ . '/../engine/src/IngestMapper.php';

$assert = function (bool $condition, string $message): void {
    if (!$condition) {
        throw new \RuntimeException($message);
    }
};

// A. Legacy inbound job: the dialplan label is replaced by the answered extension.
$metadata = [
    'uniqueid' => '1793426858.840', 'src' => '1001', 'dst' => 'recordcheck',
    'source_filename' => 'stereo_ins1001202610310937381793426858.840.wav',
];
$form = IngestMapper::toIngestForm($metadata);
$assert($form['dialed_number'] === '219', 'Legacy inbound job did not recover the answered destination');
$assert($form['agent_extension'] === '219', 'Legacy inbound job lost the answered extension');
$assert($form['direction'] === 'inbound', 'Legacy inbound job lost its direction');

// B. A numeric destination is never overwritten.
$metadata['dst'] = '1002';
$assert(IngestMapper::toIngestForm($metadata)['dialed_number'] === '1002', 'A valid destination was overwritten');

// C. An outbound label must not invent an inbound agent.
$metadata['dst'] = 'recordcheck';
$metadata['source_filename'] = 'stereo_out1001202610310937381793426858.840.wav';
$outbound = IngestMapper::toIngestForm($metadata);
$assert(!isset($outbound['agent_extension']), 'Outbound destination was inferred from an inbound channel');
$assert(!isset($outbound['dialed_number']), 'An outbound dialplan label was forwarded as a number');

// D. Extension-to-extension recordings keep both parties.
$internal = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.841', 'src' => '1001', 'dst' => '1002',
    'source_filename' => 'stereo_exten-1002-1001-20261031-093738-1793426858.841.wav',
]);
$assert(($internal['direction'] ?? '') === 'internal', 'Internal recording was not marked internal');
$assert($internal['dialed_number'] === '1002', 'Internal dialed extension was lost');
$assert($internal['caller_number'] === '1001', 'Internal caller extension was lost');

// E. A non-numeric label is resolved from CDR evidence, including the caller.
$fromCdr = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.900', 'src' => '09351234567', 'dst' => 'recordcheck',
    'direction' => 'inbound',
    'source_filename' => 'stereo_ins09351234567202611251200001793426858.900.wav',
]);
$assert($fromCdr['caller_number'] === '09351234567', 'The external caller number was replaced by an extension');
$assert($fromCdr['caller_extension'] === '0101', 'CDR caller extension was not used');
$assert($fromCdr['dialed_number'] === '0203', 'CDR dialed extension was not used');
$assert($fromCdr['agent_extension'] === '0203', 'CDR agent extension was not used');
$assert($fromCdr['pbx_evidence'] === 'cdr', 'CDR evidence was not labelled');

// F. Ambiguous CDR answers must not be guessed.
$ambiguous = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.901', 'src' => '09351234567', 'dst' => 'recordcheck',
    'direction' => 'inbound',
    'source_filename' => 'stereo_ins09351234567202611251200001793426858.901.wav',
]);
$assert(!isset($ambiguous['dialed_number']), 'An ambiguous CDR answer was guessed');
$assert($ambiguous['pbx_evidence'] === 'ambiguous', 'Ambiguity was not surfaced');

// G. Inbound calls fall back to the DID when the CDR has nothing.
$fromDid = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.902', 'src' => '09351234567', 'dst' => 'recordcheck',
    'from_did' => '02112345678', 'direction' => 'inbound',
    'source_filename' => 'stereo_ins09351234567202611251200001793426858.902.wav',
]);
$assert($fromDid['dialed_number'] === '02112345678', 'The inbound DID fallback was not used');
$assert($fromDid['pbx_evidence'] === 'direct', 'The DID fallback was not labelled direct');

// H. A non-numeric caller label is never forwarded as a phone number.
$labelCaller = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.903', 'src' => 'anonymous', 'dst' => '1002', 'direction' => 'inbound',
]);
$assert(!isset($labelCaller['caller_number']), 'A caller label was forwarded as a number');

// I. An unknown direction is dropped instead of being sent for a guaranteed 422.
$badDirection = IngestMapper::toIngestForm([
    'uniqueid' => '1793426858.904', 'src' => '1001', 'dst' => '1002', 'direction' => 'sideways',
]);
$assert(!isset($badDirection['direction']), 'An invalid direction was forwarded');

echo "Ingest destination recovery passed.\n";
