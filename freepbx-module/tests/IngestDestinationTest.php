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
require __DIR__ . '/../engine/src/IngestMapper.php';
$metadata = [
    'uniqueid' => '1793426858.840', 'src' => '1001', 'dst' => 'recordcheck',
    'source_filename' => 'stereo_ins1001202610310937381793426858.840.wav',
];
$form = IngestMapper::toIngestForm($metadata);
if ($form['dialed_number'] !== '219' || $form['agent_extension'] !== '219' || $form['direction'] !== 'inbound') {
    throw new \RuntimeException('Legacy inbound job did not recover the answered destination');
}
$metadata['dst'] = '1002';
if (IngestMapper::toIngestForm($metadata)['dialed_number'] !== '1002') {
    throw new \RuntimeException('A valid destination was overwritten');
}
$metadata['dst'] = 'recordcheck';
$metadata['source_filename'] = 'stereo_out1001202610310937381793426858.840.wav';
if (isset(IngestMapper::toIngestForm($metadata)['agent_extension'])) {
    throw new \RuntimeException('Outbound destination was inferred from an inbound channel');
}
echo "Ingest destination recovery passed.\n";
