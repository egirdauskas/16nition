package org.ignition.launcher;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class LocalBackendService extends Service {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final IBinder connection = new android.os.Binder();

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        Notification.Builder builder;
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(new NotificationChannel(
                "local-server", "Offline game server", NotificationManager.IMPORTANCE_LOW));
            builder = new Notification.Builder(this, "local-server");
        } else {
            builder = new Notification.Builder(this);
        }
        PendingIntent open = PendingIntent.getActivity(this, 0,
            new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = builder
            .setSmallIcon(R.mipmap.ic_launcher).setContentTitle("16NITION")
            .setContentText("Local server")
            .setContentIntent(open).setOngoing(true).build();
        startForeground(16, notification);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        boolean stop = intent != null && "stop".equals(intent.getAction());
        submit(stop);
        return stop ? START_NOT_STICKY : START_STICKY;
    }

    private void submit(boolean stop) {
        worker.execute(() -> {
            try {
                com.chaquo.python.PyObject bridge = BackendHost.prepare(this)
                    .getModule("launcher_bridge");
                if (stop) {
                    bridge.callAttr("stop");
                    stopForeground(STOP_FOREGROUND_REMOVE);
                    stopSelf();
                } else {
                    ExpansionFiles.prepareContent(this);
                    bridge.callAttr("start", getFilesDir().getAbsolutePath());
                }
            } catch (Exception error) {
                android.util.Log.e("16NITION", "Local server startup failed", error);
                BackendHost.lastError = error.getMessage();
                stopForeground(STOP_FOREGROUND_REMOVE);
                stopSelf();
            }
        });
    }

    @Override public void onDestroy() {
        worker.execute(() -> {
            if (com.chaquo.python.Python.isStarted()) {
                com.chaquo.python.Python.getInstance().getModule("launcher_bridge").callAttr("stop");
            }
        });
        worker.shutdown();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        submit(false);
        return connection;
    }
}
