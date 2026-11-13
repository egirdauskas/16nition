package org.ignition.launcher;

import android.app.Service;
import android.content.Intent;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;

/** Authenticated Binder keeps locally signed games bound to the backend process. */
public final class GameSessionService extends Service {
    private final Binder session = new Binder() {
        @Override protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) {
            if (code != 1) return false;
            data.enforceInterface("org.ignition.game.session");
            GameTrust.enforceCaller(GameSessionService.this);
            long identity = Binder.clearCallingIdentity();
            try {
                Intent start = new Intent(GameSessionService.this, LocalBackendService.class);
                if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(start);
                else startService(start);
            } finally { Binder.restoreCallingIdentity(identity); }
            reply.writeNoException();
            return true;
        }
    };

    @Override public IBinder onBind(Intent intent) { return session; }
}
