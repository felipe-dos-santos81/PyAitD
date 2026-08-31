// SPDX-License-Identifier: GPL-2.0-only
// Live-mirror OS bridge: posts synthetic key events to the DOSBox-X pid
// and reports window geometry. Resident; reads lines from stdin.
import Cocoa
import Darwin

var reportedDead = Set<pid_t>()

func postKey(_ pid: pid_t, _ keyCode: CGKeyCode, _ down: Bool) {
    if kill(pid, 0) != 0 {
        if !reportedDead.contains(pid) {
            reportedDead.insert(pid)
            print("DEAD \(pid)")
            fflush(stdout)
        }
        return
    }
    guard let event = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: down)
    else { return }
    event.postToPid(pid)
}

func windows(_ needle: String) -> [(pid_t, CGFloat, CGFloat, CGFloat, CGFloat)] {
    var out: [(pid_t, CGFloat, CGFloat, CGFloat, CGFloat)] = []
    guard let list = CGWindowListCopyWindowInfo(
        [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
    ) as? [[String: Any]] else { return out }
    for w in list {
        let name = ((w[kCGWindowName as String] as? String) ?? "").lowercased()
        let owner = ((w[kCGWindowOwnerName as String] as? String) ?? "").lowercased()
        if !needle.isEmpty && !name.contains(needle) && !owner.contains(needle) { continue }
        guard let pid = w[kCGWindowOwnerPID as String] as? pid_t,
              let b = w[kCGWindowBounds as String] as? [String: CGFloat],
              let x = b["X"], let y = b["Y"], let wd = b["Width"], let ht = b["Height"]
        else { continue }
        out.append((pid, x, y, wd, ht))
    }
    return out
}

while let line = readLine() {
    let parts = line.split(separator: " ").map(String.init)
    switch parts.first {
    case "post":
        guard parts.count == 4,
              let keyCode = UInt16(parts[1]),
              let pid = pid_t(parts[3]) else { continue }
        postKey(pid, keyCode, parts[2] == "down")
    case "window":
        let needle = parts.count > 1 ? parts[1].lowercased() : ""
        if let (pid, x, y, wd, ht) = windows(needle).first {
            print("\(pid) \(Int(x)) \(Int(y)) \(Int(wd)) \(Int(ht))")
        } else {
            print("NONE")
        }
    default:
        break
    }
    fflush(stdout)
}
