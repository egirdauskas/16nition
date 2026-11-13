package org.ignition.launcher;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;

/** Android owns installation approval; the launcher only supplies its verified APK. */
final class GameInstaller {
    private GameInstaller() {}
    static void install(Context context) throws Exception {
        GamePreparation.verifyPrepared(context);
        File apk = GamePreparation.prepared(context);
        PackageInstaller installer = context.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams parameters = new PackageInstaller.SessionParams(
            PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        parameters.setAppPackageName(GameTrust.GAME);
        parameters.setSize(apk.length());
        int id = installer.createSession(parameters);
        context.getSharedPreferences("game-install", Context.MODE_PRIVATE).edit()
            .putInt("session", id).remove("error").commit();
        boolean committed = false;
        try (PackageInstaller.Session session = installer.openSession(id)) {
            try (FileInputStream input = new FileInputStream(apk);
                 OutputStream output = session.openWrite("game.apk", 0, apk.length())) {
                byte[] buffer = new byte[262144];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                session.fsync(output);
            }
            Intent callback = new Intent(context, GameInstallReceiver.class);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (android.os.Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
            PendingIntent result = PendingIntent.getBroadcast(context, id, callback, flags);
            session.commit(result.getIntentSender());
            committed = true;
        } finally {
            if (!committed) installer.abandonSession(id);
        }
    }
}
