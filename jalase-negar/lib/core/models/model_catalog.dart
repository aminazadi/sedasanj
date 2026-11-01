import 'model_spec.dart';

/// Static catalog of supported models.
///
/// ASR: the Shenava-1 family (FastConformer CTC), official sherpa-onnx
/// exports from the original release repositories.
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
        'نسخهٔ سبک و سریع برای نمایش زنده؛ دقت فایل نهایی از مدل CTC کمتر است',
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
    _shenava(
      id: 'shenava-koochik',
      repo: 'Shenava-Koochik-v1.0-sherpa-onnx',
      nameFa: 'شنوا کوچیک (۱۱۴M)',
      descriptionFa:
          'بالاترین دقت برای رونویسی فایل جلسه؛ انتخاب اصلی گوشی‌های میان‌رده به بالا',
      modelSize: 458819249,
      recommended: true,
    ),
    shenavaKoochikRnnt,
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

  static final List<ModelSpec> all = [sileroVad, gtcrnDenoiser, ...asrModels];

  static ModelSpec byId(String id) => all.firstWhere((m) => m.id == id);
}
