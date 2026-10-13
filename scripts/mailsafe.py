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

VERSION = "0.1.5"
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


CONTAINER_KINDS = ("embedded-message", "tnef", "msg")
_ORDER = {"low": 0, "medium": 1, "high": 2}


_EXEC_MAGIC = ((b"MZ", "windows-executable"), (b"\x7fELF", "elf-executable"), (b"\xcf\xfa\xed\xfe", "macho-executable"),
               (b"\xce\xfa\xed\xfe", "macho-executable"), (b"\xca\xfe\xba\xbe", "macho-executable"), (b"#!", "script"),
               (b"L\x00\x00\x00\x01\x14\x02\x00", "windows-shortcut"))
_TYPE_MAGIC = {"pdf": (b"%PDF",), "png": (b"\x89PNG",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
               "gif": (b"GIF8",), "zip": (b"PK",), "docx": (b"PK",), "xlsx": (b"PK",), "pptx": (b"PK",),
               "doc": (b"\xd0\xcf\x11\xe0",), "xls": (b"\xd0\xcf\x11\xe0",), "ppt": (b"\xd0\xcf\x11\xe0",)}
_ACTIVE_TEXT = re.compile(rb"(?is)^(<\?xml[^>]*>\s*)?(<!doctype html|<html|<script|<svg|<hta:|<head|<body|<iframe|<form)")
_WSH = re.compile(rb"(?i)^(on error resume next|set \w+ = createobject|wscript\.|\$\w+\s*=|powershell|@echo off|"
                  rb"<job|<package|\[system\.)")
# JavaScript-like text (renamed .js): strong markers count alone, weak ones need two together
_JS_STRONG = re.compile(rb"(?i)(new\s+activexobject|wscript\.shell|\beval\s*\(|fromcharcode\s*\(|document\.write\s*\(|"
                        rb"\bshell\.application|\bcreateobject\s*\()")
_JS_WEAK = (re.compile(rb"\bfunction\s*\w*\s*\([^)]*\)\s*\{"), re.compile(rb"\b(var|let|const)\s+\w+\s*="),
            re.compile(rb"\breturn\b[^;\n]*;"), re.compile(rb"=>\s*\{"), re.compile(rb"\)\s*;\s*\}"))
TEXT_EXTS = {"txt", "text", "log", "csv", "md", "ini", "cfg", "json", "xml", "dat", ""}
# reasons that keep a file out of the output folder unless --include-risky (then saved as .quarantine)
HOLD_BACK = {"content-does-not-match-extension", "script-like-text", "unreadable-container",
             "damaged-compound-file"}


def _normalize(head):
    """Bytes as an opener would see them: UTF-16 (BOM or alternating nulls) decoded to UTF-8, a
    UTF-8 BOM, leading whitespace and leading NUL padding removed."""
    h = head
    def _text16(x):  # UTF-16 without a BOM only if the other bytes are printable ASCII
        return len(x) >= 16 and x.count(0) >= 6 and all(32 <= c < 127 or c in (9, 10, 13) for c in x if c)
    if h[:2] in (b"\xff\xfe", b"\xfe\xff") or \
            (h[1:16:2].count(0) >= 6 and _text16(h[:16])) or (h[0:16:2].count(0) >= 6 and _text16(h[:16])):
        enc = "utf-16" if h[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-16-le" if h[1:16:2].count(0) >= 6 else "utf-16-be")
        try:
            h = h[: len(h) - len(h) % 2].decode(enc, "ignore").encode("utf-8", "ignore")
        except (LookupError, ValueError):
            pass
    if h.startswith(b"\xef\xbb\xbf"):
        h = h[3:]
    return h.lstrip(b"\x00\t\r\n\x0b\x0c ")


def _find_pe(data, limit=4096):
    """An MZ header within the first bytes whose e_lfanew points at a PE signature: junk before MZ."""
    k = data.find(b"MZ", 0, limit)
    while k != -1:
        if len(data) >= k + 0x40:
            off = int.from_bytes(data[k + 0x3c:k + 0x40], "little")
            if 0 < off < 4096 and data[k + off:k + off + 4] == b"PE\x00\x00":
                return k
        k = data.find(b"MZ", k + 1, limit)
    return -1


def content_risk(data, name):
    """Reasons from the bytes, not the name: executable or script content, or bytes that do not
    match the claimed type (fake.pdf holding MZ). Checks run after _normalize, so a BOM, UTF-16,
    whitespace or NUL padding in front does not hide the content. A type check, not a scan."""
    if not data:
        return []
    raw, e, out = data[:8192], ext_of(name or ""), []
    head = _normalize(raw)
    bin_head = (raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).lstrip(b"\x00\t\r\n\x0b\x0c ")
    for sig, what in _EXEC_MAGIC:
        if bin_head.startswith(sig) or head.startswith(sig):
            out.append("executable-content:" + what)
            break
    else:
        if _find_pe(raw) > 0:
            out.append("executable-content:windows-executable")
        elif b"\x7fELF" in raw[:1024]:
            out.append("executable-content:elf-executable")
    if _ACTIVE_TEXT.match(head) and e not in ("html", "htm", "svg", "xml"):
        out.append("executable-content:html-or-script")
    elif _WSH.match(head) and e not in ("vbs", "ps1", "bat", "cmd", "js", "wsf"):
        out.append("executable-content:script")
    elif e in TEXT_EXTS and e not in ("json", "xml"):
        if _JS_STRONG.search(head):
            out.append("executable-content:script")
        elif sum(1 for r in _JS_WEAK if r.search(head)) >= 2:
            out.append("script-like-text")
    want = _TYPE_MAGIC.get(e)
    if want and not any(head[:8].startswith(w) or (e == "pdf" and w in raw[:1024]) for w in want):
        out.append("content-does-not-match-extension")
    return list(dict.fromkeys(out))


def kind_risk(kind, risk, reasons, data=None, name=None):
    """Raise risk by what the bytes are, not the name: a nested message or TNEF found by content is a container
    (at least medium) whatever its filename; an OLE object is high."""
    reasons = list(reasons)
    if kind in CONTAINER_KINDS:
        reasons += ["container", "nested-message"]
        if _ORDER[risk] < 1:
            risk = "medium"
    if kind == "ole-object":
        risk, reasons = "high", reasons + ["ole-object"]
    if kind == "file" and data:
        cr = content_risk(data, name)
        reasons += cr
        if any(x.startswith("executable-content") for x in cr):
            risk = "high"
        elif cr and _ORDER[risk] < 1:
            risk = "medium"
    if HOLD_BACK & set(reasons) and _ORDER[risk] < 1:
        risk = "medium"
    return risk, list(dict.fromkeys(reasons))


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
    if (ct.startswith(("text/plain", "image/", "audio/", "video/")) or ct == "application/pdf") and \
            (e in OUTLOOK_BLOCKED or e in ACTIVE_WEB or e in MACRO_OFFICE):
        reasons.append("content-type-mismatch")  # declared harmless type, active extension: a disguise
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
# a host-like token anywhere in link text ("Please visit https://paypal.com now")
_HOSTTOKEN = re.compile(r"(?i)(?<![\w@.\-])(https?://)?((?:[a-z0-9\u00a1-\uffff-]+\.)+[a-z\u00a1-\uffff]{2,63})(?=[/:?#\s,;.)!\"'>\]]|$)")
_FILEISH = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "zip", "rar", "7z", "png", "jpg",
            "jpeg", "gif", "htm", "html", "js", "exe", "msg", "eml", "ics", "dat", "xml", "json", "php", "asp",
            "aspx", "py", "sh", "bat", "cmd", "ps1", "vbs", "iso", "img", "svg", "rtf", "odt", "md"}


def shown_hosts(text):
    """Every host the link text shows: a token with http(s):// always counts; a bare name counts
    unless it looks like a file name (invoice.pdf). Email addresses are ignored."""
    out = []
    for m in _HOSTTOKEN.finditer(text):
        h = m.group(2).lower()
        if m.group(1) or h.rsplit(".", 1)[-1] not in _FILEISH:
            out.append(h)
    return out[:20]


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
        shown = [m.group(1).lower()] if m and "@" not in tx else []
        shown += shown_hosts(tx)  # also a host anywhere in the text, not only at the start
        if host and any(registrable(s) != registrable(host) for s in shown):
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
_LOCK = threading.Lock()  # print lock: exactly one result is printed
_WRITE_LOCK = threading.Lock()  # write lock: see guarded()
_RUN = {"done": False, "cleanup": [], "timer": None, "committed": False}


def guarded():
    """Hold this around each write step that the watchdog must not interrupt halfway (one file, the
    final rename). It is the write lock, separate from the print lock; the watchdog takes it before
    cleaning up, so it fires only between steps and its cleanup never races a write in progress.
    Do not call emit or fail while holding it."""
    return _WRITE_LOCK


def committed():
    """Call while holding guarded() right after the output is renamed into place: from then on the
    timeout is ignored and the normal result (which reports the saved files) is printed."""
    _RUN["committed"] = True


def _scrub(d):
    """Error and incomplete texts can quote file bytes (names, header values): strip terminal escape
    codes, other controls, bidi and zero-width characters before they reach a terminal or a log."""
    if d.get("error") is not None:
        d["error"] = clean_text(str(d["error"]).replace("\n", " "), 2000)
    for k in ("incomplete", "warnings", "cleanup"):
        if isinstance(d.get(k), list):
            d[k] = [clean_text(str(x).replace("\n", " "), 1000) for x in d[k]]
    return d


def emit(obj, as_json, human):
    """Print JSON or the human text. obj must have ok and error."""
    _scrub(obj)
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
    _scrub(d)
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
        # write lock first (waits for a file write or the rename in progress), then the print lock;
        # the main thread never holds the print lock while holding the write lock, so no deadlock
        with _WRITE_LOCK, _LOCK:
            if _RUN["done"] or _RUN["committed"]:
                return  # the result is out, or the output is committed and its result follows
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
                _scrub(d)
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
    "attachment contents are not scanned for malware; risk comes from names, declared types and a first-bytes type check (not a scan)",
    "DKIM and SPF are not re-verified; Authentication-Results are read as written",
    "encrypted (S/MIME, OME) content is not decrypted",
    "OLE objects and reference (cloud) attachments are not decoded or followed",
    "the domain comparison uses a two- or three-label approximation, not the Public Suffix List",
]
