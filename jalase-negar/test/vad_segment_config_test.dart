import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/vad_segment_engine.dart';
import 'package:jalase_negar/core/models/model_spec.dart';

VadSegmentConfig _config({int? speakerThreads}) => speakerThreads == null
    ? const VadSegmentConfig(
        vadModelPath: 'vad.onnx',
        tokensPath: 'tokens.txt',
        architecture: AsrArchitecture.transducer,
      )
    : VadSegmentConfig(
        vadModelPath: 'vad.onnx',
        tokensPath: 'tokens.txt',
        architecture: AsrArchitecture.transducer,
        speakerThreads: speakerThreads,
      );

void main() {
  test('thread defaults stay as they were until a phone confirms a change', () {
    // Thread counts depend on the phone's cores, heat and memory. The
    // benchmark Mac showed two speaker threads are faster with identical text
    // and labels on two single-speaker clips, but that has not been tried on a
    // phone, so the default is the single thread the app always used.
    final config = _config();
    expect(config.numThreads, 2);
    expect(config.speakerThreads, 1);
  });

  test('the speaker-model thread count can be raised for a benchmark', () {
    expect(_config(speakerThreads: 2).speakerThreads, 2);
  });
}
