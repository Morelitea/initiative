package com.morelitea.initiative;

import android.os.Bundle;
import android.view.View;
import androidx.core.view.ViewCompat;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Register custom plugins BEFORE super.onCreate() so they're available to the bridge
        registerPlugin(FirebaseRuntimePlugin.class);

        // Switch from splash theme to main theme with edge-to-edge attributes
        setTheme(R.style.AppTheme_NoActionBar);
        super.onCreate(savedInstanceState);

        // Clear the built-in Capacitor SystemBars plugin's inset listener on the WebView parent.
        // Both SystemBars (CoordinatorLayout padding) and @capacitor-community/safe-area (decor
        // view padding) apply bottom insets, causing a double offset when the keyboard opens.
        // The safe-area plugin handles all inset management, so remove the built-in one.
        View webViewParent = (View) getBridge().getWebView().getParent();
        ViewCompat.setOnApplyWindowInsetsListener(webViewParent, null);
        webViewParent.requestApplyInsets();

        // Create notification channels for push notifications
        NotificationChannelManager.createNotificationChannels(this);
    }
}
