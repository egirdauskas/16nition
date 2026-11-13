package org.ignition.launcher;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;
import java.io.File;
import java.math.BigInteger;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.cert.X509Certificate;
import java.util.Collections;
import java.util.Date;
import javax.security.auth.x500.X500Principal;

/** Per-install game key. The launcher's release private key never ships. */
final class GameSigning {
    private static final String ALIAS = "ignition-local-game-v1";
    private GameSigning() {}

    static synchronized X509Certificate certificate(boolean create) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            if (!create) return null;
            KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA", "AndroidKeyStore");
            long now = System.currentTimeMillis();
            generator.initialize(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY)
                .setKeySize(2048)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                .setCertificateSubject(new X500Principal("CN=Ignition local game"))
                .setCertificateSerialNumber(BigInteger.valueOf(now))
                .setCertificateNotBefore(new Date(now - 86400000L))
                .setCertificateNotAfter(new Date(now + 30L * 365 * 86400000L))
                .build());
            generator.generateKeyPair();
        }
        return (X509Certificate)store.getCertificate(ALIAS);
    }

    static String digest(byte[] certificate) throws Exception {
        byte[] raw = MessageDigest.getInstance("SHA-256").digest(certificate);
        StringBuilder value = new StringBuilder();
        for (byte item : raw) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }

    static void sign(File unsigned, File output) throws Exception {
        X509Certificate certificate = certificate(true);
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        PrivateKey key = (PrivateKey)store.getKey(ALIAS, null);
        ApkSigner.SignerConfig config = new ApkSigner.SignerConfig.Builder(
            "IGNITION", key, Collections.singletonList(certificate)).build();
        new ApkSigner.Builder(Collections.singletonList(config))
            .setInputApk(unsigned).setOutputApk(output).setMinSdkVersion(24)
            // apksig's v1 (JAR) signer needs java.util.Base64 (API 26+); it crashed
            // Prepare game on Android 7.1 (BlueStacks Nougat, 12 Nov 2026). The game's
            // minSdk 24 always verifies APK Signature Scheme v2, so v1 is redundant
            // there; API 26+ output stays byte-identical to before.
            .setV1SigningEnabled(android.os.Build.VERSION.SDK_INT >= 26).setV2SigningEnabled(true)
            .setV3SigningEnabled(false).setV4SigningEnabled(false).build().sign();
        ApkVerifier.Result verified = new ApkVerifier.Builder(output)
            .setMinCheckedPlatformVersion(24).build().verify();
        if (!verified.isVerified() || verified.getSignerCertificates().size() != 1
                || !digest(verified.getSignerCertificates().get(0).getEncoded())
                    .equals(digest(certificate.getEncoded()))) {
            throw new java.io.IOException("Prepared game signature did not verify");
        }
    }
}
