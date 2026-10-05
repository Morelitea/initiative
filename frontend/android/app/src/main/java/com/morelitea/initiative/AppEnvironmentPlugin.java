package com.morelitea.initiative;

import android.content.pm.PackageManager;
import android.os.Build;
import android.security.NetworkSecurityPolicy;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Facts about this install that the web layer cannot see: which app installed it (Google Play
 * is "com.android.vending"), so an update prompt can send a Play install to Play, and whether
 * this build may reach plain-HTTP servers, which only a debug build does.
 */
@CapacitorPlugin(name = "AppEnvironment")
public class AppEnvironmentPlugin extends Plugin {

    @PluginMethod
    public void get(PluginCall call) {
        JSObject result = new JSObject();
        String installer = installerPackage();
        if (installer != null) {
            result.put("installer", installer);
        }
        result.put("cleartextPermitted", NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted());
        call.resolve(result);
    }

    @SuppressWarnings("deprecation")
    private String installerPackage() {
        PackageManager packageManager = getContext().getPackageManager();
        String packageName = getContext().getPackageName();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                return packageManager.getInstallSourceInfo(packageName).getInstallingPackageName();
            }
            return packageManager.getInstallerPackageName(packageName);
        } catch (PackageManager.NameNotFoundException | IllegalArgumentException e) {
            return null;
        }
    }
}
