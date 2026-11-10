import AVFoundation
import Cocoa
import CoreAudio
import FlutterMacOS

/// Captures every input channel of ONE CoreAudio device (a multichannel USB
/// interface, or an Aggregate Device the user built in Audio MIDI Setup) and
/// streams interleaved little-endian PCM16 at 16 kHz to Dart.
///
/// Uses a HAL IOProc, not AVAudioEngine: forum reports say AVAudioEngine
/// misreports the format/channel count of aggregate devices. Resampling to
/// 16 kHz is done by AVAudioConverter. Not yet verified on hardware.
final class MultichannelCapture: NSObject, FlutterStreamHandler {
  static let targetRate: Double = 16000

  private var sink: FlutterEventSink?
  private var deviceId = AudioObjectID(kAudioObjectUnknown)
  private var aggregateId = AudioObjectID(kAudioObjectUnknown)
  private var ioProc: AudioDeviceIOProcID?
  private var converter: AVAudioConverter?
  private var inFormat: AVAudioFormat?
  private var outFormat: AVAudioFormat?
  private var channels = 0
  private var deviceRate = 0.0
  private let queue = DispatchQueue(label: "ir.sedasanj.multichannel", qos: .userInitiated)

  static func register(with messenger: FlutterBinaryMessenger) {
    let capture = MultichannelCapture()
    let method = FlutterMethodChannel(
      name: "jalase/multichannel_capture", binaryMessenger: messenger)
    method.setMethodCallHandler { call, result in capture.handle(call, result) }
    let events = FlutterEventChannel(
      name: "jalase/multichannel_capture/pcm", binaryMessenger: messenger)
    events.setStreamHandler(capture)
  }

  // MARK: FlutterStreamHandler

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

  // MARK: Method channel

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "listInputs":
      result(listInputs())
    case "start":
      guard let args = call.arguments as? [String: Any],
        let uids = (args["deviceUids"] as? [String]) ?? (args["deviceUid"] as? String).map({ [$0] }),
        !uids.isEmpty
      else {
        result(FlutterError(code: "bad_args", message: "deviceUids is required", details: nil))
        return
      }
      requestMic { [weak self] granted in
        guard let self = self else { return }
        guard granted else {
          result(FlutterError(code: "mic_denied", message: "Microphone permission denied", details: nil))
          return
        }
        self.start(uids: uids, result: result)
      }
    case "stop":
      stop()
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func requestMic(_ done: @escaping (Bool) -> Void) {
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized: done(true)
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { done(ok) } }
    default: done(false)
    }
  }

  // MARK: Devices

  private func allDevices() -> [AudioObjectID] {
    var addr = AudioObjectPropertyAddress(
      mSelector: kAudioHardwarePropertyDevices, mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
      == noErr
    else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
      == noErr
    else { return [] }
    return ids
  }

  private func stringProp(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = AudioObjectPropertyAddress(
      mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &value) == noErr,
      let cf = value?.takeRetainedValue()
    else { return nil }
    return cf as String
  }

  /// Total input channels over all input streams of the device.
  private func inputChannels(_ id: AudioObjectID) -> Int {
    var addr = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyStreamConfiguration, mScope: kAudioDevicePropertyScopeInput,
      mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(
      byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return list.reduce(0) { $0 + Int($1.mNumberChannels) }
  }

  private func isAggregate(_ id: AudioObjectID) -> Bool {
    var addr = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyTransportType, mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var t = UInt32(0)
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &t) == noErr else { return false }
    return t == kAudioDeviceTransportTypeAggregate
  }

  /// A private aggregate of several devices, with drift compensation on
  /// every member except the first (the clock master). Channels come in the
  /// order of [uids]. Private: it is not shown in Audio MIDI Setup and goes
  /// away with the app.
  private func makeAggregate(_ uids: [String]) -> AudioObjectID? {
    let subDevices: [[String: Any]] = uids.enumerated().map { i, uid in
      [
        kAudioSubDeviceUIDKey as String: uid,
        kAudioSubDeviceDriftCompensationKey as String: i == 0 ? 0 : 1,
      ]
    }
    let desc: [String: Any] = [
      kAudioAggregateDeviceNameKey as String: "Jalase Negar Input",
      kAudioAggregateDeviceUIDKey as String: "ir.sedasanj.jalase.aggregate.\(UUID().uuidString)",
      kAudioAggregateDeviceIsPrivateKey as String: 1,
      kAudioAggregateDeviceMainSubDeviceKey as String: uids[0],
      kAudioAggregateDeviceSubDeviceListKey as String: subDevices,
    ]
    var id = AudioObjectID(kAudioObjectUnknown)
    guard AudioHardwareCreateAggregateDevice(desc as CFDictionary, &id) == noErr else { return nil }
    return id
  }

  private func nominalRate(_ id: AudioObjectID) -> Double {
    var addr = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyNominalSampleRate, mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var rate = Float64(0)
    var size = UInt32(MemoryLayout<Float64>.size)
    _ = AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &rate)
    return rate
  }

  private func isBuiltIn(_ id: AudioObjectID) -> Bool {
    var addr = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyTransportType, mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var t = UInt32(0)
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &t) == noErr else { return false }
    return t == kAudioDeviceTransportTypeBuiltIn
  }

  private func listInputs() -> [[String: Any]] {
    allDevices().compactMap { id in
      let n = inputChannels(id)
      guard n > 0, !isAggregate(id), let uid = stringProp(id, kAudioDevicePropertyDeviceUID)
      else { return nil }
      return [
        "uid": uid,
        "name": stringProp(id, kAudioObjectPropertyName) ?? uid,
        "channels": n,
        "sampleRate": nominalRate(id),
        "builtIn": isBuiltIn(id),
      ]
    }
  }

  private func device(forUid uid: String) -> AudioObjectID? {
    allDevices().first { stringProp($0, kAudioDevicePropertyDeviceUID) == uid }
  }

  // MARK: Capture

  private func start(uids: [String], result: @escaping FlutterResult) {
    stop()
    var target: AudioObjectID
    if uids.count == 1 {
      guard let id = device(forUid: uids[0]) else {
        result(FlutterError(code: "device_missing", message: "Input device not found", details: nil))
        return
      }
      target = id
    } else {
      for uid in uids where device(forUid: uid) == nil {
        result(FlutterError(code: "device_missing", message: "Input device not found", details: nil))
        return
      }
      guard let agg = makeAggregate(uids) else {
        result(FlutterError(code: "aggregate", message: "Could not combine the microphones", details: nil))
        return
      }
      aggregateId = agg
      target = agg
      // The members' streams appear a moment after creation.
      var waited = 0
      while inputChannels(agg) == 0 && waited < 20 {
        Thread.sleep(forTimeInterval: 0.1)
        waited += 1
      }
    }
    let id = target
    let n = inputChannels(id)
    let rate = nominalRate(id)
    guard n > 0, rate > 0 else {
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
    let inFmt = AVAudioFormat(
      commonFormat: .pcmFormatFloat32, sampleRate: rate, interleaved: true, channelLayout: layout)
    let outFmt = AVAudioFormat(
      commonFormat: .pcmFormatInt16, sampleRate: MultichannelCapture.targetRate, interleaved: true,
      channelLayout: layout)
    guard let conv = AVAudioConverter(from: inFmt, to: outFmt) else {
      stop()
      result(FlutterError(code: "format", message: "Cannot convert \(n)-channel audio", details: nil))
      return
    }
    deviceId = id
    channels = n
    deviceRate = rate
    inFormat = inFmt
    outFormat = outFmt
    converter = conv

    var proc: AudioDeviceIOProcID?
    let status = AudioDeviceCreateIOProcIDWithBlock(&proc, id, queue) {
      [weak self] _, inData, _, _, _ in
      self?.onInput(inData)
    }
    guard status == noErr, let created = proc else {
      stop()
      result(FlutterError(code: "ioproc", message: "IOProc failed (\(status))", details: nil))
      return
    }
    ioProc = created
    let startStatus = AudioDeviceStart(id, created)
    guard startStatus == noErr else {
      stop()
      result(FlutterError(code: "start", message: "AudioDeviceStart failed (\(startStatus))", details: nil))
      return
    }
    result(["channels": n, "sampleRate": Int(MultichannelCapture.targetRate), "deviceRate": rate])
  }

  private func onInput(_ data: UnsafePointer<AudioBufferList>) {
    guard let conv = converter, let inFmt = inFormat, let outFmt = outFormat, channels > 0 else { return }
    let list = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: data))
    guard let first = list.first, first.mNumberChannels > 0 else { return }
    let frames = Int(first.mDataByteSize) / (MemoryLayout<Float>.size * Int(first.mNumberChannels))
    guard frames > 0,
      let inBuf = AVAudioPCMBuffer(pcmFormat: inFmt, frameCapacity: AVAudioFrameCount(frames))
    else { return }
    inBuf.frameLength = AVAudioFrameCount(frames)
    guard let dst = inBuf.floatChannelData?[0] else { return }
    // Interleave every device stream into one frame-major float buffer.
    var chOffset = 0
    for buffer in list {
      let c = Int(buffer.mNumberChannels)
      guard let src = buffer.mData?.assumingMemoryBound(to: Float.self), c > 0 else { continue }
      let f = min(frames, Int(buffer.mDataByteSize) / (MemoryLayout<Float>.size * c))
      for i in 0..<f {
        for k in 0..<c where chOffset + k < channels {
          dst[i * channels + chOffset + k] = src[i * c + k]
        }
      }
      chOffset += c
    }
    let cap = AVAudioFrameCount(Double(frames) * MultichannelCapture.targetRate / deviceRate) + 64
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
    if let proc = ioProc, deviceId != AudioObjectID(kAudioObjectUnknown) {
      AudioDeviceStop(deviceId, proc)
      AudioDeviceDestroyIOProcID(deviceId, proc)
    }
    ioProc = nil
    converter = nil
    deviceId = AudioObjectID(kAudioObjectUnknown)
    if aggregateId != AudioObjectID(kAudioObjectUnknown) {
      AudioHardwareDestroyAggregateDevice(aggregateId)
      aggregateId = AudioObjectID(kAudioObjectUnknown)
    }
    channels = 0
  }
}
