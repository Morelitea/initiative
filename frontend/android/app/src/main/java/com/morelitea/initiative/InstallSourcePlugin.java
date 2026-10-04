package com.morelitea.initiative;

import android.content.pm.PackageManager;
import android.os.Build;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Says which app installed this one (Google Play is "com.android.vending"), so an update
 * prompt can send a Play install to Play and a downloaded APK to the next APK.
 */
@CapacitorPlugin(name = "InstallSource")
public class InstallSourcePlugin extends Plugin {

    @PluginMethod
    public void get(PluginCall call) {
        JSObject result = new JSObject();
        String installer = installerPackage();
        if (installer != null) {
            result.put("installer", installer);
        }
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
