// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
//
// cc-profiles: the Mac app, a window around the web UI. `cc-profiles install-app` puts this
// program in ~/Applications/cc-profiles.app with Resources/launch.json, which names the
// cc-profiles command to run and the port. At launch the app runs `<command> open --no-browser`
// (the server starts in the background unless it is running) and shows http://127.0.0.1:<port>
// in a WKWebView; on quit it stops the server, if it was the one that started it.
// Links to other sites open in the default browser, downloads go to ~/Downloads.
//
// Built by macapp.build_binary() (scripts/build_app.py): standard library only, no Xcode project.

import AppKit
import WebKit

struct Launch: Decodable {
    let command: [String]
    let port: Int
}

/// Run the cc-profiles command with these arguments; (exit status, output).
func runCommand(_ launch: Launch, _ args: [String], wait: Bool = true) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch.command[0])
    p.arguments = Array(launch.command.dropFirst()) + args
    p.standardInput = FileHandle.nullDevice
    let pipe = Pipe()
    p.standardOutput = wait ? pipe : FileHandle.nullDevice
    p.standardError = wait ? pipe : FileHandle.nullDevice
    do {
        try p.run()
    } catch {
        return (127, "\(launch.command[0]) could not start: \(error.localizedDescription)")
    }
    if !wait {
        return (0, "")
    }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

func escapeHTML(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        .replacingOccurrences(of: ">", with: "&gt;")
}

// The usual reason the command no longer runs: Homebrew replaced the Python it was installed with.
let brokenHint = """
    If Python was updated (by Homebrew, for example), install cc-profiles again in a terminal: \
    pipx reinstall cc-profiles, or uv tool install --force --reinstall cc-profiles. \
    See https://cc-profiles.andreaia.com/troubleshooting.html
    """
let retryScheme = "cc-profiles-app"

// Tells the app the page's background color, now and whenever the theme changes (the theme
// button sets data-theme on <html>; "system" follows macOS), so the title bar can wear it.
// It runs in its own world: the page's scripts do not see it, and its CSP does not apply.
let backgroundWatch = """
    (() => {
      let last = "";
      const send = () => {
        const color = getComputedStyle(document.body || document.documentElement).backgroundColor;
        if (color && color !== last) { last = color; webkit.messageHandlers.background.postMessage(color); }
      };
      const soon = () => { send(); setTimeout(send, 400); };  // after a background transition, too
      new MutationObserver(soon).observe(document.documentElement, { attributes: true });
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", soon);
      soon();
    })();
    """

/// "rgb(22, 21, 19)" or "rgba(…)" as a color, or nil.
func parseColor(_ css: String) -> NSColor? {
    let parts = css.split(whereSeparator: { !"0123456789.".contains($0) }).compactMap { Double($0) }
    guard parts.count >= 3 else { return nil }
    return NSColor(srgbRed: parts[0] / 255, green: parts[1] / 255, blue: parts[2] / 255, alpha: 1)
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate,
                         WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var launch: Launch?
    var startedServer = false
    var titleWatch: NSKeyValueObservation?

    var home: URL { URL(string: "http://127.0.0.1:\(launch?.port ?? 4777)/")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()  // the page's own settings (theme, last tab) are kept
        config.userContentController.addUserScript(WKUserScript(source: backgroundWatch, injectionTime: .atDocumentEnd,
                                                                forMainFrameOnly: true, in: .defaultClient))
        config.userContentController.add(self, contentWorld: .defaultClient, name: "background")
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "cc-profiles"
        window.titleVisibility = .hidden  // the page shows the name; the title bar is the page's color
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(name: nil) { appearance in  // until the page tells its own
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                ? NSColor(srgbRed: 0x16 / 255, green: 0x15 / 255, blue: 0x13 / 255, alpha: 1)
                : NSColor(srgbRed: 0xf6 / 255, green: 0xf5 / 255, blue: 0xf2 / 255, alpha: 1)
        }
        window.tabbingMode = .disallowed
        window.minSize = NSSize(width: 720, height: 480)
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("cc-profiles")
        titleWatch = web.observe(\.title) { [weak self] view, _ in
            if let title = view.title, !title.isEmpty {
                self?.window.title = title
            }
        }
        buildMenu()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        start()
    }

    /// Start the server unless it is running, then show the page.
    func start() {
        guard let url = Bundle.main.url(forResource: "launch", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let launch = try? JSONDecoder().decode(Launch.self, from: data), !launch.command.isEmpty else {
            show("This app is incomplete", "Run cc-profiles install-app in a terminal to create it again.", retry: false)
            return
        }
        self.launch = launch
        show("Starting cc-profiles…", "", retry: false)
        DispatchQueue.global(qos: .userInitiated).async {
            let (status, output) = runCommand(launch, ["open", "--no-browser", "--port", String(launch.port)])
            DispatchQueue.main.async {
                if status == 0 {
                    self.startedServer = self.startedServer || output.contains("started in the background")
                    self.web.load(URLRequest(url: self.home))
                } else {
                    self.show("cc-profiles did not start", output.trimmingCharacters(in: .whitespacesAndNewlines)
                              + "\n\n" + brokenHint, retry: true)
                }
            }
        }
    }

    /// A message in the window, in the page's colors, with a Try again button.
    func show(_ title: String, _ detail: String, retry: Bool) {
        let button = retry ? "<p><a class=\"b\" href=\"\(retryScheme):retry\">Try again</a></p>" : ""
        let html = """
            <!doctype html><meta charset="utf-8"><title>cc-profiles</title><style>
            :root { color-scheme: light dark; --bg: #f6f5f2; --ink: #1d1c1a; --dim: #6b6862; --accent: #d97757; }
            @media (prefers-color-scheme: dark) { :root { --bg: #161513; --ink: #ecebe8; --dim: #a19d96; } }
            body { margin: 0; height: 100vh; display: grid; place-items: center; background: var(--bg);
              color: var(--ink); font: 14px/1.5 -apple-system, system-ui, sans-serif; }
            main { max-width: 560px; padding: 24px; }
            h1 { font-size: 18px; margin: 0 0 8px; }
            pre { white-space: pre-wrap; color: var(--dim); font: 12px/1.5 ui-monospace, Menlo, monospace; }
            .b { display: inline-block; padding: 6px 14px; border-radius: 6px; background: var(--accent);
              color: #fff; text-decoration: none; }
            </style><main><h1>\(escapeHTML(title))</h1><pre>\(escapeHTML(detail))</pre>\(button)</main>
            """
        web.loadHTMLString(html, baseURL: nil)
    }

    func isLocal(_ url: URL) -> Bool {
        url.scheme == "http" && url.host == "127.0.0.1" && url.port == launch?.port
    }

    // The title bar takes the page's background, and a light or dark look to match it
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "background", let css = message.body as? String, let color = parseColor(css),
              let rgb = color.usingColorSpace(.sRGB) else { return }
        window.backgroundColor = color
        let light = 0.2126 * rgb.redComponent + 0.7152 * rgb.greenComponent + 0.0722 * rgb.blueComponent > 0.5
        window.appearance = NSAppearance(named: light ? .aqua : .darkAqua)
    }

    // MARK: navigation: the app's own pages here, every other site in the default browser

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, let scheme = url.scheme else {
            decisionHandler(.allow)
            return
        }
        if scheme == retryScheme {
            decisionHandler(.cancel)
            start()
        } else if action.shouldPerformDownload {
            decisionHandler(.download)
        } else if ["about", "blob", "data"].contains(scheme) || isLocal(url) {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
            NSWorkspace.shared.open(url)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let code = (error as NSError).code
        if code == NSURLErrorCancelled || code == 102 {  // 102: the load became a download
            return
        }
        show("cc-profiles is not answering", "\(error.localizedDescription)\n\nIt may have been stopped "
             + "(cc-profiles stop, /cc-profiles stop). Try again starts it.", retry: true)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    // window.open and target="_blank": in the default browser
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isLocal(url) {
                webView.load(action.request)
            } else {
                NSWorkspace.shared.open(url)
            }
        }
        return nil
    }

    // MARK: alert, confirm, prompt and <input type="file">, which a WKWebView leaves to the app

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    // MARK: downloads (exported profiles, usage CSV): into ~/Downloads, as a browser would

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let name = (suggestedFilename as NSString).lastPathComponent
        let stem = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var url = folder.appendingPathComponent(name)
        var n = 2
        while FileManager.default.fileExists(atPath: url.path) {  // never over an existing file
            url = folder.appendingPathComponent(ext.isEmpty ? "\(stem) \(n)" : "\(stem) \(n).\(ext)")
            n += 1
        }
        completionHandler(url)
    }

    // MARK: menus: without Edit, ⌘C, ⌘V, ⌘A and ⌘Z do nothing in the page's text fields

    func buildMenu() {
        let bar = NSMenu()
        func menu(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            let holder = NSMenuItem()
            holder.submenu = m
            bar.addItem(holder)
            return m
        }
        func item(_ title: String, _ action: Selector?, _ key: String = "",
                  _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        _ = menu("cc-profiles", [
            item("About cc-profiles", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("Hide cc-profiles", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("Quit cc-profiles", #selector(NSApplication.terminate(_:)), "q"),
        ])
        _ = menu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        _ = menu("View", [
            item("Reload", #selector(reload), "r"),
            item("Open in Browser", #selector(openInBrowser), "o", [.command, .shift]),
        ])
        let windows = menu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = bar
        NSApp.windowsMenu = windows
    }

    @objc func reload() {
        if let url = web.url, isLocal(url) {
            web.reload()
        } else {
            start()
        }
    }

    @objc func openInBrowser() {
        NSWorkspace.shared.open(web.url.flatMap { isLocal($0) ? $0 : nil } ?? home)
    }

    // MARK: quitting: closing the window quits; the server goes too if the app started it

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if startedServer, let launch = launch {  // not waited for: a write in progress finishes first
            _ = runCommand(launch, ["stop", "--port", String(launch.port)], wait: false)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
