"""Self-signed HTTPS certificate for the live server.

Phone browsers only allow camera access on secure pages, so the laptop has to
serve HTTPS even on a home network. The certificate is self-signed: the phone
shows a warning once, and after you accept it the camera works.
"""

import datetime
import ipaddress
import socket
from pathlib import Path


def lan_addresses() -> list[str]:
    """Best-effort list of this machine's IPv4 addresses on local networks."""
    found = set()

    # Connecting a UDP socket sends nothing; it only picks the outgoing interface.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass

    return sorted(ip for ip in found if not ip.startswith("127."))


def ensure_certificate(cert_dir: Path, hosts: list[str]) -> tuple[Path, Path]:
    """Create cert.pem/key.pem covering ``hosts`` unless a matching pair already exists."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_dir = Path(cert_dir)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    wanted = sorted(set(hosts) | {"localhost", "127.0.0.1"})

    if cert_path.exists() and key_path.exists():
        existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        covered = {str(v) for v in san.get_values_for_type(x509.IPAddress)}
        covered |= set(san.get_values_for_type(x509.DNSName))
        not_expired = existing.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc)
        if set(wanted) <= covered and not_expired:
            return cert_path, key_path

    cert_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "C.R.A.P live")])

    alt_names = []
    for host in wanted:
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            alt_names.append(x509.DNSName(host))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
