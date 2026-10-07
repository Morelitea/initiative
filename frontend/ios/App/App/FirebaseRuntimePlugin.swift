import Capacitor
import Foundation

/// Says whether the connected server sends push notifications. On iOS there is no Firebase to
/// start: the server sends iPhone pushes through BeyondersStudio's push relay, which holds the
/// publisher's APNs key. The web layer registers the APNs token with the relay for that server and
/// tells the server only the handle the relay returns. The name and methods match the Android
/// plugin so the web layer calls one interface.
@objc(FirebaseRuntimePlugin)
public class FirebaseRuntimePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "FirebaseRuntimePlugin"
    public let jsName = "FirebaseRuntime"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "initialize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isInitialized", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearConfig", returnType: CAPPluginReturnPromise)
    ]

    private struct ServerConfig: Decodable {
        let enabled: Bool
    }

    // Read and written on the main queue only. Each check takes a number, and only the
    // latest one may change the answer, so a slow reply about a previous server cannot
    // overwrite the current one.
    private var serverSendsPush = false
    private var latestCheck = 0

    /// The APNs environment this build's tokens belong to, which the relay needs to send to them:
    /// a debug build is signed with the development entitlement and registers in the sandbox.
    private static var apnsEnvironment: String {
        #if DEBUG
        return "sandbox"
        #else
        return "production"
        #endif
    }

    @objc func initialize(_ call: CAPPluginCall) {
        guard let serverUrl = call.getString("serverUrl"), !serverUrl.isEmpty else {
            call.reject("Server URL is required")
            return
        }
        let base = serverUrl.hasSuffix("/") ? String(serverUrl.dropLast()) : serverUrl
        guard let url = URL(string: base + "/settings/fcm-config"), url.scheme == "https" else {
            call.resolve(["success": false, "message": "Push notifications need an https server"])
            return
        }

        DispatchQueue.main.async {
            self.latestCheck += 1
            let check = self.latestCheck
            URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
                var sendsPush = false
                if error == nil,
                   let status = (response as? HTTPURLResponse)?.statusCode, status == 200,
                   let data = data,
                   let config = try? JSONDecoder().decode(ServerConfig.self, from: data) {
                    sendsPush = config.enabled
                }
                DispatchQueue.main.async {
                    guard let self = self, check == self.latestCheck else {
                        call.resolve(["success": false, "message": "A newer check replaced this one"])
                        return
                    }
                    self.serverSendsPush = sendsPush
                    if sendsPush {
                        call.resolve(["success": true, "apnsEnvironment": Self.apnsEnvironment])
                    } else {
                        call.resolve(["success": false, "message": "Push notifications are off on this server"])
                    }
                }
            }.resume()
        }
    }

    @objc func isInitialized(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            call.resolve(["initialized": self.serverSendsPush])
        }
    }

    /// Nothing is stored between launches: the server is asked again on each one.
    @objc func clearConfig(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.latestCheck += 1
            self.serverSendsPush = false
            call.resolve(["success": true])
        }
    }
}
