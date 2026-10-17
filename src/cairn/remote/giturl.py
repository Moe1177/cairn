"""The repo URLs a plain git org lists: which forms cairn accepts, and the host and path each
names. Only https and ssh (scp-like `git@host:path` too): no local paths, `file://` or `ext::`,
which would read this machine or run a command. No login in an https URL, where every error and
log line would show it (git's credential helper or an ssh key logs in instead): an ssh URL may
name its user (git@), nothing else.
"""

import re

# A path segment as forges allow it: sourcehut's users start with "~" (~sircmpwn/hare), and
# repos may start with a dot (.github, .profile); "." and ".." are never a name.
SEGMENT = r"~?[A-Za-z0-9_.][A-Za-z0-9_.-]{0,254}"
_REPO_PATH = re.compile(rf"^{SEGMENT}(?:/{SEGMENT}){{0,19}}$")
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?"
_USER = r"[A-Za-z0-9._-]{1,64}"
# The whole URL, strictly: what Python's parser and git (curl, ssh) could read differently, like
# a "\" or "%" before an "@", never gets here.
_HTTPS = re.compile(rf"^https://({_HOST})(?::(\d{{1,5}}))?/([^?#\\%]*)$")
_SSH = re.compile(rf"^ssh://(?:{_USER}@)?({_HOST})(?::(\d{{1,5}}))?/([^?#\\%]*)$")
_SCP_LIKE = re.compile(rf"^{_USER}@({_HOST}):(?!/)([^?#\\%]*)$")


def repo_url(url: str) -> tuple[str, str] | None:
    """(host, path) of a repo URL cairn may clone, the path without `.git`; None otherwise."""
    url = url.strip()
    if any(c.isspace() or ord(c) < 32 for c in url):
        return None
    found = _HTTPS.match(url) or _SSH.match(url)
    if found:
        host, port, path = found.groups()
        if port is not None and not 0 < int(port) < 65536:
            return None
    elif scp := _SCP_LIKE.match(url):
        host, path = scp.groups()
    else:
        return None
    path = path.strip("/").removesuffix(".git")
    if not is_repo_path(path):
        return None
    return host.lower(), path


def is_repo_path(path: str) -> bool:
    """Whether `path` (owner/name, groups between) is one cairn may name a repo or org by."""
    return bool(_REPO_PATH.fullmatch(path)) and not {".", ".."} & set(path.split("/"))
