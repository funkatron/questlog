import AppKit
import ApplicationServices
import Foundation

// Prints a JSON line: {"bundle_id": "...", "app": "...", "window_title": "..."}
// Requires Accessibility permission for the terminal/binary.

func frontmostInfo() -> [String: String] {
    var result: [String: String] = ["bundle_id": "unknown.bundle", "app": "Unknown", "window_title": "Unknown"]

    guard let app = NSWorkspace.shared.frontmostApplication else {
        return result
    }
    result["app"] = app.localizedName ?? "Unknown"
    result["bundle_id"] = app.bundleIdentifier ?? "unknown.bundle"

    let axApp = AXUIElementCreateApplication(app.processIdentifier)
    var focusedWindow: CFTypeRef?
    let copyRes = AXUIElementCopyAttributeValue(axApp, kAXFocusedWindowAttribute as CFString, &focusedWindow)

    if copyRes == .success, let window = focusedWindow {
        var titleValue: CFTypeRef?
        if AXUIElementCopyAttributeValue(window as! AXUIElement, kAXTitleAttribute as CFString, &titleValue) == .success {
            if let title = titleValue as? String, !title.isEmpty {
                result["window_title"] = title
            }
        }
    }

    return result
}

let info = frontmostInfo()
if let jsonData = try? JSONSerialization.data(withJSONObject: info, options: []) {
    if let jsonString = String(data: jsonData, encoding: .utf8) {
        print(jsonString)
    }
} else {
    print("{\"bundle_id\":\"unknown.bundle\",\"app\":\"Unknown\",\"window_title\":\"Unknown\"}")
}
