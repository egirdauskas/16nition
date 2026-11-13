package org.ignition.launcher;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import org.json.JSONObject;

/**
 * Supported original FIFA 16 builds (server/data/ignition-game-versions-v1.json).
 * Originals are admitted by package, EA signing certificate and versionCode,
 * not by a whole-file hash; the patch bundle still pins exact member bytes.
 */
final class GameVersions {
    private static volatile JSONObject cached;
    private GameVersions() {}

    static JSONObject policy(Context context) throws Exception {
        JSONObject value = cached;
        if (value == null) {
            String raw = BackendHost.prepare(context).getModule("launcher_bridge")
                .callAttr("game_versions", context.getFilesDir().getAbsolutePath()).toString();
            value = new JSONObject(raw);
            cached = value;
        }
        return value;
    }

    /** Policy entry for an original versionCode, or null when unsupported. */
    static JSONObject entry(Context context, int versionCode) throws Exception {
        return policy(context).getJSONObject("versions").optJSONObject(Integer.toString(versionCode));
    }

    /** Expected SHA256 of a supported expansion file name, or null. */
    static String expansionHash(Context context, String name) throws Exception {
        JSONObject versions = policy(context).getJSONObject("versions");
        java.util.Iterator<String> codes = versions.keys();
        while (codes.hasNext()) {
            JSONObject expansions = versions.getJSONObject(codes.next()).getJSONObject("expansions");
            if (expansions.has(name)) return expansions.getString(name);
        }
        return null;
    }

    /** True when versionCode is one this launcher produces for a prepared game. */
    static boolean preparedVersion(Context context, int versionCode) throws Exception {
        JSONObject versions = policy(context).getJSONObject("versions");
        java.util.Iterator<String> codes = versions.keys();
        while (codes.hasNext()) {
            if (versions.getJSONObject(codes.next()).getInt("output_version_code") == versionCode) return true;
        }
        return false;
    }

    /** The supported original identity of an archive or installed package, or null. */
    static JSONObject original(Context context, PackageInfo info) throws Exception {
        if (info == null || !GameTrust.GAME.equals(info.packageName)
                || info.signatures == null || info.signatures.length != 1) {
            return null;
        }
        String signer = GameSigning.digest(info.signatures[0].toByteArray());
        if (!policy(context).getString("signer_sha256").equals(signer)) return null;
        return entry(context, info.versionCode);
    }

    /** Verifies every v1 entry via the platform parser before reading the signer. */
    static JSONObject archive(Context context, java.io.File apk) throws Exception {
        PackageInfo info = context.getPackageManager().getPackageArchiveInfo(
            apk.getAbsolutePath(), PackageManager.GET_SIGNATURES);
        return original(context, info);
    }

    /** Supported original installed from EA (not a prepared local copy), or null. */
    static JSONObject installed(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(
                GameTrust.GAME, PackageManager.GET_SIGNATURES);
            return original(context, info);
        } catch (Exception absent) {
            return null;
        }
    }
}
