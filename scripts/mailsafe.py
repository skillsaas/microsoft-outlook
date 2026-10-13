"""Shared helpers for the microsoft-outlook skill: printable text, link checks, attachment risk,
safe file names. Standard library only. Nothing here opens a URL or runs a file.

Exit codes used by every script (see SKILL.md). JSON output also carries "status", which names
the reason, so exit 1 never has to be guessed:
  0 ok (status "ok", or "incomplete" when something was not fully read: check "incomplete")
  1 status "risk-threshold" (--fail-on-risk level reached), "risky-skipped" (extract skipped
    high-risk files) or "incomplete" (extract refuses to call a partial parse a success)
  2 status "error": unsupported, corrupt or setup error
  3 status "refused": safety refusal (size, count or time limit, output exists, unsafe path)
"""
import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import unicodedata
from urllib.parse import unquote, urlsplit

VERSION = "0.1.2"
EXIT_OK, EXIT_RISK, EXIT_UNSUPPORTED, EXIT_REFUSED = 0, 1, 2, 3

# Outlook's blocked attachment list ("Blocked attachments in Outlook", support.microsoft.com,
# read 2026-10-13, 133 extensions). Outlook blocks these by default; we treat them as high risk.
OUTLOOK_BLOCKED = frozenset("""
ade adp apk app appcontent-ms application appref-ms appx asp aspx asx bas bat bgi cab cdxml cer
chm cmd cnt com cpl crt csh der diagcab exe fxp gadget grp hlp hpj hta htc img inf ins iso isp its
jar jnlp js jse ksh library-ms lnk mad maf mag mam maq mar mas mat mau mav maw mcf mda mdb mde mdt
mdw mdz msc mht mhtml msh msh1 msh2 mshxml msh1xml msh2xml msi msp mst msu ops osd pcd pif pl plg
prf prg printerexport ps1 ps1xml ps2 ps2xml psc1 psc2 psd1 psdm1 pssc pst py pyc pyo pyw pyz pyzw
reg scf scr sct search-ms settingcontent-ms shb shs theme tmp udl url vb vbe vbp vbs vhd vhdx
vsmacros vsw webpnp website ws wsb wsc wsf wsh xbap xll xnk
""".split())
# Skill heuristics, not Microsoft's list: formats that carry macros, open in a browser, or hide
# other files. Labelled separately so the report never claims Outlook blocks them.
MACRO_OFFICE = frozenset("docm dotm xlsm xltm xlam xlsb pptm potm ppsm ppam sldm doc dot xls xlt ppt pps".split())
ACTIVE_WEB = frozenset("htm html xhtml shtml svg svgz xht".split())
CONTAINERS = frozenset("zip 7z rar gz tgz tar bz2 xz z lzh arj ace cab iso img vhd vhdx msg eml dat tnef".split())

_INVISIBLE = re.compile("[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f"
                        "\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0]")
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")


def clean_text(s, limit=2000):
    """File text made safe to print: controls, bidi and zero-width removed, length capped."""
    if s is None:
        return None
    if isinstance(s, bytes):
        s = s.decode("utf-8", "replace")
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cat in ("Cc", "Cf", "Cs", "Co") or _INVISIBLE.match(ch):
            continue
        else:
            out.append(ch)
    s = "".join(out)
    if limit and len(s) > limit:
        s = s[:limit] + " [truncated, %d chars total]" % len(s)
    return s


def has_bidi(s):
    return bool(s and _BIDI.search(s))


def has_invisible(s):
    return bool(s and _INVISIBLE.search(s))


def ext_of(name):
    base = (name or "").strip().rstrip(". ").lower()
    return base.rsplit(".", 1)[1] if "." in base else ""


def attachment_risk(name, content_type=None, size=None):
    """Return (risk, reasons). risk is low, medium or high. Name tricks count, not only the extension."""
    reasons = []
    raw = name or ""
    if has_bidi(raw):
        reasons.append("bidi-override-in-name")
    if has_invisible(raw):
        reasons.append("invisible-chars-in-name")
    if "/" in raw or "\\" in raw:
        reasons.append("path-in-name")
    name = clean_text(raw, 0)  # full name: a long padded name must not hide its extension
    if _WIN_RESERVED.match(name.replace("\\", "/").split("/")[-1]):
        reasons.append("windows-device-name")
    e = ext_of(name)
    parts = name.lower().rstrip(". ").split(".")
    if len(parts) >= 3 and parts[-2] in {"pdf", "doc", "docx", "xlsx", "jpg", "png", "txt"}:
        reasons.append("double-extension")
    if re.search(r"\s{4,}\S*\.\w+$", name):
        reasons.append("padded-name")
    if e in OUTLOOK_BLOCKED:
        reasons.append("outlook-blocked-type")
    if e in MACRO_OFFICE:
        reasons.append("macro-capable-office")
    if e in ACTIVE_WEB:
        reasons.append("opens-in-browser")
    if e in CONTAINERS:
        reasons.append("container")
    if not e:
        reasons.append("no-extension")
    ct = (content_type or "").lower()
    if ct in ("application/x-msdownload", "application/x-dosexec", "application/hta",
              "application/x-ms-shortcut", "application/javascript", "text/javascript"):
        reasons.append("executable-content-type")
    if ct in ("application/ms-tnef", "message/rfc822", "application/vnd.ms-outlook"):
        reasons.append("container")
    # opens-in-browser is high since 0.1.1: HTML and SVG attachments are a common credential
    # phishing carrier and can run script when opened from disk.
    high = {"outlook-blocked-type", "bidi-override-in-name", "double-extension",
            "executable-content-type", "padded-name", "opens-in-browser"}
    reasons = list(dict.fromkeys(reasons))  # each reason once (a .msg is a container by name and type)
    if high & set(reasons):
        return "high", reasons
    if {"macro-capable-office", "container", "invisible-chars-in-name",
            "path-in-name", "windows-device-name"} & set(reasons):
        return "medium", reasons
    return "low", reasons


_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)


def safe_filename(name, fallback="attachment"):
    """A name that cannot escape the output folder or collide with Windows device names."""
    name = clean_text(name or "", 0) or ""
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name in (".", ".."):
        name = fallback
    if _WIN_RESERVED.match(name):
        name = "_" + name
    if len(name.encode("utf-8")) > 150:
        stem, dot, e = name.rpartition(".")
        e = e.encode("utf-8")[:24].decode("utf-8", "ignore") if dot else ""
        name = stem.encode("utf-8")[:120].decode("utf-8", "ignore").rstrip(" .") + ("." + e if e else "")
    return name


# ---- links ----
_URL_RE = re.compile(r"""(?i)\b((?:https?|ftp|file|javascript|data|vbscript|ms-[a-z-]+|search-ms|mailto|tel|smb):[^\s<>"'`]+|www\.[^\s<>"'`]+)""")
_HOSTLIKE = re.compile(r"(?i)^(?:https?://)?((?:[a-z0-9\u00a1-\uffff-]+\.)+[a-z\u00a1-\uffff]{2,63})(?:[/:?#]|$)")
RISKY_SCHEMES = {"javascript", "vbscript", "data", "file", "smb", "search-ms", "ms-msdt",
                 "ms-officecmd", "ms-word", "ms-excel", "ms-powerpoint", "ms-search"}


def registrable(host):
    """Last two labels (three when the second-last is short, e.g. co.uk). An approximation:
    no public suffix list is shipped, so treat site comparison as a hint, not proof."""
    labels = [l for l in (host or "").lower().strip(".").split(".") if l]
    if len(labels) >= 3 and len(labels[-2]) <= 3 and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def analyze_url(target, text=None):
    """Scheme, host and reasons for one link. Never fetches anything."""
    t = (target or "").strip()
    reasons = []
    if has_invisible(t) or has_bidi(t):
        reasons.append("invisible-chars-in-target")
    t2 = clean_text(t, 0)
    if t2.lower().startswith("www."):
        t2 = "http://" + t2
    try:
        sp = urlsplit(t2)
        scheme = (sp.scheme or "").lower()
        host = (sp.hostname or "").lower()
        if sp.username or sp.password:
            reasons.append("userinfo-in-url")
    except ValueError:
        return {"scheme": None, "host": None, "risk": "high", "reasons": ["unparseable"]}
    if scheme in RISKY_SCHEMES or scheme.startswith("ms-"):
        reasons.append("risky-scheme")
    if scheme == "http":
        reasons.append("not-https")
    if host:
        try:
            ipaddress.ip_address(host.strip("[]"))
            reasons.append("ip-host")
        except ValueError:
            pass
        if "%" in host:
            reasons.append("encoded-chars-in-host")
            host = unquote(host).lower()
        if "xn--" in host:
            reasons.append("punycode-host")
        try:
            host.encode("ascii")
        except UnicodeEncodeError:
            reasons.append("non-ascii-host")
    if text:
        tx = clean_text(text, 0).strip()
        m = _HOSTLIKE.match(tx)
        if m and "@" not in tx and host:
            shown = m.group(1).lower()
            if registrable(shown) != registrable(host):
                reasons.append("text-shows-other-host")
    high = {"risky-scheme", "userinfo-in-url", "text-shows-other-host", "invisible-chars-in-target",
            "unparseable", "encoded-chars-in-host"}
    risk = "high" if high & set(reasons) else ("medium" if reasons and reasons != ["not-https"] else "low")
    if reasons == ["not-https"]:
        risk = "medium"
    return {"scheme": scheme or None, "host": host or None, "risk": risk, "reasons": reasons}


def urls_in_text(s, cap=500):
    found = []
    for m in _URL_RE.finditer(s or ""):
        u = m.group(1).rstrip(").,;:!?]'\"")
        found.append(u)
        if len(found) >= cap:
            break
    return found


# One result per run: the main thread and the --timeout watchdog both print through this lock,
# and whichever comes first wins, so output is never two JSON documents or a torn one.
_LOCK = threading.Lock()
_RUN = {"done": False, "cleanup": [], "timer": None}


def emit(obj, as_json, human):
    """Print JSON or the human text. obj must have ok and error."""
    with _LOCK:
        if _RUN["done"]:
            return
        _RUN["done"] = True
        if as_json:
            print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        else:
            print(human(obj) if obj.get("ok") else "error: %s" % obj.get("error"))
        sys.stdout.flush()


def fail(as_json, code, msg, **extra):
    d = {"ok": False, "status": "refused" if code == EXIT_REFUSED else "error", "error": msg}
    d.update(extra)
    with _LOCK:
        if not _RUN["done"]:
            _RUN["done"] = True
            _print_fail(as_json, d)
    return code


def _print_fail(as_json, d):
    if as_json:
        print(json.dumps(d, indent=2, ensure_ascii=False, default=str))
    else:
        print("error: %s" % d["error"], file=sys.stderr)
        for x in d.get("incomplete") or []:
            print("  not read: %s" % x, file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()


def read_capped(path, cap):
    """Read a regular file no larger than cap bytes. Raises ValueError with a reason."""
    st = os.stat(path)
    if not os.path.isfile(path):
        raise ValueError("not a regular file")
    if st.st_size > cap:
        raise OverflowError("file is %d bytes, over the %d byte limit (--max-bytes)" % (st.st_size, cap))
    with open(path, "rb") as f:
        return f.read(cap + 1)


class ArgParser(argparse.ArgumentParser):
    """argparse that reports usage errors as JSON (status "error", exit 2) when --json is given."""

    def __init__(self, *a, **k):
        k.setdefault("allow_abbrev", False)  # "--js" must not silently mean --json
        super().__init__(*a, **k)

    def error(self, message):
        # JSON for any spelling that looks like a JSON request: --json, --json=1, --js
        if any(x == "--json" or x.startswith("--json=") or x == "--js" for x in sys.argv[1:]):
            fail(True, EXIT_UNSUPPORTED, "usage: %s" % message)
            sys.exit(EXIT_UNSUPPORTED)
        super().error(message)


def watchdog(seconds, as_json):
    """Wall-clock limit for one run. When it fires, print a refusal and exit 3 at once, from a
    timer thread, so a pathological file cannot keep the process busy. 0 disables it."""
    if not seconds or seconds <= 0:
        return None

    def fire():
        with _LOCK:
            if _RUN["done"]:
                return  # the result is already out; the main thread is exiting normally
            _RUN["done"] = True
            notes = []
            try:
                for fn in list(_RUN["cleanup"]):
                    try:
                        r = fn()
                        if r:
                            notes.append(r)
                    except Exception as e:  # report, never hang in cleanup
                        notes.append("cleanup failed: %s" % type(e).__name__)
                d = {"ok": False, "status": "refused",
                     "error": "time limit of %gs reached (--timeout); nothing was completed" % seconds}
                if notes:
                    d["cleanup"] = notes
                _print_fail(as_json, d)
            finally:
                os._exit(EXIT_REFUSED)
    t = threading.Timer(seconds, fire)
    t.daemon = True
    t.start()
    _RUN["timer"] = t
    return t


def on_timeout(fn):
    """Register a cleanup to run if the watchdog fires; fn returns a short note or None."""
    _RUN["cleanup"].append(fn)
    return fn


def off_timeout(fn):
    if fn in _RUN["cleanup"]:
        _RUN["cleanup"].remove(fn)


def finish(code):
    """Cancel the watchdog and return the exit code; every script's __main__ goes through here."""
    t = _RUN["timer"]
    if t is not None:
        t.cancel()
    return code


# What these scripts never check, listed in every JSON report so a reader does not assume more.
NOT_CHECKED_MAIL = [
    "links are analyzed as text only; no URL is fetched, so final destinations and page content are unknown",
    "attachment contents are not scanned for malware; risk comes from names and types only",
    "DKIM and SPF are not re-verified; Authentication-Results are read as written",
    "encrypted (S/MIME, OME) content is not decrypted",
    "OLE objects and reference (cloud) attachments are not decoded or followed",
    "the domain comparison uses a two- or three-label approximation, not the Public Suffix List",
]
