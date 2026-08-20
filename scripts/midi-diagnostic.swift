import CoreMIDI
import Foundation

private func endpointName(_ endpoint: MIDIEndpointRef) -> String {
    var value: Unmanaged<CFString>?
    guard MIDIObjectGetStringProperty(endpoint, kMIDIPropertyDisplayName, &value) == noErr,
          let value else {
        return "Unknown MIDI source"
    }
    return value.takeRetainedValue() as String
}

private func noteName(_ note: UInt8) -> String {
    let names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return "\(names[Int(note) % 12])\(Int(note) / 12 - 1)"
}

private func describe(_ bytes: [UInt8]) -> String {
    guard let status = bytes.first else { return "empty packet" }
    let kind = status & 0xF0
    let channel = Int(status & 0x0F) + 1

    switch kind {
    case 0x90 where bytes.count >= 3 && bytes[2] > 0:
        return "NOTE ON  \(noteName(bytes[1])) (\(bytes[1])) velocity \(bytes[2]) channel \(channel)"
    case 0x80 where bytes.count >= 3, 0x90 where bytes.count >= 3:
        return "NOTE OFF \(noteName(bytes[1])) (\(bytes[1])) channel \(channel)"
    case 0xB0 where bytes.count >= 3:
        let label = bytes[1] == 64 ? "sustain pedal" : "control \(bytes[1])"
        return "CONTROL  \(label) value \(bytes[2]) channel \(channel)"
    default:
        return "RAW      " + bytes.map { String(format: "%02X", $0) }.joined(separator: " ")
    }
}

let seconds = Double(CommandLine.arguments.dropFirst().first ?? "20") ?? 20
var client = MIDIClientRef()
var inputPort = MIDIPortRef()

guard MIDIClientCreate("Piano Tutor MIDI Diagnostic" as CFString, nil, nil, &client) == noErr else {
    fputs("Could not create a CoreMIDI client.\n", stderr)
    exit(1)
}

let readBlock: MIDIReadBlock = { packetList, _ in
    var packet = packetList.pointee.packet
    for _ in 0..<packetList.pointee.numPackets {
        let length = Int(packet.length)
        let bytes: [UInt8] = withUnsafePointer(to: &packet.data) { dataPointer in
            let bytePointer = UnsafeRawPointer(dataPointer).assumingMemoryBound(to: UInt8.self)
            return Array(UnsafeBufferPointer(start: bytePointer, count: length))
        }
        print(describe(bytes))
        fflush(stdout)
        packet = MIDIPacketNext(&packet).pointee
    }
}

guard MIDIInputPortCreateWithBlock(client, "Piano Tutor Input" as CFString, &inputPort, readBlock) == noErr else {
    fputs("Could not create a CoreMIDI input port.\n", stderr)
    exit(1)
}

let sourceCount = MIDIGetNumberOfSources()
guard sourceCount > 0 else {
    print("No CoreMIDI input sources found. Check power and the USB-B data cable.")
    exit(2)
}

var connected: [String] = []
for index in 0..<sourceCount {
    let source = MIDIGetSource(index)
    let name = endpointName(source)
    if MIDIPortConnectSource(inputPort, source, nil) == noErr {
        connected.append(name)
    }
}

print("Connected MIDI sources: \(connected.joined(separator: ", "))")
print("Listening for \(Int(seconds)) seconds — play several keys and press the sustain pedal...")
fflush(stdout)
RunLoop.current.run(until: Date().addingTimeInterval(seconds))
print("MIDI diagnostic finished.")
