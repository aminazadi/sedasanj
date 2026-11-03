import 'asr_common.dart';
import 'transcriber.dart';

/// Audio preparation applied by the on-device pipeline before decoding.
///
/// The server's identity is `preprocess:none` or
/// `denoise:<model>+enhance:<model>[@<target>LUFS/<gain>dB]`. The device does
/// not run that chain yet (contract phase 3), so it names what it really does
/// instead of pretending to match.
const String kDeviceQuietGainPreparation = 'device-quiet-gain-v1';
const String kServerParityPreparation = 'preprocess:none';

/// Identity of an on-device transcript, in the server's
/// `{model}|{preparation}` shape plus the segmentation used, so two transcripts
/// of one recording can be compared knowing how each was produced.
String buildAsrIdentity({
  required String modelId,
  required AsrSegmenter segmenter,
  bool denoiser = false,
  bool live = false,
}) {
  final preparation = segmenter == AsrSegmenter.serverEnergy
      ? kServerParityPreparation
      : '$kDeviceQuietGainPreparation${denoiser ? '+gtcrn' : ''}';
  final segmentation = switch (segmenter) {
    AsrSegmenter.silero => live ? kLiveSegmentation : 'silero-vad',
    AsrSegmenter.serverEnergy => 'server-energy-vad',
  };
  return '$modelId|$preparation|segmenter:$segmentation';
}
