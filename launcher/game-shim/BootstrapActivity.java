package org.ignition.game;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Local startup/configuration only. Original engine, screens and assets are unchanged. */
public final class BootstrapActivity extends Activity {
    private TextView status;
    private boolean preparing;
    private boolean permissionPending;
    private static final String LAUNCHER = "org.ignition.launcher";
    private static final String GAME = "com.ea.gp.fifaworld.fifa";
    private static final String[] EXPANSIONS = {
        "main.13.com.ea.gp.fifaworld.obb", "patch.26.com.ea.gp.fifaworld.obb"
    };
    private static final String[] HASHES = {
        "fe3e66c5e8c804656d8ee9ca62ace64a1fe968669f5c397b23ce174b0b8c720c",
        "bdca1604e7fc8dc80d96d6d56ae0e21ff3bd1cdf75a62ecaab0109dd269ef38a"
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        begin();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        begin();
    }

    private void begin() {
        if (preparing || permissionPending) return;
        if (!LauncherTrust.trusted(this)) {
            status = new TextView(this);
            status.setText("Install the original Ignition launcher.");
            setContentView(status);
            return;
        }
        if (!getIntent().getBooleanExtra("ignition.ready", false)) {
            startActivity(new Intent("org.ignition.PLAY").setClassName(LAUNCHER,
                LAUNCHER + ".MainActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
            return;
        }
        android.app.Activity existing = GameApplication.game.get();
        if (existing != null && !existing.isFinishing() && !existing.isDestroyed()) {
            startActivity(new Intent().setClassName(getPackageName(), GAME)
                .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            finish();
            return;
        }
        status = new TextView(this);
        status.setText("Preparing game…");
        status.setPadding(24, 24, 24, 24);
        status.setTextSize(18);
        setContentView(status);
        String[] permissions = {android.Manifest.permission.READ_EXTERNAL_STORAGE,
            android.Manifest.permission.WRITE_EXTERNAL_STORAGE};
        for (String permission : permissions) {
            if (checkSelfPermission(permission) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                permissionPending = true;
                requestPermissions(permissions, 101);
                return;
            }
        }
        prepareGame();
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(request, permissions, grants);
        if (request != 101) return;
        permissionPending = false;
        if (grants.length != 2 || grants[0] != android.content.pm.PackageManager.PERMISSION_GRANTED
                || grants[1] != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            status.setText("Storage permission is required by the original game.");
            return;
        }
        prepareGame();
    }

    private void prepareGame() {
        if (preparing) return;
        preparing = true;
        new Thread(() -> {
            try {
                if (!LoopbackNetwork.verify()) throw new java.io.IOException("Server unavailable");
                for (int index = 0; index < EXPANSIONS.length; index++) copyExpansion(index);
                writeConfiguration();
                runOnUiThread(() -> {
                    preparing = false;
                    startActivity(new Intent().setClassName(getPackageName(), GAME));
                    finish();
                });
            } catch (Exception error) {
                android.util.Log.e("IgnitionGame", "Startup failed", error);
                runOnUiThread(() -> {
                    preparing = false;
                    status.setText(error.getMessage());
                });
            }
        }, "ignition-setup").start();
    }

    private void copyExpansion(int index) throws Exception {
        File directory = getObbDir();
        if (!directory.exists() && !directory.mkdirs()) throw new java.io.IOException("Expansion folder unavailable");
        File target = new File(directory, EXPANSIONS[index]);
        android.content.SharedPreferences checks = getSharedPreferences("ignition-files", MODE_PRIVATE);
        String signature = target.length() + ":" + target.lastModified();
        if (target.isFile() && signature.equals(checks.getString(EXPANSIONS[index], ""))) return;
        if (target.isFile() && HASHES[index].equals(hash(target))) {
            checks.edit().putString(EXPANSIONS[index], signature).commit();
            return;
        }
        File temporary = new File(directory, EXPANSIONS[index] + ".ignition-new");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        runOnUiThread(() -> status.setText("Copying " + EXPANSIONS[index]));
        android.net.Uri uri = android.net.Uri.parse("content://org.ignition.launcher.assets/expansions/" + EXPANSIONS[index]);
        try (InputStream source = getContentResolver().openInputStream(uri);
             FileOutputStream output = new FileOutputStream(temporary)) {
            byte[] buffer = new byte[262144];
            int count;
            while ((count = source.read(buffer)) != -1) {
                output.write(buffer, 0, count);
                digest.update(buffer, 0, count);
            }
            output.getFD().sync();
        }
        if (!HASHES[index].equals(hex(digest.digest()))) {
            temporary.delete();
            throw new java.io.IOException("Expansion hash differs: " + EXPANSIONS[index]);
        }
        if (target.exists() && !target.renameTo(new File(directory, target.getName() + ".before-ignition"))) {
            throw new java.io.IOException("Existing expansion could not be preserved");
        }
        if (!temporary.renameTo(target)) throw new java.io.IOException("Expansion copy failed");
        checks.edit().putString(EXPANSIONS[index], target.length() + ":" + target.lastModified()).commit();
    }

    private static String hash(File path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream source = new java.io.FileInputStream(path)) {
            byte[] buffer = new byte[262144];
            int count;
            while ((count = source.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest());
    }

    private static String hex(byte[] value) {
        StringBuilder result = new StringBuilder();
        for (byte item : value) result.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return result.toString();
    }

    private void writeConfiguration() throws Exception {
        String ini = "[FUT]\nRS4_BASE_URL=\"http://127.0.0.1:18081/\"\n\n"
            + "[ONLINE]\nSERVERS=\"http://127.0.0.1:18081/victory_fwm_s2\"\n"
            + "CONTENT_URL=\"http://127.0.0.1:18081/\"\n"
            + "CHALLENGE_PATH_LOC_TEXT=\"loc/%s/Challenges.xml\"\n"
            + "CHALLENGE_CATEGORY_PATH_TILE_ASSET=\"accomplishments/tiles/tile.png\"\n"
            + "CHALLENGE_PATH_BADGE_ASSET=\"accomplishments/badges/badge.png\"\n";
        File folder = getExternalFilesDir(null).getParentFile();
        File target = new File(folder, "user.ini");
        byte[] bytes = ini.getBytes(StandardCharsets.UTF_8);
        if (target.isFile() && java.util.Arrays.equals(bytes, read(target))) return;
        if (target.isFile()) {
            File archive = new File(getFilesDir(), "ignition-config-backups");
            archive.mkdirs();
            File backup = new File(archive, hash(target) + ".ini");
            if (!backup.exists()) {
                try (FileOutputStream output = new FileOutputStream(backup)) { output.write(read(target)); }
            }
        }
        File temporary = new File(folder, "user.ini.ignition-new");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(bytes);
            output.getFD().sync();
        }
        if (!temporary.renameTo(target)) throw new java.io.IOException("Local configuration failed");
    }

    private static byte[] read(File file) throws Exception {
        try (InputStream input = new java.io.FileInputStream(file);
             java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }
}
