// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
//
// cc-profiles: the Mac app, a window around the web UI. `cc-profiles install-app` puts this
// program in ~/Applications/cc-profiles.app with Resources/launch.json, which names the
// cc-profiles command to run and the port. At launch the app runs `<command> open --no-browser`
// (the server starts in the background unless it is running) and shows http://127.0.0.1:<port>
// in a WKWebView; on quit it stops the server, if it was the one that started it. While the
// window is open it checks the server every few seconds and starts it again if it stopped.
// Links to other sites open in the default browser, downloads go to ~/Downloads. Folders and
// profile .zip files dropped on the window or the Dock icon go to the page (Relink, Import).
// Recent projects open in a terminal with Claude Code from the Dock icon's menu and, optionally,
// from an icon in the menu bar; any folder does from Finder (Quick Actions). Optional: opening
// at login. The window comes back where it was, on the tab it was on.
//
// Built by macapp.build_binary() (scripts/build_app.py): standard library only, no Xcode project.

import AppKit
import ServiceManagement
import UserNotifications
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

// Tells the app the page's background color (for the title bar) and whether a new version of
// cc-profiles is out (the ⓘ button gets the has-update class, its title names the version),
// now and whenever they change. It runs in its own world: the page's scripts do not see it,
// and its CSP does not apply.
let pageWatch = """
    (() => {
      let color = "", update = null;
      const send = () => {
        const c = getComputedStyle(document.body || document.documentElement).backgroundColor;
        if (c && c !== color) { color = c; webkit.messageHandlers.background.postMessage(c); }
        const b = document.querySelector("#about-btn");
        const u = b && b.classList.contains("has-update") ? ((b.title.match(/cc-profiles (\\S+) is available/) || [])[1] || "") : null;
        if (b && u !== update) { update = u; webkit.messageHandlers.update.postMessage(u === null ? "-" : u); }
      };
      const soon = () => { send(); setTimeout(send, 400); };  // after a background transition, too
      new MutationObserver(soon).observe(document.documentElement,
        { attributes: true, subtree: true, attributeFilter: ["class", "title", "data-theme"] });
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", soon);
      soon();
    })();
    """

// The page's tabs, in order: ⌘1 to ⌘9 go to the first nine
let tabs: [(String, String)] = [("projects", "Projects"), ("memories", "Memories"), ("conversations", "Conversations"),
                                ("usage", "Usage"), ("skills", "Skills"), ("agents", "Agents"), ("mcp", "MCP"),
                                ("plugins", "Plugins"), ("profiles", "Profiles"), ("compare", "Compare"),
                                ("backups", "Backups"), ("health", "Health"), ("settings", "Settings")]

/// "rgb(22, 21, 19)" or "rgba(…)" as a color, or nil.
func parseColor(_ css: String) -> NSColor? {
    let parts = css.split(whereSeparator: { !"0123456789.".contains($0) }).compactMap { Double($0) }
    guard parts.count >= 3 else { return nil }
    return NSColor(srgbRed: parts[0] / 255, green: parts[1] / 255, blue: parts[2] / 255, alpha: 1)
}

/// The mascot of the favicon, as a menu bar icon (a template: macOS colors it).
func mascotImage() -> NSImage {
    let grid = ["......#.....", ".....#......", "..########..", ".##########.", ".##.####.##.", ".##.####.##.",
                ".##########.", ".##########.", ".##########.", "..##....##.."]
    let cell: CGFloat = 1.5
    let image = NSImage(size: NSSize(width: 12 * cell, height: CGFloat(grid.count) * cell + 2), flipped: true) { _ in
        NSColor.black.setFill()
        for (y, row) in grid.enumerated() {
            for (x, c) in row.enumerated() where c == "#" {
                NSRect(x: CGFloat(x) * cell, y: CGFloat(y) * cell + 1, width: cell, height: cell).fill()
            }
        }
        return true
    }
    image.isTemplate = true
    return image
}

/// A WKWebView that hands folders dropped on it to the app (the page cannot learn their path).
final class WebView: WKWebView {
    var onFolders: (([URL]) -> Void)?

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self],
                                                         options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
        let folders = urls.filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
        if !folders.isEmpty, let handle = onFolders {
            handle(folders)
            return true
        }
        return super.performDragOperation(sender)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKNavigationDelegate,
                         WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler, UNUserNotificationCenterDelegate {
    var window: NSWindow!
    var web: WebView!
    var launch: Launch?
    var startedServer = false
    var starting = false
    var failures = 0             // server checks in a row that got no answer
    var restarts: [Date] = []    // when the app started the server again by itself
    var pending: [URL] = []      // files opened before the page was there
    var titleWatch: NSKeyValueObservation?
    var statusItem: NSStatusItem?
    var token: String?           // the page's API token: read and written under tokenLock
    let tokenLock = NSLock()
    var recent: [[String: Any]] = []     // the recent projects, for the Dock icon's menu
    var labels: [String: String] = [:]   // profile id → name
    let defaults = UserDefaults.standard

    var home: URL { URL(string: "http://127.0.0.1:\(launch?.port ?? 4777)/")! }
    var inMenuBar: Bool { defaults.bool(forKey: "menuBar") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let event = NSAppleEventManager.shared().currentAppleEvent
        let atLogin = event?.eventID == kAEOpenApplication
            && event?.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()  // the page's own settings (theme, last tab) are kept
        config.applicationNameForUserAgent = "cc-profiles-app"  // the page shows the app's shortcuts
        config.userContentController.addUserScript(WKUserScript(source: pageWatch, injectionTime: .atDocumentEnd,
                                                                forMainFrameOnly: true, in: .defaultClient))
        // The page runs under the transparent title bar, so its overlays and the About panel reach
        // the top of the window: --titlebar tells it how much room to leave for the window's buttons.
        let titlebar = NSWindow.frameRect(forContentRect: NSRect(x: 0, y: 0, width: 100, height: 100),
                                          styleMask: [.titled]).height - 100
        config.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.style.setProperty('--titlebar', '\(Int(titlebar))px')",
            injectionTime: .atDocumentStart, forMainFrameOnly: true, in: .defaultClient))
        for name in ["background", "update"] {
            config.userContentController.add(self, contentWorld: .defaultClient, name: name)
        }
        web = WebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.onFolders = { [weak self] in self?.dropped($0) }
        web.pageZoom = CGFloat(defaults.object(forKey: "zoom") as? Double ?? 1)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
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
        window.isReleasedWhenClosed = false  // closed to the menu bar, it opens again
        window.delegate = self
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("cc-profiles")
        window.setFrameUsingName("cc-profiles")  // where it was when it closed
        titleWatch = web.observe(\.title) { [weak self] view, _ in
            if let title = view.title, !title.isEmpty {
                self?.window.title = title
            }
        }
        UNUserNotificationCenter.current().delegate = self
        NSApp.servicesProvider = self  // the Finder's Quick Actions
        NSUpdateDynamicServices()
        buildMenu()
        setMenuBar(inMenuBar)
        if atLogin && inMenuBar {  // at login it waits in the menu bar
            NSApp.setActivationPolicy(.accessory)
        } else {
            showWindow()
        }
        start()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.checkServer() }
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refreshRecent() }
    }

    func showWindow() {
        NSApp.setActivationPolicy(.regular)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
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
        starting = true
        show("Starting cc-profiles…", "", retry: false)
        DispatchQueue.global(qos: .userInitiated).async {
            let (status, output) = runCommand(launch, ["open", "--no-browser", "--port", String(launch.port)])
            DispatchQueue.main.async {
                self.starting = false
                self.failures = 0
                self.tokenLock.lock()
                self.token = nil  // a server started again has a new one
                self.tokenLock.unlock()
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

    /// Every few seconds while the page is shown: no answer twice in a row (it was stopped, or
    /// it crashed) starts the server again, up to three times in five minutes.
    func checkServer() {
        guard !starting, let url = web.url, isLocal(url) else { return }
        var request = URLRequest(url: home, timeoutInterval: 2)
        request.httpMethod = "GET"
        URLSession.shared.dataTask(with: request) { _, response, _ in
            let alive = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Server")?.hasPrefix("cc-profiles/") == true
            DispatchQueue.main.async {
                guard !self.starting else { return }
                self.failures = alive ? 0 : self.failures + 1
                guard self.failures >= 2 else { return }
                self.restarts = self.restarts.filter { $0.timeIntervalSinceNow > -300 }
                if self.restarts.count >= 3 {
                    self.show("cc-profiles keeps stopping", "It was started again three times in the last five "
                              + "minutes. See ~/.cc-profiles/server.log.", retry: true)
                } else {
                    self.restarts.append(Date())
                    self.start()
                }
            }
        }.resume()
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

    /// Run a statement in the page (its own world: the page's functions are there).
    func page(_ js: String, _ args: [String: Any] = [:]) {
        web.callAsyncJavaScript(js, arguments: args, in: nil, in: .page, completionHandler: nil)
    }

    // MARK: messages from the page: its background for the title bar, a new version for the Dock

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? String else { return }
        if message.name == "background", let color = parseColor(body), let rgb = color.usingColorSpace(.sRGB) {
            window.backgroundColor = color
            let light = 0.2126 * rgb.redComponent + 0.7152 * rgb.greenComponent + 0.0722 * rgb.blueComponent > 0.5
            window.appearance = NSAppearance(named: light ? .aqua : .darkAqua)
        } else if message.name == "update" {
            updateAvailable(body == "-" ? nil : body)
        }
    }

    /// A badge on the Dock icon while a new version is out, and a notification once per version.
    func updateAvailable(_ version: String?) {
        NSApp.dockTile.badgeLabel = version == nil ? nil : "1"
        guard let version = version, !version.isEmpty, defaults.string(forKey: "notifiedVersion") != version else { return }
        defaults.set(version, forKey: "notifiedVersion")
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = "cc-profiles \(version) is available"
            content.body = "Click to see what changed and update."
            center.add(UNNotificationRequest(identifier: "update-\(version)", content: content, trigger: nil))
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        showWindow()
        page("document.querySelector('#about-btn')?.click()")
        done()
    }

    // MARK: files: folders to Relink, profile .zip files to Import, from the window or the Dock icon

    func application(_ application: NSApplication, open urls: [URL]) {
        showWindow()
        if let url = web.url, isLocal(url), !starting {
            dropped(urls)
        } else {
            pending += urls
        }
    }

    func dropped(_ urls: [URL]) {
        for url in urls {
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                page("window.ccDropFolder?.(path)", ["path": url.path])
            } else if url.pathExtension.lowercased() == "zip",
                      let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= 500 << 20,
                      let data = try? Data(contentsOf: url) {
                page("window.ccDropZip?.(name, data)", ["name": url.lastPathComponent, "data": data.base64EncodedString()])
            }
        }
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
            restarts = []
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

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, isLocal(url) {
            refreshRecent()
        }
        if let url = webView.url, isLocal(url), !pending.isEmpty {
            let urls = pending
            pending = []
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.dropped(urls) }  // once the page has its data
        }
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
                  _ mods: NSEvent.ModifierFlags = .command, tag: Int = 0) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            i.tag = tag
            return i
        }
        let zoomIn = item("Zoom In", #selector(zoom(_:)), "=", tag: 1)  // ⌘= on keyboards without a + key
        zoomIn.isHidden = true
        zoomIn.allowsKeyEquivalentWhenHidden = true
        var appItems = [item("About cc-profiles", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
                        .separator(),
                        item("Settings…", #selector(goTab(_:)), ",", tag: tabs.count - 1),
                        .separator(),
                        item("Show in Menu Bar", #selector(toggleMenuBar))]
        if #available(macOS 13, *) {
            appItems.append(item("Open at Login", #selector(toggleLogin)))
        }
        appItems += [.separator(),
                     item("Hide cc-profiles", #selector(NSApplication.hide(_:)), "h"),
                     item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
                     item("Show All", #selector(NSApplication.unhideAllApplications(_:))),
                     .separator(),
                     item("Quit cc-profiles", #selector(NSApplication.terminate(_:)), "q")]
        menu("cc-profiles", appItems).delegate = self
        _ = menu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
            .separator(),
            item("Search Everything", #selector(search), "f"),
        ])
        _ = menu("View", [
            item("Reload", #selector(reload), "r"),
            item("Open in Browser", #selector(openInBrowser), "o", [.command, .shift]),
            .separator(),
            item("Actual Size", #selector(zoom(_:)), "0", tag: 0),
            item("Zoom In", #selector(zoom(_:)), "+", tag: 1),
            zoomIn,
            item("Zoom Out", #selector(zoom(_:)), "-", tag: -1),
        ])
        _ = menu("Go", tabs.enumerated().map { i, tab in
            item(tab.1, #selector(goTab(_:)), i < 9 ? String(i + 1) : "", tag: i)
        })
        let windows = menu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = bar
        NSApp.windowsMenu = windows
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        if menu === statusItem?.menu {
            fillStatusMenu(menu)
            return
        }
        for item in menu.items {  // the app menu: the switches show their state
            if item.action == #selector(toggleMenuBar) {
                item.state = inMenuBar ? .on : .off
            }
            if #available(macOS 13, *), item.action == #selector(toggleLogin) {
                item.state = SMAppService.mainApp.status == .enabled ? .on : .off
            }
        }
    }

    @objc func goTab(_ sender: NSMenuItem) {
        showWindow()
        page("document.querySelector(`#tabs button[data-tab=\"${tab}\"]`)?.click()", ["tab": tabs[sender.tag].0])
    }

    @objc func search() {
        page("const s = document.querySelector('#gsearch'); s?.focus(); s?.select()")
    }

    @objc func zoom(_ sender: NSMenuItem) {
        let steps: [CGFloat] = [0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3]
        let now = web.pageZoom
        let next = sender.tag == 0 ? 1 : sender.tag > 0 ? (steps.first { $0 > now + 0.001 } ?? 3)
            : (steps.last { $0 < now - 0.001 } ?? 0.5)
        web.pageZoom = next
        defaults.set(Double(next), forKey: "zoom")
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

    @objc func toggleLogin() {
        guard #available(macOS 13, *) else { return }
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
            }
        } catch {
            let alert = NSAlert()
            alert.messageText = "Could not change Open at Login"
            alert.informativeText = "\(error.localizedDescription)\n\nAdd cc-profiles in System Settings → General → Login Items."
            alert.beginSheetModal(for: window)
        }
    }

    // MARK: the menu bar icon: recent projects, each opens in a terminal with Claude Code

    @objc func toggleMenuBar() {
        defaults.set(!inMenuBar, forKey: "menuBar")
        setMenuBar(inMenuBar)
    }

    func setMenuBar(_ on: Bool) {
        if on, statusItem == nil {
            statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
            statusItem?.button?.image = mascotImage()
            statusItem?.button?.toolTip = "cc-profiles"
            let menu = NSMenu()
            menu.delegate = self
            statusItem?.menu = menu
        } else if !on, let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
            statusItem = nil
            if !window.isVisible {
                NSApp.terminate(nil)
            }
        }
    }

    /// GET or POST to the server's API, waiting at most two seconds; the token comes from the page.
    /// Called from any thread.
    func api(_ path: String, _ body: [String: String]? = nil) -> Any? {
        func call(_ request: URLRequest) -> (Data?, HTTPURLResponse?) {
            var result: (Data?, HTTPURLResponse?) = (nil, nil)
            let done = DispatchSemaphore(value: 0)
            URLSession.shared.dataTask(with: request) { data, response, _ in
                result = (data, response as? HTTPURLResponse)
                done.signal()
            }.resume()
            _ = done.wait(timeout: .now() + 2)
            return result
        }
        tokenLock.lock()
        var token = self.token
        tokenLock.unlock()
        if token == nil, let html = call(URLRequest(url: home, timeoutInterval: 2)).0.map({ String(decoding: $0, as: UTF8.self) }),
           let range = html.range(of: #"const TOKEN = "([^"]+)""#, options: .regularExpression) {
            token = String(html[range].dropFirst(15).dropLast())
            tokenLock.lock()
            self.token = token
            tokenLock.unlock()
        }
        guard let token = token, let url = URL(string: path, relativeTo: home) else { return nil }
        var request = URLRequest(url: url, timeoutInterval: 2)
        request.setValue(token, forHTTPHeaderField: "X-Token")
        if let body = body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = call(request)
        if response?.statusCode == 403 {  // the server started again, with a new token
            tokenLock.lock()
            self.token = nil
            tokenLock.unlock()
        }
        return data.flatMap { try? JSONSerialization.jsonObject(with: $0) }
    }

    /// The ten most recent projects whose folder exists, and the profiles' names (from the server).
    func fetchRecent() -> (projects: [[String: Any]], labels: [String: String])? {
        guard let profiles = api("/api/profiles") as? [[String: Any]],
              let projects = api("/api/projects") as? [[String: Any]] else { return nil }
        let labels = Dictionary(profiles.compactMap { p in (p["id"] as? String).map { ($0, p["label"] as? String ?? $0) } },
                                uniquingKeysWith: { a, _ in a })
        let recent = projects.filter { ($0["exists"] as? Bool) == true }
            .sorted { ($0["last"] as? Double ?? 0) > ($1["last"] as? Double ?? 0) }
        return (Array(recent.prefix(10)), labels)
    }

    /// The Dock icon's menu cannot wait for the server: it shows what this keeps up to date.
    func refreshRecent() {
        DispatchQueue.global(qos: .utility).async {
            guard let fetched = self.fetchRecent() else { return }
            DispatchQueue.main.async {
                self.recent = fetched.projects
                self.labels = fetched.labels
            }
        }
    }

    /// The projects as menu items: one opens in its profile, one in several asks which.
    func addProjects(to menu: NSMenu, _ projects: [[String: Any]], _ labels: [String: String]) {
        guard !projects.isEmpty else { return }
        let title = NSMenuItem(title: "Open in a terminal, with Claude Code", action: nil, keyEquivalent: "")
        title.isEnabled = false
        menu.addItem(title)
        for project in projects {
            guard let name = project["name"] as? String, let pretty = project["pretty"] as? String else { continue }
            let ids = ((project["in"] as? [String: Any]) ?? [:]).keys.sorted()
            let item = NSMenuItem(title: pretty, action: nil, keyEquivalent: "")
            if ids.count == 1 {
                item.action = #selector(openTerminal(_:))
                item.representedObject = [name, ids[0]]
                item.toolTip = "In \(labels[ids[0]] ?? ids[0])"
            } else {
                let sub = NSMenu()
                for id in ids {
                    let choice = NSMenuItem(title: "In \(labels[id] ?? id)", action: #selector(openTerminal(_:)), keyEquivalent: "")
                    choice.representedObject = [name, id]
                    choice.target = self
                    sub.addItem(choice)
                }
                item.submenu = sub
            }
            item.target = self
            menu.addItem(item)
        }
    }

    func fillStatusMenu(_ menu: NSMenu) {
        menu.removeAllItems()
        let fetched = fetchRecent()
        if let fetched = fetched {
            recent = fetched.projects
            labels = fetched.labels
        }
        let header = NSMenuItem(title: fetched == nil ? "cc-profiles is not running"
                                : "cc-profiles is running on port \(launch?.port ?? 4777)", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        let open = NSMenuItem(title: "Open cc-profiles", action: #selector(openFromMenu), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        if let fetched = fetched, !fetched.projects.isEmpty {
            menu.addItem(.separator())
            addProjects(to: menu, fetched.projects, fetched.labels)
        }
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit cc-profiles", action: #selector(NSApplication.terminate(_:)), keyEquivalent: ""))
    }

    // MARK: the Dock icon's menu: the same recent projects (macOS adds its own items below)

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        refreshRecent()
        let menu = NSMenu()
        addProjects(to: menu, recent, labels)
        return menu.items.isEmpty ? nil : menu
    }

    @objc func openFromMenu() {
        showWindow()
    }

    @objc func openTerminal(_ sender: NSMenuItem) {
        guard let pair = sender.representedObject as? [String], pair.count == 2 else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let reply = self.api("/api/terminal/open", ["project": pair[0], "profile": pair[1]]) as? [String: Any]
            if let error = reply?["error"] as? String ?? (reply == nil ? "cc-profiles did not answer." : nil) {
                self.alert("Could not open the project", error)
            }
        }
    }

    // MARK: Finder → Quick Actions: a folder in a terminal with Claude Code, in the profile the
    // rules give it (as profile by folder does) or in one picked here

    @objc func openInClaude(_ pboard: NSPasteboard, userData: String?, error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        openFolders(pboard, pick: false)
    }

    @objc func openInClaudeWithProfile(_ pboard: NSPasteboard, userData: String?,
                                       error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        openFolders(pboard, pick: true)
    }

    func openFolders(_ pboard: NSPasteboard, pick: Bool) {
        let urls = pboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
        let folders = urls.filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }.map { $0.path }
        guard !folders.isEmpty else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            // the Quick Action may have just launched the app: give the server time to start
            var profiles: [[String: Any]]?
            for _ in 0..<20 {
                profiles = self.api("/api/profiles") as? [[String: Any]]
                if profiles != nil { break }
                Thread.sleep(forTimeInterval: 1)
            }
            guard let all = profiles else {
                return self.alert("Could not open the folder", "cc-profiles is not answering. Open the app and try again.")
            }
            DispatchQueue.main.async {
                var pid: String?
                if pick {
                    guard let chosen = self.askProfile(all, folders) else { return }
                    pid = chosen
                }
                DispatchQueue.global(qos: .userInitiated).async {
                    for folder in folders {
                        var body = ["path": folder]
                        body["profile"] = pid
                        let reply = self.api("/api/terminal/open", body) as? [String: Any]
                        if let error = reply?["error"] as? String ?? (reply == nil ? "cc-profiles did not answer." : nil) {
                            self.alert("Could not open \((folder as NSString).lastPathComponent)", error)
                        }
                    }
                }
            }
        }
    }

    /// The profile to open folders in, or nil when cancelled.
    func askProfile(_ profiles: [[String: Any]], _ folders: [String]) -> String? {
        let ids = profiles.compactMap { $0["id"] as? String }
        let popup = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 260, height: 26), pullsDown: false)
        popup.addItems(withTitles: profiles.map { ($0["label"] as? String) ?? ($0["id"] as? String ?? "") })
        let alert = NSAlert()
        alert.messageText = "Open in Claude Code"
        alert.informativeText = "Claude Code starts in \(folders.map { ($0 as NSString).abbreviatingWithTildeInPath }.joined(separator: ", ")), in the profile you pick."
        alert.accessoryView = popup
        alert.addButton(withTitle: "Open")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn, popup.indexOfSelectedItem < ids.count else { return nil }
        return ids[popup.indexOfSelectedItem]
    }

    /// An error, from any thread.
    func alert(_ title: String, _ detail: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = title
            alert.informativeText = detail
            NSApp.activate(ignoringOtherApps: true)
            alert.runModal()
        }
    }

    // MARK: closing: the window goes to the menu bar if the icon is there, else the app quits;
    // the server stops with the app if the app started it

    func windowWillClose(_ notification: Notification) {
        if inMenuBar {
            NSApp.setActivationPolicy(.accessory)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        !inMenuBar
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            showWindow()
        }
        return true
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
