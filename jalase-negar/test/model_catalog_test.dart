import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/models/model_catalog.dart';
import 'package:jalase_negar/core/models/model_spec.dart';
import 'package:jalase_negar/core/utils/transcript_text.dart';

void main() {
  group('ModelCatalog', () {
    test('the sound-event model ships its model and class labels', () {
      const spec = ModelCatalog.soundEvents;
      expect(spec.kind, ModelKind.soundEvents);
      expect(ModelCatalog.all, contains(spec));
      // The engine reads files[0] as the model and files[1] as the labels.
      expect(spec.files.map((f) => f.filename), [
        'model.int8.onnx',
        'class_labels_indices.csv',
      ]);
    });

    test('recorded SHA-256 values are well formed and unique per file', () {
      final seen = <String>{};
      for (final spec in ModelCatalog.all) {
        for (final file in spec.files) {
          final hash = file.sha256;
          if (hash == null) continue;
          expect(hash, matches(RegExp(r'^[0-9a-f]{64}$')), reason: file.url);
          expect(seen.add(hash), isTrue, reason: 'repeated hash: ${file.url}');
        }
      }
      // Every weight file is covered; only the CED label list is not.
      final missing = [
        for (final spec in ModelCatalog.all)
          for (final file in spec.files)
            if (file.sha256 == null) '${spec.id}/${file.filename}',
      ];
      expect(missing, [
        'ced-tiny-audio-tagging-2024-04-19/class_labels_indices.csv',
      ]);
    });

    test('only licences the catalog already states are recorded', () {
      expect(ModelCatalog.speakerEmbedding.license, 'Apache-2.0');
      expect(ModelCatalog.speakerSegmentation.license, 'MIT');
      expect(ModelCatalog.soundEvents.license, isNull);
    });

    test('ids are unique', () {
      final ids = ModelCatalog.all.map((m) => m.id).toSet();
      expect(ids.length, ModelCatalog.all.length);
    });

    test('every model downloads from SedaSanj', () {
      for (final spec in ModelCatalog.all) {
        expect(spec.files, isNotEmpty);
        for (final file in spec.files) {
          expect(
            file.url,
            'https://sedasanj.ir/jalase-negar-models/v1/${spec.id}/${file.filename}',
          );
          expect(file.sizeBytes, greaterThan(0));
        }
      }
    });

    test('ASR bundles contain the files required by their Sherpa backend', () {
      for (final spec in ModelCatalog.asrModels) {
        expect(spec.kind, ModelKind.asr);
        final names = spec.files.map((f) => f.filename);
        expect(names, contains('tokens.txt'));
        if (spec.asrArchitecture == AsrArchitecture.nemoCtc) {
          expect(names, contains('model.onnx'));
        } else {
          expect(
            names,
            containsAll([
              'encoder.int8.onnx',
              'decoder.int8.onnx',
              'joiner.int8.onnx',
            ]),
          );
        }
      }
    });

    test('the server default RNNT model is the only recommended ASR model', () {
      final recommended = ModelCatalog.asrModels.where((m) => m.recommended);
      expect(recommended.map((m) => m.id), ['shenava-koochik-v1-5-rnnt']);
      expect(ModelCatalog.asrModels.first.id, 'shenava-koochik-v1-5-rnnt');
      expect(
        ModelCatalog.shenavaKoochikRnnt.asrArchitecture,
        AsrArchitecture.transducer,
      );
    });

    test('only the recommended ASR model is offered; others are retired', () {
      expect(ModelCatalog.asrModels.map((m) => m.id), [
        'shenava-koochik-v1-5-rnnt',
      ]);
      for (final id in ModelCatalog.retiredIds) {
        expect(() => ModelCatalog.byId(id), throwsStateError);
      }
    });

    test('byId resolves and throws for unknown ids', () {
      expect(
        ModelCatalog.byId('shenava-koochik-v1-5-rnnt').kind,
        ModelKind.asr,
      );
      expect(() => ModelCatalog.byId('nope'), throwsStateError);
    });
  });

  group('buildTranscriptText', () {
    test(
      'merges channels chronologically without fabricated speaker labels',
      () {
        final text = buildTranscriptText([
          (channel: 1, startMs: 2000, text: 'دوم'),
          (channel: 0, startMs: 1000, text: 'اول'),
          (channel: 0, startMs: 3000, text: 'سوم'),
        ], channelCount: 2);
        expect(text, 'اول\nدوم\nسوم');
      },
    );

    test('omits labels for mono recordings', () {
      final text = buildTranscriptText([
        (channel: 0, startMs: 0, text: 'سلام'),
      ], channelCount: 1);
      expect(text, 'سلام');
    });
  });
}
