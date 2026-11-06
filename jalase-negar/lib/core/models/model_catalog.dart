import 'model_spec.dart';

/// Static catalog of supported models.
///
/// ASR: only the Shenava Koochik v1.5 RNNT (INT8) is offered; it is the one that the SedaSanj platform's aiservice runs on CPU,
/// so a local transcript and a server transcript come from the same weights.
/// VAD: Silero VAD used to segment long meeting audio before decoding.
abstract final class ModelCatalog {
  static const String vadModelId = 'silero-vad';

  static const ModelSpec sileroVad = ModelSpec(
    id: vadModelId,
    kind: ModelKind.vad,
    nameFa: 'تشخیص گفتار (Silero VAD)',
    descriptionFa: 'پیش‌نیاز رونویسی؛ صوت طولانی را به قطعه‌های گفتار می‌شکند',
    repoUrl: 'https://github.com/snakers4/silero-vad',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/silero-vad/silero_vad.onnx',
        filename: 'silero_vad.onnx',
        sizeBytes: 643854,
      ),
    ],
  );

  static const ModelSpec gtcrnDenoiser = ModelSpec(
    id: 'gtcrn-denoiser',
    kind: ModelKind.denoiser,
    nameFa: 'کاهش نویز (GTCRN)',
    descriptionFa: 'پیش‌پردازش اختیاری برای صدای ضعیف و محیط شلوغ',
    repoUrl: 'https://github.com/k2-fsa/sherpa-onnx',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/gtcrn-denoiser/gtcrn_simple.onnx',
        filename: 'gtcrn_simple.onnx',
        sizeBytes: 1700000,
        sizeIsEstimate: true,
      ),
    ],
  );

  /// Version stamped on voiceprints made with [speakerEmbedding]. Bump it when
  /// the file behind the id changes, so old voiceprints are not compared with
  /// embeddings of a different model.
  static const String speakerEmbeddingVersion = '1';

  static const String speakerEmbeddingId = 'campplus-sv-zh-en-16k';

  /// 3D-Speaker CAM++ (Chinese + English training data, Apache-2.0).
  /// ⚠ needs lab confirmation: no Persian benchmark exists for it; accuracy
  /// on Persian speech must be measured before trusting the default
  /// thresholds.
  static const ModelSpec speakerEmbedding = ModelSpec(
    id: speakerEmbeddingId,
    kind: ModelKind.speakerEmbedding,
    nameFa: 'تشخیص گوینده (CAM++)',
    descriptionFa:
        'پیش‌نیاز «افراد و صدا»؛ ردصدا را از گفتار می‌سازد تا گویندگان شناخته شوند',
    repoUrl: 'https://github.com/k2-fsa/sherpa-onnx',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/campplus-sv-zh-en-16k/speaker_embedding.onnx',
        filename: 'speaker_embedding.onnx',
        sizeBytes: 28281164,
      ),
    ],
  );

  /// pyannote segmentation 3.0 (MIT), int8 export by sherpa-onnx.
  static const ModelSpec speakerSegmentation = ModelSpec(
    id: 'pyannote-segmentation-3-0',
    kind: ModelKind.speakerSegmentation,
    nameFa: 'تشخیص هم‌پوشانی گفتار (pyannote)',
    descriptionFa:
        'اختیاری؛ تغییر گوینده و صحبت هم‌زمان دو نفر را در جلسه تشخیص می‌دهد',
    repoUrl: 'https://huggingface.co/pyannote/segmentation-3.0',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/pyannote-segmentation-3-0/model.int8.onnx',
        filename: 'model.int8.onnx',
        sizeBytes: 1540506,
      ),
    ],
  );

  static const String soundEventsId = 'ced-tiny-audio-tagging-2024-04-19';

  /// CED-tiny audio tagger (AudioSet, 527 classes) converted by sherpa-onnx.
  /// It lets the transcript name laughter, crying, coughs and similar sounds
  /// between square brackets. Optional: without it the transcript is plain
  /// speech.
  /// ⚠ needs lab confirmation: the licence of the Tiny weights is not stated
  /// on the sherpa-onnx repository page (CED-Base is Apache-2.0); read the
  /// upstream licence before a public release.
  static const ModelSpec soundEvents = ModelSpec(
    id: soundEventsId,
    kind: ModelKind.soundEvents,
    nameFa: 'تشخیص صداهای انسانی (CED)',
    descriptionFa:
        'اختیاری؛ خنده، گریه، سرفه و حالت‌های مشابه را در متن بین [ ] می‌نویسد',
    repoUrl:
        'https://huggingface.co/k2-fsa/sherpa-onnx-ced-tiny-audio-tagging-2024-04-19',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/ced-tiny-audio-tagging-2024-04-19/model.int8.onnx',
        filename: 'model.int8.onnx',
        sizeBytes: 6133417,
      ),
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/ced-tiny-audio-tagging-2024-04-19/class_labels_indices.csv',
        filename: 'class_labels_indices.csv',
        sizeBytes: 14675,
      ),
    ],
  );

  static const ModelSpec shenavaKoochikRnnt = ModelSpec(
    id: 'shenava-koochik-v1-5-rnnt',
    kind: ModelKind.asr,
    asrArchitecture: AsrArchitecture.transducer,
    nameFa: 'شنوا کوچیک ۱.۵ (Sherpa-ONNX RNNT، ۱۳۷M)',
    descriptionFa:
        'همان مدل پیش‌فرض سرور صداسنج (نسخهٔ INT8 برای پردازنده)؛ پیشنهاد اصلی',
    recommended: true,
    repoUrl:
        'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx',
    files: [
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/shenava-koochik-v1-5-rnnt/encoder.int8.onnx',
        filename: 'encoder.int8.onnx',
        sizeBytes: 131000000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/shenava-koochik-v1-5-rnnt/decoder.int8.onnx',
        filename: 'decoder.int8.onnx',
        sizeBytes: 3960000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/shenava-koochik-v1-5-rnnt/joiner.int8.onnx',
        filename: 'joiner.int8.onnx',
        sizeBytes: 1410000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://sedasanj.ir/jalase-negar-models/v1/shenava-koochik-v1-5-rnnt/tokens.txt',
        filename: 'tokens.txt',
        sizeBytes: 12236,
      ),
    ],
  );

  /// The only speech-to-text model offered; the others were retired.
  static final List<ModelSpec> asrModels = [shenavaKoochikRnnt];

  /// Ids of retired ASR models. Their files are deleted from the phone.
  static const List<String> retiredIds = [
    'shenava-koochik',
    'shenava-rizeh',
    'shenava-rizeh-pizeh',
  ];

  static final List<ModelSpec> speakerModels = [
    speakerEmbedding,
    speakerSegmentation,
  ];

  static final List<ModelSpec> all = [
    sileroVad,
    gtcrnDenoiser,
    ...speakerModels,
    soundEvents,
    ...asrModels,
  ];

  static ModelSpec byId(String id) => all.firstWhere((m) => m.id == id);
}
