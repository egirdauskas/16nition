package org.ignition.launcher;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.widget.Button;
import android.widget.TextView;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String GAME = "com.ea.gp.fifaworld";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler();
    private TextView status;
    private TextView club;
    private Button play;
    private Button godmodeButton;
    private boolean resumed;
    private boolean pendingPlay;
    private String pendingExport;
    private String displayedPhase;

    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            if (!resumed) return;
            try {
                if (GamePreparation.busy) {
                    status.setText(GamePreparation.progress);
                    play.setEnabled(false);
                    handler.postDelayed(this, 500);
                    return;
                }
                if (BackendHost.lastError != null) {
                    pendingPlay = false;
                    play.setEnabled(true);
                    status.setText(BackendHost.lastError);
                    handler.postDelayed(this, 500);
                    return;
                }
                if (Python.isStarted()) {
                    JSONObject state = new JSONObject(Python.getInstance().getModule("launcher_bridge")
                        .callAttr("status").toString());
                    String phase = state.getString("phase");
                    if (!phase.equals(displayedPhase)) {
                        displayedPhase = phase;
                        if ("running".equals(phase) || "stopped".equals(phase)) worker.execute(MainActivity.this::updateClub);
                    }
                    String detail = state.getString("detail");
                    if (!detail.contentEquals(status.getText())) status.setText(detail);
                    if (pendingPlay && "error".equals(state.getString("phase"))) {
                        pendingPlay = false;
                        play.setEnabled(true);
                    }
                    if (pendingPlay && "running".equals(state.getString("phase"))) {
                        pendingPlay = false;
                        play.setEnabled(true);
                        startActivity(new Intent().setClassName(GAME, "org.ignition.game.BootstrapActivity")
                            .putExtra("ignition.ready", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                    }
                }
            } catch (Exception error) { fail(error); }
            handler.postDelayed(this, 500);
        }
    };

    private PyObject bridge() throws Exception {
        return BackendHost.prepare(this).getModule("launcher_bridge");
    }
    private void fail(Exception error) {
        android.util.Log.e("Ignition", "Operation failed", error);
        runOnUiThread(() -> {
            pendingPlay = false;
            play.setEnabled(true);
            new AlertDialog.Builder(this).setTitle("16NITION").setMessage(error.getMessage())
                .setPositiveButton("OK", null).show();
        });
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (saved != null) pendingExport = saved.getString("export");
        immersive();
        try {
            LauncherUi ui = new LauncherUi(this);
            club = ui.club;
            status = ui.status;
            play = ui.action("play", this::playGame);
            ui.action("import", () -> chooseFile(79));
            ui.action("export", () -> idleThen(this::prepareExport));
            ui.action("clubs", this::chooseClub);
            godmodeButton = ui.action("godmode", () -> idleThen(this::godmode));
            godmodeButton.setEnabled(false);
            ui.action("setup", this::setup);
            setContentView(ui);
        } catch (Exception error) {
            throw new IllegalStateException("Launcher presentation could not load", error);
        }
        if ("org.ignition.PLAY".equals(getIntent().getAction())) handler.post(this::playGame);
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(
            android.view.View.SYSTEM_UI_FLAG_FULLSCREEN |
            android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
            android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) immersive();
    }

    private boolean patchedGame() {
        return GameTrust.paired(this);
    }
    private void playGame() {
        if (!patchedGame()) {
            gameSetup();
            return;
        }
        play.setEnabled(false);
        worker.execute(() -> {
            boolean stale;
            try { stale = bridge().callAttr("club_needs_update", getFilesDir().getAbsolutePath()).toBoolean(); }
            catch (Exception error) { stale = false; }
            boolean update = stale;
            runOnUiThread(() -> {
                if (!update) { startPlay(); return; }
                play.setEnabled(true);
                new AlertDialog.Builder(this).setTitle("Update club?")
                    .setMessage("This club was saved with an older 16NITION version. Update it to this "
                        + "version's Store rules? Your players, coins and history are kept, and a backup "
                        + "is saved first.")
                    .setPositiveButton("Update", (dialog, which) -> {
                        play.setEnabled(false);
                        status.setText("Updating club…");
                        worker.execute(() -> {
                            try {
                                bridge().callAttr("update_club", getFilesDir().getAbsolutePath());
                                runOnUiThread(this::startPlay);
                            } catch (Exception error) { fail(error); }
                        });
                    })
                    .setNegativeButton("Cancel", null).show();
            });
        });
    }

    private void startPlay() {
        pendingPlay = true;
        BackendHost.lastError = null;
        play.setEnabled(false);
        status.setText("Starting…");
        Intent service = new Intent(this, LocalBackendService.class);
        if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(service);
        else startService(service);
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if ("org.ignition.PLAY".equals(intent.getAction())) playGame();
    }

    private void chooseFile(int request) {
        Intent select = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*")
            .addCategory(Intent.CATEGORY_OPENABLE);
        if (request == 82) select.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(select, request);
    }
    private void idleThen(Runnable action) { idleThen(action, false); }

    /** leaving: the action only switches away from the selected club (new/select/import). */
    private void idleThen(Runnable action, boolean leaving) {
        worker.execute(() -> {
            try {
                bridge().callAttr("check_idle", getFilesDir().getAbsolutePath(),
                    new com.chaquo.python.Kwarg("leaving", leaving));
                runOnUiThread(() -> {
                    if (patchedGame()) closeGame(action);
                    else action.run();
                });
            } catch (Exception error) { fail(error); }
        });
    }
    private void closeGame(Runnable action) {
        class CloseConnection implements android.content.ServiceConnection {
            private boolean complete;
            private boolean requested;
            private final Runnable timeout = () -> finishClose(false);
            private void finishClose(boolean stopped) {
                if (complete) return;
                complete = true;
                handler.removeCallbacks(timeout);
                try { unbindService(this); } catch (IllegalArgumentException ignored) {}
                if (stopped) action.run();
                else fail(new java.io.IOException("Game did not close; club files were preserved."));
            }
            @Override public void onServiceConnected(android.content.ComponentName name, android.os.IBinder binder) {
                try {
                    binder.linkToDeath(() -> handler.post(() -> finishClose(true)), 0);
                    android.os.Parcel data = android.os.Parcel.obtain();
                    try {
                        data.writeInterfaceToken("org.ignition.game.control");
                        requested = true;
                        if (!binder.transact(1, data, null, android.os.IBinder.FLAG_ONEWAY)) finishClose(false);
                    } finally { data.recycle(); }
                } catch (Exception error) { finishClose(false); }
            }
            @Override public void onServiceDisconnected(android.content.ComponentName name) {
                finishClose(requested);
            }
            @Override public void onBindingDied(android.content.ComponentName name) { finishClose(requested); }
            @Override public void onNullBinding(android.content.ComponentName name) { finishClose(false); }
        }
        CloseConnection connection = new CloseConnection();
        if (!bindService(new Intent().setClassName(GAME, "org.ignition.game.GameControlService"),
                connection, BIND_AUTO_CREATE)) {
            fail(new java.io.IOException("Game control unavailable; club files were preserved."));
            return;
        }
        // Binding and process death are asynchronous; no delay is treated as proof.
        handler.postDelayed(connection.timeout, 10000);
    }
    private void prepareExport() {
        worker.execute(() -> {
            try {
                pendingExport = bridge().callAttr("export_club", getFilesDir().getAbsolutePath()).toString();
                runOnUiThread(() -> startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .setType("application/gzip").addCategory(Intent.CATEGORY_OPENABLE)
                    .putExtra(Intent.EXTRA_TITLE, "16NITION-club.tar.gz"), 84));
            } catch (Exception error) { fail(error); }
        });
    }
    private void godmode() {
        worker.execute(() -> {
            try {
                JSONObject result = new JSONObject(bridge().callAttr("godmode",
                    getFilesDir().getAbsolutePath()).toString());
                runOnUiThread(() -> {
                    updateClub();
                    android.widget.Toast.makeText(this,
                        result.optString("club") + ": 999,999 FP",
                        android.widget.Toast.LENGTH_LONG).show();
                });
            } catch (Exception error) { fail(error); }
        });
    }
    private void chooseClub() {
        worker.execute(() -> {
            try {
                JSONArray rows = new JSONArray(bridge().callAttr("list_clubs", getFilesDir().getAbsolutePath()).toString());
                String[] names = new String[rows.length()];
                for (int index = 0; index < names.length; index++) names[index] = rows.getJSONObject(index).getString("name");
                runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Clubs").setItems(names, (dialog, selected) -> {
                    idleThen(() -> worker.execute(() -> {
                        try {
                            bridge().callAttr("select_club", getFilesDir().getAbsolutePath(), rows.getJSONObject(selected).getString("id"));
                            updateClub();
                        } catch (Exception error) { fail(error); }
                    }), true);
                }).setPositiveButton("New club", (dialog, which) -> idleThen(() -> worker.execute(() -> {
                    try { bridge().callAttr("new_club", getFilesDir().getAbsolutePath()); updateClub(); }
                    catch (Exception error) { fail(error); }
                }), true)).setNegativeButton("Cancel", null).show());
            } catch (Exception error) { fail(error); }
        });
    }
    private void setup() {
        new AlertDialog.Builder(this).setTitle("Setup").setItems(new String[]{
            "Prepare game", "Import expansions", "Stop server", "Device check"
        }, (dialog, selected) -> {
            if (selected == 0) gameSetup();
            if (selected == 1) chooseFile(82);
            if (selected == 2) {
                Intent service = new Intent(this, LocalBackendService.class).setAction("stop");
                if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(service);
                else startService(service);
            }
            if (selected == 3) worker.execute(() -> {
                try {
                    String result = bridge().callAttr("self_test", getFilesDir().getAbsolutePath()).toString();
                    try (FileOutputStream output = new FileOutputStream(new File(getFilesDir(), "device-check.json"))) {
                        output.write(result.getBytes(StandardCharsets.UTF_8));
                    }
                    runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Device check")
                        .setMessage("Python and backend modules: OK").setPositiveButton("OK", null).show());
                } catch (Exception error) { fail(error); }
            });
        }).show();
    }

    private boolean gameInstalled() {
        try { getPackageManager().getApplicationInfo(GAME, 0); return true; }
        catch (PackageManager.NameNotFoundException absent) { return false; }
    }

    private void gameSetup() {
        java.util.ArrayList<String> names = new java.util.ArrayList<>();
        names.add("Choose original APK");
        try {
            if (GameVersions.installed(this) != null) names.add("Use installed FIFA");
        } catch (Exception absent) { }
        try { if (GamePreparation.record(this) != null) names.add("Install prepared game"); }
        catch (Exception invalid) { }
        new AlertDialog.Builder(this).setTitle("Game setup")
            .setItems(names.toArray(new String[0]), (dialog, selected) -> {
                String choice = names.get(selected);
                if ("Choose original APK".equals(choice)) chooseFile(85);
                else if ("Use installed FIFA".equals(choice)) prepareGame(null);
                else requestGameInstall();
            }).setNegativeButton("Cancel", null).show();
    }

    private void prepareGame(Uri original) {
        BackendHost.lastError = null;
        play.setEnabled(false);
        status.setText("Preparing game…");
        worker.execute(() -> {
            try {
                if (original == null) GamePreparation.prepareInstalled(this);
                else GamePreparation.prepare(this, original);
                runOnUiThread(() -> {
                    play.setEnabled(true);
                    status.setText("Game ready to install");
                    if (!isFinishing() && !isDestroyed()) requestGameInstall();
                });
            } catch (Exception error) { fail(error); }
        });
    }

    private void requestGameInstall() {
        worker.execute(() -> {
            try {
                GamePreparation.verifyPrepared(this);
                runOnUiThread(this::authorizeGameInstall);
            } catch (Exception error) { fail(error); }
        });
    }

    private void authorizeGameInstall() {
        if (android.os.Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
            getSharedPreferences("game-install", MODE_PRIVATE).edit().putBoolean("permission", true).commit();
            startActivityForResult(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:" + getPackageName())), 86);
            return;
        }
        if (gameInstalled() && !GameTrust.localSignature(this)) {
            new AlertDialog.Builder(this).setTitle("Replace FIFA installation?")
                .setMessage("Android must remove the current game before installing the prepared copy. "
                    + "Clubs saved in 16NITION are retained; the game's own app data will be removed.")
                .setPositiveButton("Continue", (dialog, which) -> idleThen(() -> {
                    getSharedPreferences("game-install", MODE_PRIVATE).edit().putBoolean("removing", true).commit();
                    startActivityForResult(new Intent(Intent.ACTION_UNINSTALL_PACKAGE,
                        Uri.parse("package:" + GAME)).putExtra(Intent.EXTRA_RETURN_RESULT, true), 87);
                })).setNegativeButton("Cancel", null).show();
        } else idleThen(this::commitGameInstall);
    }

    private void commitGameInstall() {
        worker.execute(() -> {
            try {
                GameInstaller.install(this);
                runOnUiThread(() -> status.setText("Waiting for Android installation…"));
            } catch (Exception error) { fail(error); }
        });
    }

    private void updateClub() {
        try {
            JSONObject value = new JSONObject(bridge().callAttr("selected_club", getFilesDir().getAbsolutePath()).toString());
            runOnUiThread(() -> {
                club.setText(value.optString("name", "New club"));
                godmodeButton.setEnabled(!value.optBoolean("pending", true));
            });
        } catch (Exception error) { fail(error); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 84 && (result != RESULT_OK || data == null)) {
            if (pendingExport != null) new File(pendingExport).delete();
            pendingExport = null;
            return;
        }
        if (result != RESULT_OK || data == null) return;
        if (request == 85) {
            prepareGame(data.getData());
            return;
        }
        if (request == 82) {
            worker.execute(() -> {
                try {
                    ExpansionFiles.importSelection(this, data);
                    runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Expansions imported")
                        .setPositiveButton("OK", null).show());
                }
                catch (Exception error) { fail(error); }
            });
            return;
        }
        if (request == 84 && pendingExport != null) {
            worker.execute(() -> {
                try (InputStream input = new java.io.FileInputStream(pendingExport);
                     OutputStream output = getContentResolver().openOutputStream(data.getData())) {
                    copy(input, output, 128L * 1024 * 1024);
                    new File(pendingExport).delete();
                    pendingExport = null;
                } catch (Exception error) { fail(error); }
            });
            return;
        }
        if (request == 79) {
            Runnable action = () -> worker.execute(() -> {
                File archive = new File(getFilesDir(), "selected-import");
                try {
                    try (InputStream input = getContentResolver().openInputStream(data.getData());
                         OutputStream output = new FileOutputStream(archive)) {
                        copy(input, output, 128L * 1024 * 1024);
                    }
                    bridge().callAttr("import_club",
                        getFilesDir().getAbsolutePath(), archive.getAbsolutePath());
                    archive.delete();
                    updateClub();
                } catch (Exception error) { fail(error); }
            });
            idleThen(action, true);
        }
    }
    private static void copy(InputStream input, OutputStream output, long limit) throws Exception {
        byte[] buffer = new byte[65536];
        long total = 0;
        int count;
        while ((count = input.read(buffer)) != -1) {
            total += count;
            if (total > limit) throw new java.io.IOException("File exceeds the size limit");
            output.write(buffer, 0, count);
        }
    }
    @Override public void onResume() {
        super.onResume();
        resumed = true;
        handler.post(refresh);
        worker.execute(this::updateClub);
        android.content.SharedPreferences install = getSharedPreferences("game-install", MODE_PRIVATE);
        if (install.getBoolean("permission", false)) {
            install.edit().remove("permission").commit();
            if (android.os.Build.VERSION.SDK_INT < 26 || getPackageManager().canRequestPackageInstalls()) requestGameInstall();
        }
        if (install.getBoolean("removing", false)) {
            install.edit().remove("removing").commit();
            if (!gameInstalled()) requestGameInstall();
        }
        String error = install.getString("error", null);
        if (error != null) {
            install.edit().remove("error").commit();
            status.setText(error);
        }
    }
    @Override public void onPause() {
        resumed = false;
        handler.removeCallbacks(refresh);
        super.onPause();
    }
    @Override public void onSaveInstanceState(Bundle state) {
        state.putString("export", pendingExport);
        super.onSaveInstanceState(state);
    }
    @Override public void onDestroy() { worker.shutdown(); super.onDestroy(); }
}
