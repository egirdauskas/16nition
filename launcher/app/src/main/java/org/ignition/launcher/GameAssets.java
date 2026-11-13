package org.ignition.launcher;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import org.json.JSONObject;

/** Only the paired legacy/local game can read selected expansion files. */
public final class GameAssets extends ContentProvider {
    /** Shape only; the hash of every selected file was checked against policy at import. */
    static boolean allowed(String name) {
        return name != null && name.matches("(main|patch)\\.\\d+\\.com\\.ea\\.gp\\.fifaworld\\.obb");
    }
    @Override public boolean onCreate() { return true; }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws java.io.FileNotFoundException {
        GameTrust.enforceCaller(getContext());
        String name = uri.getLastPathSegment();
        if (!"r".equals(mode) || !allowed(name) || uri.getPathSegments().size() != 2
                || !"expansions".equals(uri.getPathSegments().get(0))) {
            throw new java.io.FileNotFoundException("Unsupported game file");
        }
        long identity = android.os.Binder.clearCallingIdentity();
        try (FileInputStream source = new FileInputStream(new File(getContext().getFilesDir(), "game-files.json"))) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = source.read(buffer)) != -1) bytes.write(buffer, 0, count);
            JSONObject files = new JSONObject(bytes.toString("UTF-8"));
            return getContext().getContentResolver().openFileDescriptor(Uri.parse(files.getString(name)), "r");
        } catch (Exception error) {
            throw new java.io.FileNotFoundException("Import " + name + " in Ignition first");
        } finally {
            android.os.Binder.restoreCallingIdentity(identity);
        }
    }
    @Override public String getType(Uri uri) { return "application/octet-stream"; }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
