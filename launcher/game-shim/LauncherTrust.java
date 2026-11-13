package org.ignition.game;

import android.content.Context;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import java.security.MessageDigest;

/** Public launcher signing identity; no private signing material is embedded. */
final class LauncherTrust {
    private static final String CERTIFICATE = "c7bf3e41d0b1f68aaffc2dbda83498978b9d642947eafad7140eead49e2d1a60";
    static boolean trusted(Context context) {
        try {
            Signature[] signatures = context.getPackageManager().getPackageInfo(
                "org.ignition.launcher", PackageManager.GET_SIGNATURES).signatures;
            if (signatures == null || signatures.length != 1) return false;
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray());
            StringBuilder value = new StringBuilder();
            for (byte item : digest) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
            return CERTIFICATE.equals(value.toString());
        } catch (Exception error) { return false; }
    }
}
