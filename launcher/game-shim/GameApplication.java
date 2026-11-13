package org.ignition.game;

import android.app.Activity;
import android.app.Application;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.IBinder;
import java.lang.ref.WeakReference;

/** Keep the local backend at the active game's priority and close only our own Activity. */
public final class GameApplication extends Application implements Application.ActivityLifecycleCallbacks {
    static WeakReference<Activity> game = new WeakReference<>(null);
    private boolean bound;
    private final android.os.Handler handler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable reconnect = this::bindBackend;
    private final ServiceConnection backend = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            android.os.Parcel data = android.os.Parcel.obtain();
            android.os.Parcel reply = android.os.Parcel.obtain();
            try {
                data.writeInterfaceToken("org.ignition.game.session");
                if (!binder.transact(1, data, reply, 0)) throw new SecurityException("Backend handshake unavailable");
                reply.readException();
            } catch (Exception error) {
                android.util.Log.e("IgnitionGame", "Backend handshake failed", error);
            } finally {
                data.recycle();
                reply.recycle();
            }
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            // Android reconnects this live binding when the service restarts.
        }
        @Override public void onBindingDied(ComponentName name) {
            if (bound) unbindService(this);
            bound = false;
            if (game.get() != null) bindBackend();
        }
    };

    private void bindBackend() {
        handler.removeCallbacks(reconnect);
        if (bound || game.get() == null) return;
        try {
            if (!LauncherTrust.trusted(this)) throw new SecurityException("Install the original Ignition launcher");
            bound = bindService(new Intent().setClassName("org.ignition.launcher",
                "org.ignition.launcher.GameSessionService"), backend,
                BIND_AUTO_CREATE | BIND_IMPORTANT);
            if (!bound) android.util.Log.e("IgnitionGame", "Backend binding unavailable");
        } catch (Exception error) {
            android.util.Log.e("IgnitionGame", "Backend binding failed", error);
        }
        if (!bound) handler.postDelayed(reconnect, 1000);
    }
    @Override public void onCreate() {
        super.onCreate();
        registerActivityLifecycleCallbacks(this);
    }
    @Override public void onActivityCreated(Activity activity, Bundle state) {
        if (activity.getClass().getName().equals("com.ea.gp.fifaworld.fifa")) {
            game = new WeakReference<>(activity);
            bindBackend();
        }
    }
    @Override public void onActivityDestroyed(Activity activity) {
        if (game.get() == activity) {
            game.clear();
            handler.removeCallbacks(reconnect);
            if (bound) unbindService(backend);
            bound = false;
        }
    }
    @Override public void onActivityStarted(Activity activity) {}
    @Override public void onActivityResumed(Activity activity) {}
    @Override public void onActivityPaused(Activity activity) {}
    @Override public void onActivityStopped(Activity activity) {}
    @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) {}
}
