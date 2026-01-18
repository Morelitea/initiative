package com.morelitea.initiative;

import android.os.Bundle;
import androidx.activity.EdgeToEdge;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Switch from splash theme to main theme with edge-to-edge attributes
        setTheme(R.style.AppTheme_NoActionBar);
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);

        // Register custom Firebase runtime plugin
        registerPlugin(FirebaseRuntimePlugin.class);

        // Create notification channels for push notifications
        NotificationChannelManager.createNotificationChannels(this);
    }
}
