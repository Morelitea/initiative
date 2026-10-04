import Capacitor
import WebKit

/// The app's bridge view controller. It registers the app's own plugins and hands the bridge
/// only messages posted by the app's top-level page.
class MainViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(FirebaseRuntimePlugin())

        guard let handler = (bridge as? CapacitorBridge)?.webViewDelegationHandler else {
            return
        }
        let contentController = handler.contentController
        contentController.removeScriptMessageHandler(forName: MainFrameOnlyMessageHandler.name)
        contentController.add(MainFrameOnlyMessageHandler(handler), name: MainFrameOnlyMessageHandler.name)
    }
}

/// Passes on the bridge messages that come from the main frame, and drops those from any frame
/// embedded in the page, so embedded content has no way to call the app's plugins.
final class MainFrameOnlyMessageHandler: NSObject, WKScriptMessageHandler {
    /// The message handler name Capacitor's bridge script posts to.
    static let name = "bridge"

    private let inner: WKScriptMessageHandler

    init(_ inner: WKScriptMessageHandler) {
        self.inner = inner
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame else {
            return
        }
        inner.userContentController(userContentController, didReceive: message)
    }
}
