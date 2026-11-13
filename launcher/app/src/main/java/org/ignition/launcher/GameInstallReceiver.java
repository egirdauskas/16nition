package org.ignition.launcher;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;

public final class GameInstallReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent result) {
        int status = result.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmation = result.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmation != null) context.startActivity(confirmation.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return;
        }
        android.content.SharedPreferences.Editor state = context.getSharedPreferences(
            "game-install", Context.MODE_PRIVATE).edit().remove("session");
        if (status == PackageInstaller.STATUS_SUCCESS && GameTrust.paired(context)) {
            state.remove("error").putBoolean("installed", true);
        } else {
            state.putString("error", result.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
        }
        state.commit();
        context.startActivity(new Intent(context, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
    }
}
