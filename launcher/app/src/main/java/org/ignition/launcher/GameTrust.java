package org.ignition.launcher;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Binder;
import java.security.cert.X509Certificate;

/** Admit our legacy game or the copy signed by this install's private key. */
final class GameTrust {
    static final String GAME = "com.ea.gp.fifaworld";
    private GameTrust() {}

    static boolean localSignature(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(GAME, PackageManager.GET_SIGNATURES);
            X509Certificate local = GameSigning.certificate(false);
            return local != null && info.signatures.length == 1
                && GameSigning.digest(info.signatures[0].toByteArray())
                    .equals(GameSigning.digest(local.getEncoded()));
        } catch (Exception absent) { return false; }
    }

    static boolean paired(Context context) {
        try {
            PackageManager manager = context.getPackageManager();
            PackageInfo info = manager.getPackageInfo(GAME,
                PackageManager.GET_SIGNATURES | PackageManager.GET_META_DATA);
            if (info.applicationInfo.metaData == null
                    || info.applicationInfo.metaData.getInt("org.ignition.route.version") != 1) return false;
            if (manager.checkSignatures(context.getPackageName(), GAME) == PackageManager.SIGNATURE_MATCH) return true;
            X509Certificate local = GameSigning.certificate(false);
            return local != null && GameVersions.preparedVersion(context, info.versionCode)
                && info.signatures.length == 1
                && GameSigning.digest(info.signatures[0].toByteArray())
                    .equals(GameSigning.digest(local.getEncoded()));
        } catch (Exception absent) { return false; }
    }

    static void enforceCaller(Context context) {
        try {
            int uid = context.getPackageManager().getApplicationInfo(GAME, 0).uid;
            if (Binder.getCallingUid() == uid && paired(context)) return;
        } catch (PackageManager.NameNotFoundException absent) { }
        throw new SecurityException("Unpaired game caller");
    }
}
