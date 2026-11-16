import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import printables


def fetch(monkeypatch, out, name):
    monkeypatch.setattr(printables, "model", lambda _: {"stls": [{"name": name, "id": "1"}]})
    monkeypatch.setattr(printables, "download_link", lambda *_: "unused")
    monkeypatch.setattr(printables, "fetch_bytes", lambda _: b"downloaded mesh")
    printables.cmd_fetch(SimpleNamespace(model_id="1", out=out, match="", every=1, max=12, ledger=None))


@pytest.mark.parametrize("name", ["../escape.stl", "nested/escape.stl", "nested\\escape.stl", "/escape.stl"])
def test_download_rejects_unsafe_filename(tmp_path, monkeypatch, name):
    # Absolute-path probe stays in scratch even on the vulnerable implementation.
    if name.startswith("/"):
        name = str(tmp_path / "absolute.stl")
    with pytest.raises(ValueError, match="filename"):
        fetch(monkeypatch, tmp_path / "out", name)
    assert not (tmp_path / "escape.stl").exists()
    assert not (tmp_path / "absolute.stl").exists()


def test_download_rejects_symlink(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"preserve")
    (out / "model.stl").symlink_to(sentinel)
    with pytest.raises(ValueError, match="symlink"):
        fetch(monkeypatch, out, "model.stl")
    assert sentinel.read_bytes() == b"preserve"


def test_safe_download_and_existing_file_preserved(tmp_path, monkeypatch):
    out = tmp_path / "out"
    fetch(monkeypatch, out, "model.stl")
    assert (out / "model.stl").read_bytes() == b"downloaded mesh"
    (out / "model.stl").write_bytes(b"existing")
    fetch(monkeypatch, out, "model.stl")
    assert (out / "model.stl").read_bytes() == b"existing"


def test_download_exclusive_creation_after_fetch(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(printables, "model", lambda _: {"stls": [{"name": "model.stl", "id": "1"}]})
    monkeypatch.setattr(printables, "download_link", lambda *_: "unused")
    def race(_):
        (out / "model.stl").write_bytes(b"created during fetch")
        return b"downloaded mesh"
    monkeypatch.setattr(printables, "fetch_bytes", race)
    with pytest.raises(FileExistsError):
        printables.cmd_fetch(SimpleNamespace(model_id="1", out=out, match="", every=1, max=12, ledger=None))
    assert (out / "model.stl").read_bytes() == b"created during fetch"


def test_download_rejects_file_url(tmp_path):
    source = tmp_path / "local.txt"
    source.write_bytes(b"local data must not be downloaded")
    with pytest.raises(ValueError, match="HTTPS"):
        printables.fetch_bytes(source.as_uri())


@pytest.mark.parametrize("url", ["http://media.printables.com/file", "https://localhost/file",
    "https://media.printables.com.example.org/file", "https://media.printables.com:444/file",
    "https://user@media.printables.com/file", "https://127.0.0.1/file"])
def test_download_url_and_redirect_restrictions(url):
    import urllib.request
    with pytest.raises(ValueError, match="HTTPS"):
        printables.validate_download_url(url)
    req = urllib.request.Request("https://media.printables.com/start")
    with pytest.raises(ValueError, match="HTTPS"):
        printables.DownloadRedirectHandler().redirect_request(req, None, 302, "redirect", {}, url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "::1", "fc00::1"])
def test_download_rejects_private_dns_before_connect(monkeypatch, address):
    import socket
    monkeypatch.setattr(printables.socket, "getaddrinfo", lambda *a, **kw:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    connection = printables.DownloadHTTPSConnection("media.printables.com", timeout=1)
    monkeypatch.setattr(printables.socket, "socket", lambda *a: pytest.fail("must not connect"))
    with pytest.raises(ValueError, match="public addresses"):
        connection.connect()


def test_download_connects_to_checked_address_with_host_tls(monkeypatch):
    import socket
    from unittest.mock import Mock
    checked = ("1.1.1.1", 443)
    resolver = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", checked)])
    monkeypatch.setattr(printables.socket, "getaddrinfo", resolver)
    sock, tls = Mock(), Mock()
    monkeypatch.setattr(printables.socket, "socket", Mock(return_value=sock))
    connection = printables.DownloadHTTPSConnection("media.printables.com", timeout=3, context=tls)
    connection.connect()
    resolver.assert_called_once()
    sock.connect.assert_called_once_with(checked)
    tls.wrap_socket.assert_called_once_with(sock, server_hostname="media.printables.com")
