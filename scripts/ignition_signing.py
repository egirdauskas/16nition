"""Stable, local project signing identity. Private material never enters Git/APKs."""
import os
from pathlib import Path
import secrets
import subprocess


def configuration():
    directory = Path.home() / '.local/share/ignition'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = directory / 'signing.properties'
    if not config.exists():
        store = directory / 'signing.p12'
        if store.exists():
            raise ValueError('Existing signing key lacks configuration; never replace it')
        password = secrets.token_hex(32)
        env = dict(os.environ, IGNITION_SIGNING_PASSWORD=password)
        subprocess.run([
            'keytool', '-genkeypair', '-keystore', str(store), '-storetype', 'PKCS12',
            '-storepass:env', 'IGNITION_SIGNING_PASSWORD',
            '-keypass:env', 'IGNITION_SIGNING_PASSWORD', '-alias', 'ignition',
            '-keyalg', 'RSA', '-keysize', '3072', '-validity', '36500',
            '-dname', 'CN=Ignition, O=16NITION',
        ], env=env, check=True, capture_output=True)
        store.chmod(0o600)
        with config.open('x') as output:
            config.chmod(0o600)
            output.write('storeFile=' + str(store) + '\nkeyAlias=ignition\n'
                         'storePassword=' + password + '\nkeyPassword=' + password + '\n')
    values = {}
    for line in config.read_text().splitlines():
        key, value = line.split('=', 1)
        values[key] = value
    if not Path(values['storeFile']).is_file():
        raise ValueError('Project signing key is missing')
    return config, values


def sign(apksigner, source, destination):
    _, values = configuration()
    env = dict(os.environ, IGNITION_STORE_PASSWORD=values['storePassword'],
               IGNITION_KEY_PASSWORD=values['keyPassword'])
    subprocess.run([
        str(apksigner), 'sign', '--ks', values['storeFile'],
        '--ks-key-alias', values['keyAlias'], '--ks-pass', 'env:IGNITION_STORE_PASSWORD',
        '--key-pass', 'env:IGNITION_KEY_PASSWORD', '--out', str(destination), str(source),
    ], env=env, check=True)
