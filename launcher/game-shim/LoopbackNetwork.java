package org.ignition.game;

import android.os.SystemClock;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Availability of the actual on-device server, independent of Internet access. */
public final class LoopbackNetwork {
    private static volatile boolean reachable;
    private static volatile long checkedAt;
    private static final AtomicBoolean checking = new AtomicBoolean();
    private static final ExecutorService worker = Executors.newSingleThreadExecutor(action -> {
        Thread thread = new Thread(action, "ignition-network");
        thread.setDaemon(true);
        return thread;
    });
    private LoopbackNetwork() {}

    public static synchronized boolean verify() {
        HttpURLConnection connection = null;
        boolean success = false;
        try {
            connection = (HttpURLConnection)new URL("http://127.0.0.1:18081/").openConnection();
            connection.setConnectTimeout(1500);
            connection.setReadTimeout(1500);
            connection.setUseCaches(false);
            success = connection.getResponseCode() == 200;
        } catch (Exception unavailable) {
            success = false;
        } finally {
            if (connection != null) connection.disconnect();
        }
        reachable = success;
        checkedAt = SystemClock.elapsedRealtime();
        return success;
    }

    public static int connectionType() {
        // Keep network I/O off the UI thread. Bootstrap verifies synchronously
        // on its worker before starting the original Activity; later queries
        // refresh the last real result, at most once every five seconds.
        if (SystemClock.elapsedRealtime() - checkedAt >= 5000 && checking.compareAndSet(false, true)) {
            worker.execute(() -> {
                try { verify(); } finally { checking.set(false); }
            });
        }
        return reachable ? android.net.ConnectivityManager.TYPE_ETHERNET : -1;
    }
}
