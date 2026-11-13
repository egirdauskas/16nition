package org.ignition.launcher;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;

final class BackendHost {
    private static boolean prepared;
    static volatile String lastError;
    private BackendHost() {}

    static synchronized Python prepare(Context context) throws Exception {
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(context.getApplicationContext()));
        }
        if (prepared) return Python.getInstance();
        for (String name : new String[]{"runtime.zip", "runtime-manifest.json", "content-manifest.json", "game-recipe.zip"}) {
            File temporary = new File(context.getFilesDir(), name + ".new");
            try (InputStream input = context.getAssets().open(name);
                 FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    output.write(buffer, 0, count);
                }
                output.getFD().sync();
            }
            if (!temporary.renameTo(new File(context.getFilesDir(), name))) {
                throw new java.io.IOException("Could not prepare local server files");
            }
        }
        prepared = true;
        return Python.getInstance();
    }
}
