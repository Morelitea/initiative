import Capacitor
import FirebaseCore
import Foundation

/// Turns on Firebase for push notifications when the connected server uses the Firebase project
/// this build was made for.
///
/// Apple delivers pushes to this app only from a Firebase project that holds the publisher's APNs
/// key, so iOS push works with the servers that share the bundled `GoogleService-Info.plist`'s
/// project and with no others. Any other server reports push as unavailable, and the app falls
/// back to email and in-app notifications, as it does without push.
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
        let projectId: String?

        enum CodingKeys: String, CodingKey {
            case enabled
            case projectId = "project_id"
        }
    }

    @objc func initialize(_ call: CAPPluginCall) {
        guard let serverUrl = call.getString("serverUrl"), !serverUrl.isEmpty else {
            call.reject("Server URL is required")
            return
        }
        guard let options = Self.bundledOptions() else {
            call.resolve(["success": false, "message": "Push notifications are not set up in this build"])
            return
        }
        let base = serverUrl.hasSuffix("/") ? String(serverUrl.dropLast()) : serverUrl
        guard let url = URL(string: base + "/settings/fcm-config"), url.scheme == "https" else {
            call.resolve(["success": false, "message": "Push notifications need an https server"])
            return
        }

        URLSession.shared.dataTask(with: url) { data, response, error in
            guard error == nil,
                  let status = (response as? HTTPURLResponse)?.statusCode, status == 200,
                  let data = data,
                  let config = try? JSONDecoder().decode(ServerConfig.self, from: data) else {
                call.resolve(["success": false, "message": "Could not read the server's push settings"])
                return
            }
            guard config.enabled else {
                call.resolve(["success": false, "message": "FCM not enabled on the server"])
                return
            }
            guard config.projectId == options.projectID else {
                call.resolve(["success": false, "message": "Push notifications on iPhone need a server using this app's Firebase project"])
                return
            }
            DispatchQueue.main.async {
                if FirebaseApp.app() == nil {
                    FirebaseApp.configure(options: options)
                }
                call.resolve(["success": true])
            }
        }.resume()
    }

    @objc func isInitialized(_ call: CAPPluginCall) {
        call.resolve(["initialized": FirebaseApp.app() != nil])
    }

    /// Nothing is stored between launches: the server is asked again on each one.
    @objc func clearConfig(_ call: CAPPluginCall) {
        call.resolve(["success": true])
    }

    private static func bundledOptions() -> FirebaseOptions? {
        guard let path = Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") else {
            return nil
        }
        return FirebaseOptions(contentsOfFile: path)
    }
}
