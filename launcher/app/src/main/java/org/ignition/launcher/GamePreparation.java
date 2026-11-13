package org.ignition.launcher;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import com.chaquo.python.PyObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Original input stays unchanged; only verified, locally signed output is installed. */
final class GamePreparation {
    static volatile boolean busy;
    static volatile String progress = "";
    private GamePreparation() {}

    static File directory(Context context) { return new File(context.getFilesDir(), "game-install"); }
    static File prepared(Context context) { return new File(directory(context), "game.apk"); }

    static String hash(File path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(path)) {
            byte[] buffer = new byte[262144];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder value = new StringBuilder();
        for (byte item : digest.digest()) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }

    static JSONObject record(Context context) throws Exception {
        File path = new File(directory(context), "prepared.json");
        if (!path.isFile() || !prepared(context).isFile()) return null;
        try (InputStream input = new FileInputStream(path)) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                bytes.write(buffer, 0, count);
                if (bytes.size() > 65536) throw new java.io.IOException("Game receipt exceeds limit");
            }
            return new JSONObject(bytes.toString("UTF-8"));
        }
    }

    private static void save(Context context, JSONObject record) throws Exception {
        File temporary = new File(directory(context), "prepared.json.new");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(record.toString().getBytes(StandardCharsets.UTF_8));
            output.getFD().sync();
        }
        if (!temporary.renameTo(new File(directory(context), "prepared.json"))) {
            throw new java.io.IOException("Could not save game preparation");
        }
    }

    static void prepare(Context context, Uri uri) throws Exception {
        prepare(context, context.getContentResolver().openInputStream(uri));
    }

    static void prepareInstalled(Context context) throws Exception {
        File apk = new File(context.getPackageManager().getApplicationInfo(GameTrust.GAME, 0).sourceDir);
        prepare(context, new FileInputStream(apk));
    }

    private static synchronized void prepare(Context context, InputStream input) throws Exception {
        if (input == null) throw new java.io.IOException("Original APK unavailable");
        if (busy) {
            input.close();
            throw new java.io.IOException("Game preparation is already running");
        }
        busy = true;
        File directory = directory(context);
        directory.mkdirs();
        File original = new File(directory, "original.apk.new");
        File signed = new File(directory, "game.apk.new");
        File unsigned = new File(directory, "unsigned.apk");
        try (InputStream source = input) {
            if (directory.getUsableSpace() < 128L * 1024 * 1024) {
                throw new java.io.IOException("At least 128 MB of free storage is needed");
            }
            progress = "Copying original APK…";
            try (FileOutputStream output = new FileOutputStream(original)) {
                byte[] buffer = new byte[262144];
                int count;
                long size = 0;
                while ((count = source.read(buffer)) != -1) {
                    size += count;
                    if (size > 128L * 1024 * 1024) throw new java.io.IOException("Unsupported original APK");
                    output.write(buffer, 0, count);
                }
                output.getFD().sync();
            }
            progress = "Checking original APK…";
            PackageInfo archive = context.getPackageManager().getPackageArchiveInfo(
                original.getAbsolutePath(), PackageManager.GET_SIGNATURES);
            JSONObject version = GameVersions.original(context, archive);
            if (version == null) throw new java.io.IOException("Select a supported original FIFA 16 APK");
            progress = "Preparing game " + version.getString("version_name") + "…";
            PyObject bridge = BackendHost.prepare(context).getModule("launcher_bridge");
            JSONObject result = new JSONObject(bridge.callAttr("prepare_game",
                context.getFilesDir().getAbsolutePath(), original.getAbsolutePath(),
                archive.versionCode).toString());
            progress = "Signing game…";
            GameSigning.sign(unsigned, signed);
            PackageInfo info = context.getPackageManager().getPackageArchiveInfo(signed.getAbsolutePath(),
                PackageManager.GET_META_DATA);
            if (info == null || !GameTrust.GAME.equals(info.packageName)
                    || info.versionCode != version.getInt("output_version_code")
                    || info.applicationInfo.metaData == null
                    || info.applicationInfo.metaData.getInt("org.ignition.route.version") != 1) {
                throw new java.io.IOException("Prepared game identity differs");
            }
            result.put("apk_sha256", hash(signed));
            result.put("apk_bytes", signed.length());
            result.put("certificate_sha256", GameSigning.digest(GameSigning.certificate(false).getEncoded()));
            try (FileInputStream ready = new FileInputStream(signed)) { ready.getFD().sync(); }
            if (!signed.renameTo(prepared(context))) throw new java.io.IOException("Could not publish prepared game");
            save(context, result);
            progress = "Game ready to install";
        } finally {
            busy = false;
            original.delete();
            unsigned.delete();
            signed.delete();
        }
    }

    static void verifyPrepared(Context context) throws Exception {
        PyObject bridge = BackendHost.prepare(context).getModule("launcher_bridge");
        JSONObject record = record(context);
        java.security.cert.X509Certificate certificate = GameSigning.certificate(false);
        // Records from before multi-version support carry no source version: v26 -> 34.
        int source = record == null ? -1 : record.optInt("source_version_code", 26);
        JSONObject version = source < 0 ? null : GameVersions.entry(context, source);
        if (record == null || certificate == null || version == null
                || record.getInt("version") != version.getInt("output_version_code")
                || !hash(prepared(context)).equals(record.getString("apk_sha256"))
                || prepared(context).length() != record.getLong("apk_bytes")
                || !bridge.callAttr("game_recipe_accepts", context.getFilesDir().getAbsolutePath(),
                    record.toString()).toBoolean()
                || !GameSigning.digest(certificate.getEncoded())
                    .equals(record.getString("certificate_sha256"))) {
            throw new java.io.IOException("Prepare the original game APK first");
        }
    }
}
