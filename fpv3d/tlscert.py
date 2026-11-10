"""HTTPS for the phone: a small private certificate authority (CA) of your own + a server certificate for this PC.

Why: browsers only allow some features on secure (https) pages: keeping the phone screen on during a live
flight, the radio over USB (Web Serial), installing Alpline as an app. Over plain http://192.168.x.x they are
blocked. Install the CA once on the phone (Android: Settings > Security > Encryption & credentials > Install a
certificate > CA certificate, then pick alpline-ca.crt); from then on the phone trusts this PC's https page.

The CA (cache/tls/ca.*) is made once and kept; the server certificate is remade whenever this PC's network
addresses change (a new hotspot), signed by the same CA, so the phone keeps trusting it.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import json
from pathlib import Path

from .locations import ROOT
from .brand import APP_NAME

DIR = ROOT / "cache" / "tls"
CA_CRT, CA_KEY = DIR / "alpline-ca.crt", DIR / "ca.key"
SRV_CRT, SRV_KEY, SRV_META = DIR / "server.crt", DIR / "server.key", DIR / "server.json"


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _key():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def _save_key(k, path: Path):
    from cryptography.hazmat.primitives import serialization
    path.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                     serialization.NoEncryption()))


def _load_key(path: Path):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID
    if CA_CRT.exists() and CA_KEY.exists():
        return x509.load_pem_x509_certificate(CA_CRT.read_bytes()), _load_key(CA_KEY)
    DIR.mkdir(parents=True, exist_ok=True)
    key = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{APP_NAME} local CA (this PC only)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    _save_key(key, CA_KEY)
    CA_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def ensure(ips) -> tuple:
    """(certfile, keyfile) for https on these IPv4 addresses (+ localhost); remade when they change."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    ips = sorted(set(ips) | {"127.0.0.1"})
    try:
        meta = json.loads(SRV_META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    ca_cert, ca_key = _ca()
    now = dt.datetime.now(dt.timezone.utc)
    if (meta.get("ips") == ips and SRV_CRT.exists() and SRV_KEY.exists()
            and dt.datetime.fromisoformat(meta.get("until", "2000-01-01T00:00:00+00:00")) > now + dt.timedelta(days=7)):
        return str(SRV_CRT), str(SRV_KEY)
    key = _key()
    until = now + dt.timedelta(days=397)                 # browsers refuse server certificates valid for longer
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{APP_NAME} on this PC")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(until)
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _save_key(key, SRV_KEY)
    SRV_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + CA_CRT.read_bytes())   # chain: server + CA
    SRV_META.write_text(json.dumps({"ips": ips, "until": until.isoformat()}), encoding="utf-8")
    return str(SRV_CRT), str(SRV_KEY)
