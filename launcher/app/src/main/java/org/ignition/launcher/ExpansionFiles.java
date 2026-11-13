package org.ignition.launcher;

import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;
import java.util.ArrayList;

final class ExpansionFiles {
    private ExpansionFiles() {}
    static synchronized void prepareContent(Context context) throws Exception {
        com.chaquo.python.PyObject bridge = BackendHost.prepare(context).getModule("launcher_bridge");
        String directory = context.getFilesDir().getAbsolutePath();
        if (bridge.callAttr("content_ready", directory).toBoolean()) return;
        File selection = new File(context.getFilesDir(), "game-files.json");
        if (!selection.isFile()) throw new java.io.IOException(
            "Select the original main and patch OBB files in Setup → Import expansions.");
        JSONObject stored;
        try (InputStream input = new java.io.FileInputStream(selection)) {
            java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            stored = new JSONObject(output.toString("UTF-8"));
        }
        ArrayList<ParcelFileDescriptor> opened = new ArrayList<>();
        try {
            JSONObject paths = new JSONObject();
            java.util.Iterator<String> names = stored.keys();
            while (names.hasNext()) {
                String name = names.next();
                if (!name.startsWith("main.")) continue;
                ParcelFileDescriptor descriptor = context.getContentResolver().openFileDescriptor(
                    Uri.parse(stored.getString(name)), "r");
                if (descriptor == null) throw new java.io.IOException("Expansion unavailable: " + name);
                opened.add(descriptor);
                paths.put(name, descriptor.getFd());
            }
            // Keep descriptors alive while Python seeks directly in each OBB.
            // No extra 1.4 GB copy in launcher storage or whole-file RAM buffer.
            bridge.callAttr("prepare_expansions", directory, paths.toString());
        } finally {
            for (ParcelFileDescriptor descriptor : opened) descriptor.close();
        }
    }

    static synchronized void importSelection(Context context, Intent selection) throws Exception {
        File file = new File(context.getFilesDir(), "game-files.json");
        JSONObject result = new JSONObject();
        if (file.exists()) {
            try (InputStream input = new java.io.FileInputStream(file)) {
                java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                result = new JSONObject(output.toString("UTF-8"));
            }
        }
        int size = selection.getClipData() == null ? 1 : selection.getClipData().getItemCount();
        for (int index = 0; index < size; index++) {
            Uri uri = selection.getClipData() == null ? selection.getData() : selection.getClipData().getItemAt(index).getUri();
            String name;
            try (Cursor row = context.getContentResolver().query(uri,
                    new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                if (row == null || !row.moveToFirst()) throw new java.io.IOException("File name unavailable");
                name = row.getString(0);
            }
            String expected = GameAssets.allowed(name) ? GameVersions.expansionHash(context, name) : null;
            if (expected == null) throw new java.io.IOException("Select the original main and patch OBB files");
            context.getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = context.getContentResolver().openInputStream(uri)) {
                byte[] buffer = new byte[262144];
                int count;
                while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            }
            StringBuilder hash = new StringBuilder();
            for (byte value : digest.digest()) hash.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            if (!expected.equals(hash.toString())) throw new java.io.IOException("Expansion hash differs: " + name);
            result.put(name, uri.toString());
        }
        File temporary = new File(context.getFilesDir(), "game-files.json.new");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(result.toString().getBytes(StandardCharsets.UTF_8));
            output.getFD().sync();
        }
        if (!temporary.renameTo(file)) throw new java.io.IOException("Could not save expansion selection");
        java.util.Iterator<String> selected = result.keys();
        while (selected.hasNext()) {
            if (selected.next().startsWith("main.")) {
                prepareContent(context);
                break;
            }
        }
    }
}
