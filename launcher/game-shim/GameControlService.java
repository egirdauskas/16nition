package org.ignition.game;

import android.app.Activity;
import android.app.Service;
import android.content.Intent;
import android.os.Binder;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;

/** Same-signature launcher control; Binder death confirms this process stopped. */
public final class GameControlService extends Service {
    private final Binder control = new Binder() {
        @Override protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) {
            if (code != 1) return false;
            data.enforceInterface("org.ignition.game.control");
            new Handler(Looper.getMainLooper()).post(() -> {
                Activity game = GameApplication.game.get();
                if (game != null) game.finish();
                new Handler(Looper.getMainLooper()).postDelayed(() ->
                    android.os.Process.killProcess(android.os.Process.myPid()), 150);
            });
            return true;
        }
    };

    @Override public IBinder onBind(Intent intent) { return control; }
}
