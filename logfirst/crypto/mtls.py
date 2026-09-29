"""X.509 material for mutual TLS between client nodes and the authority.

Honest scoping, because this is easy to oversell: the TLS layer here is
*classical* (ECDSA P-256). It authenticates the transport in both directions and
encrypts the channel. It is **not** where the security argument lives, and
nothing in the evidence chain depends on it.

The split is deliberate:

* **TLS** answers "is this socket really to the authority, and is the caller a
  node we enrolled?" It is a perimeter control.
* **The ML-DSA signature in the request body** answers "did *this recipient's
  key* authorise *this* request?" That is the non-repudiation property, and it
  is the one that survives the request being logged, replayed, subpoenaed, or
  examined years later by someone who does not trust this server at all.

A request that passes TLS and fails the body signature is rejected. A request
that somehow reached the handler without TLS would still have to pass the body
signature. So the PQ signature is the load-bearing check and TLS is defence in
depth -- which is the right way round for a system whose threat model includes
its own operator.

Using ECDSA for the transport is a knowing trade: TLS 1.3 with PQ hybrid key
exchange is available in newer OpenSSL builds but not universally, and a demo
that fails to handshake on the presentation laptop is worse than one whose
transport layer is not post-quantum. The transport is not the artefact that has
to survive a decade; the signed ledger entry is.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _write(path: str, data: bytes, mode: int = 0o600) -> None:
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def _key_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())


def _cert_pem(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


class MTLSFactory:
    """Issues and persists the X.509 material for one deployment."""

    def __init__(self, ca_cert: x509.Certificate, ca_key, directory: str):
        self.ca_cert = ca_cert
        self.ca_key = ca_key
        self.directory = directory
        self.ca_path = os.path.join(directory, "ca.pem")

    @classmethod
    def open(cls, directory: str) -> "MTLSFactory":
        """Load the deployment CA, creating it on first call.

        The CA key is written 0600 next to the certs. In a real deployment this
        is the one key that would live in an HSM and never on disk; for the
        demo it is a file, and README says so.
        """
        os.makedirs(directory, exist_ok=True)
        cert_path = os.path.join(directory, "ca.pem")
        key_path = os.path.join(directory, "ca.key")
        if os.path.exists(cert_path) and os.path.exists(key_path):
            with open(cert_path, "rb") as f:
                ca_cert = x509.load_pem_x509_certificate(f.read())
            with open(key_path, "rb") as f:
                ca_key = serialization.load_pem_private_key(f.read(), password=None)
            return cls(ca_cert, ca_key, directory)

        ca_key = _key()
        now = datetime.datetime.now(datetime.timezone.utc)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(_name("logfirst-mtls-ca"))
            .issuer_name(_name("logfirst-mtls-ca"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                           critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        _write(cert_path, _cert_pem(ca_cert), 0o644)
        _write(key_path, _key_pem(ca_key))
        return cls(ca_cert, ca_key, directory)

    def issue(self, cn: str, directory: str, server: bool = False) -> dict:
        """Issue a leaf certificate and key; return the paths."""
        os.makedirs(directory, exist_ok=True)
        key = _key()
        now = datetime.datetime.now(datetime.timezone.utc)
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name(cn))
            .issuer_name(self.ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
        )
        if server:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]), critical=False)
            eku = x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH])
        else:
            eku = x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH])
        builder = builder.add_extension(eku, critical=False)
        cert = builder.sign(self.ca_key, hashes.SHA256())

        cert_path = os.path.join(directory, f"{cn}.pem")
        key_path = os.path.join(directory, f"{cn}.key")
        _write(cert_path, _cert_pem(cert), 0o644)
        _write(key_path, _key_pem(key))
        return {"cert": cert_path, "key": key_path, "ca": self.ca_path}

    # -- ssl contexts ------------------------------------------------------

    def server_context(self, cert_path: str, key_path: str) -> ssl.SSLContext:
        """Context that *requires* a client certificate.

        ``CERT_REQUIRED`` is the point of the exercise: an unauthenticated
        caller must fail at the handshake, before any request body is parsed.
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        ctx.load_verify_locations(cafile=self.ca_path)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def client_context(self, cert_path: str, key_path: str) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(cert_path, key_path)
        ctx.load_verify_locations(cafile=self.ca_path)
        ctx.check_hostname = False  # demo runs on 127.0.0.1 with a local CA
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

