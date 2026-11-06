import 'dart:io';

import 'package:dio/dio.dart';

import 'model_spec.dart';
import 'model_store.dart';

enum DownloadStatus { idle, downloading, paused, completed, failed }

class DownloadState {
  const DownloadState({
    required this.status,
    this.receivedBytes = 0,
    this.totalBytes = 0,
    this.speedBytesPerSecond = 0,
    this.error,
  });

  final DownloadStatus status;
  final int receivedBytes;
  final int totalBytes;
  final int speedBytesPerSecond;
  final String? error;

  double get progress => totalBytes == 0 ? 0 : receivedBytes / totalBytes;

  DownloadState copyWith({
    DownloadStatus? status,
    int? receivedBytes,
    int? totalBytes,
    int? speedBytesPerSecond,
    String? error,
  }) => DownloadState(
    status: status ?? this.status,
    receivedBytes: receivedBytes ?? this.receivedBytes,
    totalBytes: totalBytes ?? this.totalBytes,
    speedBytesPerSecond: speedBytesPerSecond ?? this.speedBytesPerSecond,
    error: error,
  );
}

/// Streams model files to disk with HTTP range resume.
///
/// Files download to `<name>.part` and are renamed once their size matches
/// the spec, so a killed app or dropped connection resumes where it left off
/// instead of restarting a multi-gigabyte pull.
class ModelDownloader {
  ModelDownloader(this._store)
    : _dio = Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 30),
          // Large model files can have long quiet periods on mobile networks.
          receiveTimeout: const Duration(minutes: 30),
          followRedirects: true,
          maxRedirects: 8,
        ),
      );

  static const Duration _progressInterval = Duration(milliseconds: 300);

  final ModelStore _store;
  final Dio _dio;
  final Map<String, CancelToken> _cancelTokens = {};

  bool isActive(String modelId) => _cancelTokens.containsKey(modelId);

  Future<void> download(
    ModelSpec spec, {
    required void Function(DownloadState state) onState,
  }) async {
    if (isActive(spec.id)) return;
    final cancelToken = CancelToken();
    _cancelTokens[spec.id] = cancelToken;
    final total = spec.totalSizeBytes;
    var currentSpeed = 0;
    try {
      await _store.dirFor(spec).create(recursive: true);
      var completedBytes = 0;
      for (final file in spec.files) {
        final target = File(_store.filePath(spec, file));
        if (await target.exists() &&
            (file.sizeIsEstimate || await target.length() == file.sizeBytes)) {
          completedBytes += file.sizeBytes;
          continue;
        }
        await _downloadFile(
          spec,
          file,
          cancelToken,
          onReceived: (received) => onState(
            DownloadState(
              status: DownloadStatus.downloading,
              receivedBytes: completedBytes + received,
              totalBytes: total,
              speedBytesPerSecond: currentSpeed,
            ),
          ),
          onSpeed: (speed) => currentSpeed = speed,
        );
        completedBytes += file.sizeBytes;
      }
      await _store.markInstalled(spec);
      onState(
        DownloadState(
          status: DownloadStatus.completed,
          receivedBytes: total,
          totalBytes: total,
          speedBytesPerSecond: 0,
        ),
      );
    } on DioException catch (e) {
      if (CancelToken.isCancel(e)) {
        onState(
          DownloadState(
            status: DownloadStatus.paused,
            receivedBytes: await _store.bytesOnDisk(spec),
            totalBytes: total,
            speedBytesPerSecond: currentSpeed,
          ),
        );
      } else {
        onState(
          DownloadState(
            status: DownloadStatus.failed,
            receivedBytes: await _store.bytesOnDisk(spec),
            totalBytes: total,
            speedBytesPerSecond: 0,
            error: _dioErrorMessage(e),
          ),
        );
      }
    } catch (e) {
      onState(
        DownloadState(
          status: DownloadStatus.failed,
          receivedBytes: await _store.bytesOnDisk(spec),
          totalBytes: total,
          speedBytesPerSecond: 0,
          error: e.toString(),
        ),
      );
    } finally {
      _cancelTokens.remove(spec.id);
    }
  }

  String _dioErrorMessage(DioException e) {
    final status = e.response?.statusCode;
    if (status == 404) {
      return 'فایل مدل روی سرور صداسنج موجود نیست (JN-MDL-0001). '
          'دوباره تلاش کنید و در صورت تکرار با پشتیبانی تماس بگیرید.';
    }
    return e.message ?? e.toString();
  }

  Future<void> _downloadFile(
    ModelSpec spec,
    ModelFileSpec file,
    CancelToken cancelToken, {
    required void Function(int receivedBytes) onReceived,
    required void Function(int speedBytesPerSecond) onSpeed,
  }) async {
    final part = File(_store.partPath(spec, file));
    var resumeFrom = await part.exists() ? await part.length() : 0;
    if (!file.sizeIsEstimate && resumeFrom > file.sizeBytes) {
      await part.delete();
      resumeFrom = 0;
    }

    Response<ResponseBody> response;
    try {
      response = await _dio.get<ResponseBody>(
        file.url,
        options: Options(
          responseType: ResponseType.stream,
          headers: {if (resumeFrom > 0) 'range': 'bytes=$resumeFrom-'},
        ),
        cancelToken: cancelToken,
      );
    } on DioException catch (e) {
      // The server can reject an old partial offset with HTTP 416.
      // Discard that stale range and retry once from byte zero.
      if (e.response?.statusCode != 416 || resumeFrom == 0) rethrow;
      if (await part.exists()) await part.delete();
      resumeFrom = 0;
      response = await _dio.get<ResponseBody>(
        file.url,
        options: Options(responseType: ResponseType.stream),
        cancelToken: cancelToken,
      );
    }

    // Server ignored the range request: start over.
    if (resumeFrom > 0 && response.statusCode != 206) {
      await part.delete();
      resumeFrom = 0;
    }

    final sink = part.openWrite(
      mode: resumeFrom > 0 ? FileMode.append : FileMode.write,
    );
    var received = resumeFrom;
    final progressClock = Stopwatch()..start();
    var speedClock = Stopwatch()..start();
    var speedStartBytes = received;
    try {
      await for (final chunk in response.data!.stream) {
        sink.add(chunk);
        received += chunk.length;
        if (speedClock.elapsedMilliseconds >= 800) {
          final seconds = speedClock.elapsedMilliseconds / 1000;
          onSpeed(((received - speedStartBytes) / seconds).round());
          speedStartBytes = received;
          speedClock = Stopwatch()..start();
        }
        if (progressClock.elapsed >= _progressInterval) {
          progressClock.reset();
          onReceived(received);
        }
      }
      onReceived(received);
      final seconds = speedClock.elapsedMilliseconds / 1000;
      if (seconds > 0) {
        onSpeed(((received - speedStartBytes) / seconds).round());
      }
      await sink.flush();
    } finally {
      await sink.close();
    }

    if (!file.sizeIsEstimate && received != file.sizeBytes) {
      throw Exception(
        'اندازه فایل دانلودشده نادرست است (${file.filename}): '
        '$received از ${file.sizeBytes} بایت',
      );
    }
    await part.rename(_store.filePath(spec, file));
  }

  void cancel(String modelId) {
    _cancelTokens[modelId]?.cancel();
  }
}
