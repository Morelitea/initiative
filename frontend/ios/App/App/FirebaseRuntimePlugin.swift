import Capacitor
import Foundation

/// Says whether the connected server sends push notifications. On iOS there is no Firebase to
/// start: the app registers its APNs token with the server, and the server sends iPhone pushes
/// through Morelitea's push relay, which holds the publisher's APNs key. The name and methods
/// match the Android plugin so the web layer calls one interface.
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

    private var serverSendsPush = false

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

        URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
            guard error == nil,
                  let status = (response as? HTTPURLResponse)?.statusCode, status == 200,
                  let data = data,
                  let config = try? JSONDecoder().decode(ServerConfig.self, from: data) else {
                self?.serverSendsPush = false
                call.resolve(["success": false, "message": "Could not read the server's push settings"])
                return
            }
            self?.serverSendsPush = config.enabled
            if config.enabled {
                call.resolve(["success": true])
            } else {
                call.resolve(["success": false, "message": "Push notifications are off on this server"])
            }
        }.resume()
    }

    @objc func isInitialized(_ call: CAPPluginCall) {
        call.resolve(["initialized": serverSendsPush])
    }

    /// Nothing is stored between launches: the server is asked again on each one.
    @objc func clearConfig(_ call: CAPPluginCall) {
        serverSendsPush = false
        call.resolve(["success": true])
    }
}
