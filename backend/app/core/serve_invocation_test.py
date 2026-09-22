"""How the container starts its server.

``start.sh`` is the only thing that turns the deployment's environment into a
uvicorn invocation, and the answer it builds decides whether the app is served
over HTTP or HTTPS. It is shell, so it is exercised the way the container runs
it: with a stand-in ``uvicorn`` on PATH that records the arguments it was given.
"""

import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit

START_SH = Path(__file__).resolve().parents[2] / "start.sh"


@pytest.fixture
def serve(tmp_path):
    """Run ``start.sh`` and return what it would have run uvicorn with."""
    recorder = tmp_path / "uvicorn"
    recorder.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
    recorder.chmod(0o755)

    def _run(**env: str) -> subprocess.CompletedProcess:
        environment = {
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            **env,
        }
        return subprocess.run(
            ["sh", str(START_SH)],
            capture_output=True,
            text=True,
            env=environment,
        )

    return _run


def _args(result: subprocess.CompletedProcess) -> list[str]:
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_plain_http_is_what_a_deployment_gets_by_default(serve):
    """Every self-host quickstart, and every install behind a proxy."""
    args = _args(serve())
    assert args[:1] == ["app.main:app"]
    assert not any(arg.startswith("--ssl") for arg in args)


def test_a_certificate_and_key_are_served_directly(serve):
    args = _args(serve(TLS_CERT_FILE="/certs/full.pem", TLS_KEY_FILE="/certs/key.pem"))
    assert "--ssl-certfile=/certs/full.pem" in args
    assert "--ssl-keyfile=/certs/key.pem" in args


def test_a_path_with_a_space_reaches_uvicorn_whole(serve):
    """A volume mount on a NAS is where this one comes from."""
    args = _args(
        serve(TLS_CERT_FILE="/my certs/full.pem", TLS_KEY_FILE="/my certs/key.pem")
    )
    assert "--ssl-certfile=/my certs/full.pem" in args


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        ({"TLS_CERT_FILE": "/certs/full.pem"}, "TLS_KEY_FILE"),
        ({"TLS_KEY_FILE": "/certs/key.pem"}, "TLS_CERT_FILE"),
    ],
)
def test_half_a_setting_stops_and_names_the_other_half(serve, env, missing):
    """One on its own is a setting somebody did not finish writing."""
    result = serve(**env)
    assert result.returncode == 1
    assert missing in result.stderr
    assert result.stdout == ""


def test_a_proxy_in_front_still_gets_its_headers(serve):
    args = _args(serve(BEHIND_PROXY="true", FORWARDED_ALLOW_IPS="10.0.0.0/8"))
    assert "--proxy-headers" in args
    assert "--forwarded-allow-ips=10.0.0.0/8" in args


def test_both_halves_are_what_the_app_calls_serving_tls():
    """The boot-time check reads the same rule the script enforces."""
    assert Settings(TLS_CERT_FILE="/c.pem", TLS_KEY_FILE="/k.pem").terminates_tls
    assert not Settings(TLS_CERT_FILE="/c.pem").terminates_tls
    assert not Settings(TLS_KEY_FILE="/k.pem").terminates_tls
    assert not Settings().terminates_tls
