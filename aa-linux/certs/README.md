# TLS Credentials

No production private keys or production certificates are distributed with this
project.

The `dev/` directory contains an expired, publicly known test identity and a
time shim used only for local Desktop Head Unit testing. It cannot authenticate
to a real car and should never be used outside a local development machine.

The phone-side TLS server must use a certificate and private key accepted by the
head unit. Supply them explicitly:

```sh
python3 -m aa-linux --cert /secure/path/phone.crt --key /secure/path/phone.key
```

Use credentials only when you have the legal right to use them. Do not commit
private keys, Wi-Fi credentials, vehicle data, or captured protocol logs.

For local development, create a test certificate appropriate for your mock head
unit. A self-signed certificate is not expected to work with production head
units.
