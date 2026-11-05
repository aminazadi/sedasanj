import 'model_spec.dart';

/// Static catalog of supported models.
///
/// ASR: the Shenava family (FastConformer), official sherpa-onnx exports from
/// the original release repositories. The recommended model is the same Shenava
/// Koochik v1.5 RNNT (INT8) that the SedaSanj platform's aiservice runs on CPU,
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
            'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx',
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
            'https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx',
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
            'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx',
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
            'https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/main/model.int8.onnx',
        filename: 'model.int8.onnx',
        sizeBytes: 1540506,
      ),
    ],
  );

  static ModelSpec _shenava({
    required String id,
    required String repo,
    required String nameFa,
    required String descriptionFa,
    required int modelSize,
    bool recommended = false,
  }) {
    final base = 'https://huggingface.co/Reza2kn/$repo/resolve/main';
    return ModelSpec(
      id: id,
      kind: ModelKind.asr,
      nameFa: nameFa,
      descriptionFa: descriptionFa,
      repoUrl: 'https://huggingface.co/Reza2kn/$repo',
      recommended: recommended,
      files: [
        ModelFileSpec(
          url: '$base/model.onnx',
          filename: 'model.onnx',
          sizeBytes: modelSize,
        ),
        ModelFileSpec(
          url: '$base/tokens.txt',
          filename: 'tokens.txt',
          sizeBytes: 12236,
        ),
      ],
    );
  }

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
            'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/encoder.int8.onnx?download=true',
        filename: 'encoder.int8.onnx',
        sizeBytes: 131000000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/decoder.int8.onnx?download=true',
        filename: 'decoder.int8.onnx',
        sizeBytes: 3960000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/joiner.int8.onnx?download=true',
        filename: 'joiner.int8.onnx',
        sizeBytes: 1410000,
        sizeIsEstimate: true,
      ),
      ModelFileSpec(
        url:
            'https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx/resolve/main/tokens.txt?download=true',
        filename: 'tokens.txt',
        sizeBytes: 12236,
      ),
    ],
  );

  static final List<ModelSpec> asrModels = [
    shenavaKoochikRnnt,
    _shenava(
      id: 'shenava-koochik',
      repo: 'Shenava-Koochik-v1.0-sherpa-onnx',
      nameFa: 'شنوا کوچیک (۱۱۴M)',
      descriptionFa: 'مدل CTC بزرگ‌تر (حدود ۴۳۸ مگابایت)؛ جایگزین مدل پیشنهادی',
      modelSize: 458819249,
    ),
    _shenava(
      id: 'shenava-rizeh',
      repo: 'Shenava-Rizeh-v1.0-sherpa-onnx',
      nameFa: 'شنوا ریزه (۳۲M)',
      descriptionFa: 'تعادل دقت و سرعت؛ برای بیشتر گوشی‌ها',
      modelSize: 116700660,
    ),
    _shenava(
      id: 'shenava-rizeh-pizeh',
      repo: 'Shenava-Rizeh-Pizeh-v1.0-sherpa-onnx',
      nameFa: 'شنوا ریزه‌پیزه (۶.۹M)',
      descriptionFa: 'سبک‌ترین گزینه؛ سریع حتی روی گوشی‌های ضعیف',
      modelSize: 33201018,
    ),
  ];

  static final List<ModelSpec> speakerModels = [
    speakerEmbedding,
    speakerSegmentation,
  ];

  static final List<ModelSpec> all = [
    sileroVad,
    gtcrnDenoiser,
    ...speakerModels,
    ...asrModels,
  ];

  static ModelSpec byId(String id) => all.firstWhere((m) => m.id == id);
}
