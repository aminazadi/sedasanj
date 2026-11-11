import AVFoundation
import Flutter

/// Captures every channel of the external (USB) audio input and streams interleaved
/// little-endian PCM16 at 16 kHz to Dart, like the macOS implementation.
///
/// iOS only delivers more than the default channels when the session is active on that USB
/// route and `setPreferredInputNumberOfChannels` is called after activation (Apple forum reports:
/// a 10-input interface streamed only 2 channels otherwise). Not yet verified on hardware.
final class MultichannelCapture: NSObject, FlutterStreamHandler {
  static let targetRate: Double = 16000

  private var sink: FlutterEventSink?
  private let engine = AVAudioEngine()
  private var converter: AVAudioConverter?
  private var outFormat: AVAudioFormat?
  private var channels = 0
  private var running = false

  static func register(with messenger: FlutterBinaryMessenger) {
    let capture = MultichannelCapture()
    let method = FlutterMethodChannel(name: "jalase/multichannel_capture", binaryMessenger: messenger)
    method.setMethodCallHandler { call, result in capture.handle(call, result) }
    let events = FlutterEventChannel(
      name: "jalase/multichannel_capture/pcm", binaryMessenger: messenger)
    events.setStreamHandler(capture)
  }

  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink)
    -> FlutterError?
  {
    sink = events
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    sink = nil
    return nil
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "listInputs":
      result(listInputs())
    case "start":
      guard let args = call.arguments as? [String: Any],
        let uids = args["deviceUids"] as? [String], !uids.isEmpty
      else {
        result(FlutterError(code: "bad_args", message: "deviceUids is required", details: nil))
        return
      }
      guard uids.count == 1 else {
        result(
          FlutterError(
            code: "multi_unsupported", message: "Only one USB input can be captured at a time",
            details: nil))
        return
      }
      AVAudioSession.sharedInstance().requestRecordPermission { [weak self] granted in
        DispatchQueue.main.async {
          guard let self = self else { return }
          guard granted else {
            result(
              FlutterError(code: "mic_denied", message: "Microphone permission denied", details: nil))
            return
          }
          self.start(uid: uids[0], result: result)
        }
      }
    case "stop":
      stop()
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  // MARK: Devices

  private func usbPorts() -> [AVAudioSessionPortDescription] {
    (AVAudioSession.sharedInstance().availableInputs ?? []).filter { $0.portType == .usbAudio }
  }

  /// Channels of a USB port: what the port lists, or what the active route reports.
  private func channelsOf(_ port: AVAudioSessionPortDescription) -> Int {
    let session = AVAudioSession.sharedInstance()
    let listed = port.channels?.count ?? 0
    let active = session.currentRoute.inputs.contains { $0.uid == port.uid }
    return max(listed, active ? session.maximumInputNumberOfChannels : 0)
  }

  private func listInputs() -> [[String: Any]] {
    usbPorts().compactMap { port in
      let n = channelsOf(port)
      guard n > 0 else { return nil }
      return [
        "uid": port.uid, "name": port.portName, "channels": n,
        "sampleRate": AVAudioSession.sharedInstance().sampleRate,
      ]
    }
  }

  // MARK: Capture

  private func start(uid: String, result: @escaping FlutterResult) {
    stop()
    guard let port = usbPorts().first(where: { $0.uid == uid }) else {
      result(FlutterError(code: "device_missing", message: "Input device not found", details: nil))
      return
    }
    let session = AVAudioSession.sharedInstance()
    do {
      // `.measurement` turns off the voice processing that would collapse the channels to one.
      try session.setCategory(.record, mode: .measurement, options: [])
      try session.setPreferredInput(port)
      try session.setActive(true)
      // After activation, then again once the route settles.
      let wanted = max(channelsOf(port), session.maximumInputNumberOfChannels)
      try? session.setPreferredInputNumberOfChannels(wanted)
    } catch {
      result(FlutterError(code: "start", message: "Audio session failed: \(error)", details: nil))
      return
    }
    let input = engine.inputNode
    let inFmt = input.outputFormat(forBus: 0)
    let n = Int(inFmt.channelCount)
    guard n > 0, inFmt.sampleRate > 0 else {
      stop()
      result(FlutterError(code: "no_input", message: "Device has no input channels", details: nil))
      return
    }
    guard let layout = AVAudioChannelLayout(layoutTag: kAudioChannelLayoutTag_DiscreteInOrder | UInt32(n))
    else {
      stop()
      result(FlutterError(code: "format", message: "Cannot build \(n)-channel layout", details: nil))
      return
    }
    let outFmt = AVAudioFormat(
      commonFormat: .pcmFormatInt16, sampleRate: MultichannelCapture.targetRate,
      interleaved: true, channelLayout: layout)
    guard let conv = AVAudioConverter(from: inFmt, to: outFmt) else {
      stop()
      result(FlutterError(code: "format", message: "Cannot convert \(n)-channel audio", details: nil))
      return
    }
    channels = n
    outFormat = outFmt
    converter = conv
    input.installTap(onBus: 0, bufferSize: 4096, format: inFmt) { [weak self] buffer, _ in
      self?.onInput(buffer)
    }
    do {
      try engine.start()
    } catch {
      stop()
      result(FlutterError(code: "start", message: "Engine failed: \(error)", details: nil))
      return
    }
    running = true
    result(["channels": n, "sampleRate": Int(MultichannelCapture.targetRate)])
  }

  private func onInput(_ inBuf: AVAudioPCMBuffer) {
    guard let conv = converter, let outFmt = outFormat, channels > 0 else { return }
    let cap = AVAudioFrameCount(
      Double(inBuf.frameLength) * MultichannelCapture.targetRate / inBuf.format.sampleRate) + 64
    guard let outBuf = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
    var supplied = false
    var error: NSError?
    conv.convert(to: outBuf, error: &error) { _, status in
      if supplied {
        status.pointee = .noDataNow
        return nil
      }
      supplied = true
      status.pointee = .haveData
      return inBuf
    }
    guard error == nil, outBuf.frameLength > 0, let ch = outBuf.int16ChannelData?[0] else { return }
    let bytes = Data(bytes: ch, count: Int(outBuf.frameLength) * channels * 2)
    DispatchQueue.main.async { [weak self] in
      self?.sink?(FlutterStandardTypedData(bytes: bytes))
    }
  }

  private func stop() {
    if running || engine.isRunning {
      engine.inputNode.removeTap(onBus: 0)
      engine.stop()
    }
    running = false
    converter = nil
    channels = 0
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
  }
}
