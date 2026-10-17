"""Find a token for a code host: the environment first, then the host's own CLI login."""

import os
import re
from collections.abc import Callable, Mapping

from cairn.discover.proc import run_text
from cairn.errors import CairnError

# A host name only: no scheme, port, path or user (it goes into URLs and a CLI argument).
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$")
_GITHUB = "github.com"
# gh's own order: GH_TOKEN wins over GITHUB_TOKEN, and Enterprise hosts have their own pair.
_DOTCOM_VARS = ("GH_TOKEN", "GITHUB_TOKEN")
_ENTERPRISE_VARS = ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
_GITLAB_VARS = ("GITLAB_TOKEN", "GITLAB_ACCESS_TOKEN")  # glab's own, in its order

TokenCommand = Callable[[str], str | None]


def check_host(host: str) -> str:
    if not _HOST.fullmatch(host):
        raise CairnError(f"{host!r} isn't a host name (expected something like github.com)")
    return host.lower()


def github_token(
    host: str = _GITHUB,
    *,
    env: Mapping[str, str] | None = None,
    from_cli: TokenCommand | None = None,
) -> str:
    """The token gh would use for `host`. Raises CairnError, saying how to log in, if none."""
    host = check_host(host)
    environ = os.environ if env is None else env
    for name in _DOTCOM_VARS if host == _GITHUB else _ENTERPRISE_VARS:
        if environ.get(name, "").strip():
            return environ[name].strip()
    token = (from_cli or _gh_auth_token)(host)
    if token:
        return token
    raise CairnError(
        f"no GitHub token for {host}: run `gh auth login --hostname {host}`, or set "
        f"{'GH_TOKEN' if host == _GITHUB else 'GH_ENTERPRISE_TOKEN'}"
    )


def gitlab_token(
    host: str = "gitlab.com",
    *,
    env: Mapping[str, str] | None = None,
    from_cli: TokenCommand | None = None,
) -> str:
    """The token glab would use for `host`. Raises CairnError, saying how to log in, if none.
    GITLAB_TOKEN goes only to gitlab.com, or to the host GITLAB_HOST names (as glab does): a
    host typed wrong in the config never gets the token for another."""
    host = check_host(host)
    environ = os.environ if env is None else env
    named = environ.get("GITLAB_HOST", "").strip().lower().removeprefix("https://").rstrip("/")
    if host == (named or "gitlab.com"):
        for name in _GITLAB_VARS:
            if environ.get(name, "").strip():
                return environ[name].strip()
    token = (from_cli or _glab_token)(host)
    if token:
        return token
    raise CairnError(
        f"no GitLab token for {host}: run `glab auth login --hostname {host}`, or set "
        "GITLAB_TOKEN (a token with read_api)"
    )


def _glab_token(host: str) -> str | None:
    done = run_text(["glab", "config", "get", "token", "--host", host], timeout=15)
    if done is None or done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _gh_auth_token(host: str) -> str | None:
    done = run_text(["gh", "auth", "token", "--hostname", host], timeout=15)
    if done is None or done.returncode != 0:
        return None
    return done.stdout.strip() or None
