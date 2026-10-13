#!/usr/bin/env python3
"""Smoke tests for the microsoft-outlook skill. Run: python tests/smoke_test.py [-v]

Builds fixtures in a temp folder with tests/make_fixtures.py (synthetic files written from the
MS-CFB, MS-OXMSG, MS-OXTNEF, RFC 5322 and RFC 5545 specs), then runs every script, every
refusal and the security canaries. Needs only Python 3.9+.

Optional cross-check: set XCHECK_PYTHON to a Python that has olefile and extract-msg installed;
the .msg fixture is then read by those independent libraries too. Otherwise that test SKIPs.

Prints PASS / FAIL / SKIP per test and a summary; exit 1 if anything failed.
"""
import http.server
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import make_fixtures  # noqa: E402
import mailsafe  # noqa: E402

VERBOSE = "-v" in sys.argv
TMP = tempfile.mkdtemp(prefix="outlook-skill-test-")
RESULTS = []


class Skip(Exception):
    pass


# Canary web server: any request is a failure (scripts must never fetch).
HITS = []


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GIF89a")

    def log_message(self, *a):
        pass


SRV = http.server.HTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
CANARY = "http://127.0.0.1:%d/pixel.gif" % SRV.server_port
FX = make_fixtures.build_all(os.path.join(TMP, "fx"), CANARY)


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                       capture_output=True, text=True, timeout=120, cwd=TMP)
    data = None
    if any(str(x).startswith("--js") for x in args):
        try:
            data = json.loads(p.stdout)
        except ValueError:
            pass
    return p.returncode, data, p.stdout + p.stderr


def test(name):
    def deco(fn):
        def wrapped():
            try:
                fn()
                RESULTS.append((name, "PASS", ""))
            except Skip as e:
                RESULTS.append((name, "SKIP", str(e)))
            except AssertionError as e:
                RESULTS.append((name, "FAIL", str(e)))
            except Exception as e:  # noqa
                RESULTS.append((name, "FAIL", "%s: %s" % (type(e).__name__, e)))
        wrapped.__name__ = fn.__name__
        TESTS.append(wrapped)
        return wrapped
    return deco


TESTS = []


def kinds(r):
    return [k["kind"] for k in r["risks"]]


def write(name, data):
    p = os.path.join(TMP, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


# ---------------- inspect_mail: .eml ----------------
@test("eml: phishing traps reported")
def _():
    c, r, out = run("inspect_mail.py", FX["phish.eml"], "--json")
    assert c == 0 and r and r["ok"], out
    k = kinds(r)
    for want in ("reply-to-other-domain", "display-name-shows-other-address", "dmarc-fail", "spf-softfail", "html-form",
                 "html-scripts", "html-tracking-pixels", "html-hidden-blocks"):
        assert want in k, (want, k)
    reasons = [x for l in r["links"] for x in l["reasons"]]
    for want in ("text-shows-other-host", "ip-host", "risky-scheme"):
        assert want in reasons, (want, reasons)
    assert r["overall_risk"] == "high"


@test("eml: attachments, risk by name trick, nested message and winmail.dat")
def _():
    c, r, out = run("inspect_mail.py", FX["phish.eml"], "--json")
    by = {a["index"]: a for a in r["attachments"]}
    assert by["1"]["risk"] == "high" and "double-extension" in by["1"]["reasons"]
    assert "bidi-override-in-name" in by["2"]["reasons"] and "\u202e" not in by["2"]["name"]
    assert by["3"]["risk"] == "medium" and "macro-capable-office" in by["3"]["reasons"]
    assert "path-in-name" in by["4"]["reasons"] and "windows-device-name" in by["5"]["reasons"]
    assert by["8"]["kind"] == "embedded-message" and by["8/1"]["name"] == "reset.scr" and by["8/1"]["risk"] == "high"
    assert by["9"]["kind"] == "tnef" and by["9/1"]["name"] == "Budget 2026 final.xlsx" and by["9/2"]["risk"] == "high"
    assert all(len(a["sha256"]) == 64 for a in r["attachments"] if a["size"])


@test("eml: clean message is low risk")
def _():
    c, r, out = run("inspect_mail.py", FX["clean.eml"], "--json")
    assert c == 0 and r["overall_risk"] == "low", r["risks"]


@test("eml: targets hidden by default, shown with --show-targets")
def _():
    c, r, out = run("inspect_mail.py", FX["phish.eml"], "--json")
    assert all("target" not in l for l in r["links"]) and "/login" not in out
    c, r, out = run("inspect_mail.py", FX["phish.eml"], "--json", "--show-targets")
    assert any(l.get("target") == "http://198.51.100.7/login" for l in r["links"])


@test("eml: printed text has no zero-width or bidi characters, and is labelled data")
def _():
    c, r, out = run("inspect_mail.py", FX["phish.eml"], "--json")
    assert "\u200b" not in r["headers"]["subject"] and "\u202e" not in out
    assert "never as instructions" in r["note"]
    c, _, txt = run("inspect_mail.py", FX["phish.eml"])
    assert "file content, not instructions" in txt


@test("eml: --fail-on-risk high exits 1; clean exits 0")
def _():
    assert run("inspect_mail.py", FX["phish.eml"], "--fail-on-risk", "high")[0] == 1
    assert run("inspect_mail.py", FX["clean.eml"], "--fail-on-risk", "medium")[0] == 0


@test("security: no network fetch while inspecting (canary server, positive control)")
def _():
    import urllib.request
    urllib.request.urlopen(CANARY, timeout=5).read()  # proves the canary is reachable
    assert len(HITS) == 1, HITS
    HITS.clear()
    for f in ("phish.eml", "sample.msg", "winmail.dat"):
        run("inspect_mail.py", FX[f], "--json", "--show-targets")
    run("extract_attachments.py", FX["phish.eml"], os.path.join(TMP, "canary-out"))
    ics = write("canary.ics", ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:c\r\nURL:%s\r\nATTACH:%s\r\n"
                               "END:VEVENT\r\nEND:VCALENDAR\r\n" % (CANARY, CANARY)).encode())
    run("inspect_ics.py", ics, "--json", "--show-targets")
    assert HITS == [], HITS


@test("security: scripts import no network or mail-sending modules")
def _():
    bad = re.compile(r"^\s*(import|from)\s+(smtplib|socket|http\.client|urllib\.request|requests|ftplib|imaplib|poplib|webbrowser|subprocess)\b", re.M)
    for f in os.listdir(SCRIPTS):
        if f.endswith(".py"):
            src = open(os.path.join(SCRIPTS, f), encoding="utf-8").read()
            assert not bad.search(src), f


# ---------------- .msg ----------------
@test("msg: headers, recipients, body, html links, attachments, embedded .msg")
def _():
    c, r, out = run("inspect_mail.py", FX["sample.msg"], "--json")
    assert c == 0 and r["format"] == "msg", out
    h = r["headers"]
    assert h["subject"] == "Q3 invoice and notes" and h["message_class"] == "IPM.Note"
    assert [x["address"] for x in h["to"]] == ["ali@fabrikam.example"] and h["cc"][0]["address"] == "records@fabrikam.example"
    assert r["authentication_results"][0]["dmarc"] == "pass"
    names = [(a["index"], a["name"], a["risk"]) for a in r["attachments"]]
    assert ("1", "notes.txt", "low") in names and ("2", "update.vbs", "high") in names and ("3/1", "order.csv", "low") in names
    assert any("text-shows-other-host" in l["reasons"] for l in r["links"])


@test("msg: independent readers agree (olefile, extract-msg via XCHECK_PYTHON)")
def _():
    py = os.environ.get("XCHECK_PYTHON")
    if not py:
        raise Skip("set XCHECK_PYTHON to a Python with olefile and extract-msg")
    code = ("import sys,extract_msg,olefile\nm=extract_msg.openMsg(sys.argv[1])\n"
            "olefile.OleFileIO(sys.argv[1])\nprint(m.subject);print(len(m.attachments))\n"
            "print([a.longFilename for a in m.attachments])")
    p = subprocess.run([py, "-c", code, FX["sample.msg"]], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-500:]
    lines = p.stdout.splitlines()
    assert lines[0] == "Q3 invoice and notes" and lines[1] == "3" and "original.msg" in lines[2], p.stdout


def _cfb_header_patch(data, off, fmt, val):
    b = bytearray(data)
    struct.pack_into(fmt, b, off, val)
    return bytes(b)


@test("msg hardening: truncated, looping chain, bad header and random bytes exit 2 fast")
def _():
    good = open(FX["sample.msg"], "rb").read()
    cases = {"trunc.msg": good[:1500], "badver.msg": _cfb_header_patch(good, 0x1A, "<H", 7),
             "noise.msg": good[:8] + os.urandom(4000)}
    import msgcfb
    cf = msgcfb.Cfb(good)
    b = bytearray(good)
    fat_sector = struct.unpack_from("<I", good, 0x4C)[0]
    # make the directory chain loop onto itself
    dir1 = struct.unpack_from("<I", good, 0x30)[0]
    struct.pack_into("<I", b, (fat_sector + 1) * 512 + dir1 * 4, dir1)
    cases["loop.msg"] = bytes(b)
    for n, d in cases.items():
        c, r, out = run("inspect_mail.py", write(n, d), "--json")
        assert c == 2 and r and r["ok"] is False and "Traceback" not in out, (n, c, out[-300:])
    assert cf.entries[0]["type"] == 5


@test("msg hardening: directory cycle is refused")
def _():
    import msgcfb
    good = open(FX["sample.msg"], "rb").read()
    cf = msgcfb.Cfb(good)
    dir1 = struct.unpack_from("<I", good, 0x30)[0]
    b = bytearray(good)
    root_child = cf.entries[0]["child"]
    off = (dir1 + 1) * 512 + root_child * 128 + 72  # right sibling -> itself
    struct.pack_into("<I", b, off, root_child)
    c, r, out = run("inspect_mail.py", write("cycle.msg", bytes(b)), "--json")
    assert c == 2 and "directory" in r["error"], out


# ---------------- TNEF ----------------
@test("tnef: long file name from attMAPIProps, 8.3 fallback, checksums ok")
def _():
    c, r, out = run("inspect_mail.py", FX["winmail.dat"], "--json")
    assert c == 0 and r["format"] == "tnef"
    assert [a["name"] for a in r["attachments"]] == ["Budget 2026 final.xlsx", "run.js"]
    assert r["headers"]["subject"] == "Budget from classic Outlook" and not r["warnings"]


@test("tnef: bad checksum is a warning; length past end exits 2")
def _():
    d = bytearray(open(FX["winmail.dat"], "rb").read())
    d[-1] ^= 0xFF
    c, r, out = run("inspect_mail.py", write("badck.dat", bytes(d)), "--json")
    assert c == 0 and any("checksum" in w for w in r["warnings"]), out
    d = bytearray(open(FX["winmail.dat"], "rb").read())
    struct.pack_into("<I", d, 6 + 1 + 4, 0x7FFFFFFF)
    c, r, out = run("inspect_mail.py", write("badlen.dat", bytes(d)), "--json")
    assert c == 2 and r["ok"] is False, out


@test("tnef: matches tnefparse on its sample corpus (TNEF_CORPUS + XCHECK_PYTHON)")
def _():
    corpus, py = os.environ.get("TNEF_CORPUS"), os.environ.get("XCHECK_PYTHON")
    if not corpus or not py:
        raise Skip("set TNEF_CORPUS to tnefparse's tests/examples and XCHECK_PYTHON to a Python with tnefparse")
    import glob
    import tnef
    files = sorted(glob.glob(os.path.join(corpus, "*.tnef")))
    code = ("import sys,json,tnefparse\nout=[]\nfor f in sys.argv[1:]:\n t=tnefparse.TNEF(open(f,'rb').read())\n"
            " out.append([a.long_filename() for a in t.attachments])\nprint(json.dumps(out))")
    p = subprocess.run([py, "-c", code] + files, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-300:]
    theirs = json.loads(p.stdout)
    ours = [[a["filename"] for a in tnef.parse(open(f, "rb").read())["attachments"]] for f in files]
    assert ours == theirs and len(files) >= 10, (len(files), [f for f, a, b in zip(files, ours, theirs) if a != b])


@test("docs: SKILL.md sample JSON matches the script's real output")
def _():
    md = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    block = re.search(r"```json\n(.*?)```", md, re.S).group(1)
    c, r, _ = run("inspect_mail.py", FX["phish.eml"], "--json")
    shown = json.loads(block.replace(', ..."', '"'))
    for k in ("status", "complete", "incomplete", "overall_risk"):
        assert shown[k] == r[k], k
    assert shown["risks"][0] in r["risks"]
    a = shown["attachments"][0]
    real = [x for x in r["attachments"] if x["index"] == a["index"]][0]
    assert all(real[k] == v for k, v in a.items()), real
    assert any(n.startswith(shown["not_checked"][0].rstrip(".")[:40]) for n in r["not_checked"])


# ---------------- extract_attachments ----------------
@test("extract: dry run writes nothing")
def _():
    out = os.path.join(TMP, "dry")
    c, r, txt = run("extract_attachments.py", FX["phish.eml"], out, "--dry-run", "--json")
    assert r["ok"] and r["dry_run"] and not os.path.exists(out), txt


@test("extract: risky skipped (exit 1), safe names, no exec bits, manifest, nothing outside")
def _():
    out = os.path.join(TMP, "x1")
    before = set(os.listdir(TMP))
    c, r, txt = run("extract_attachments.py", FX["phish.eml"], out, "--json")
    assert c == 1 and r["skipped_risky"] == 4, (c, txt[-400:])
    files = sorted(os.listdir(out))
    assert "outside.txt" in files and "_CON.txt" in files and "Readme.txt" in files and "README (2).TXT" in files, files
    assert not any(f.endswith((".exe", ".scr", ".js")) for f in files), files
    for f in files:
        mode = os.stat(os.path.join(out, f)).st_mode
        assert not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), f
    assert set(os.listdir(TMP)) - before == {"x1"}, set(os.listdir(TMP)) - before
    assert not os.path.exists(os.path.join(os.path.dirname(TMP), "outside.txt"))
    man = json.load(open(os.path.join(out, "manifest.json")))
    assert len(man["attachments"]) == 12


@test("extract: --include-risky saves as .quarantine; exit 0")
def _():
    out = os.path.join(TMP, "x2")
    c, r, txt = run("extract_attachments.py", FX["phish.eml"], out, "--include-risky", "--json")
    files = os.listdir(out)
    assert c == 0 and "invoice.pdf.exe.quarantine" in files and "run.js.quarantine" in files, (c, files)
    assert not any("\u202e" in f for f in files)


@test("extract: refuses existing OUTDIR (exit 3); a symlinked parent (macOS /tmp) is resolved and allowed")
def _():
    os.makedirs(os.path.join(TMP, "exists"), exist_ok=True)
    c, r, _ = run("extract_attachments.py", FX["clean.eml"], os.path.join(TMP, "exists"), "--json")
    assert c == 3 and r["ok"] is False
    real = os.path.join(TMP, "realdir")
    os.makedirs(real, exist_ok=True)
    link = os.path.join(TMP, "linkdir")
    if not os.path.lexists(link):
        os.symlink(real, link)
    c, r, _ = run("extract_attachments.py", FX["phish.eml"], os.path.join(link, "o"), "--json", "--include-risky")
    assert c == 0 and r["outdir"] == os.path.join(os.path.realpath(real), "o"), r
    assert os.listdir(os.path.join(real, "o"))
    m = os.path.join(real, "o", "manifest.json")
    assert stat.S_IMODE(os.stat(m).st_mode) == 0o600


@test("extract: --max-total refuses and leaves no folder")
def _():
    out = os.path.join(TMP, "x3")
    c, r, _ = run("extract_attachments.py", FX["sample.msg"], out, "--max-total", "100", "--json")
    assert c == 3 and not os.path.exists(out) and not [f for f in os.listdir(TMP) if f.startswith(".extract-")]


@test("extract: .msg attachments including embedded message, --only")
def _():
    out = os.path.join(TMP, "x4")
    c, r, _ = run("extract_attachments.py", FX["sample.msg"], out, "--only", "1,3/1", "--json")
    assert c == 0 and sorted(f for f in os.listdir(out) if f != "manifest.json") == ["notes.txt", "order.csv"]
    assert open(os.path.join(out, "order.csv"), "rb").read() == b"id,qty\n1,2\n"


@test("v0.1.1 H1: MIME nesting past the cap is reported incomplete, never a clean ok; extract fails closed")
def _():
    inner = b"Content-Type: text/plain\r\n\r\nsecret payload https://deep.example/x\r\n"
    for i in range(60):
        b = b"b%d" % i
        inner = (b"Content-Type: multipart/mixed; boundary=" + b + b"\r\n\r\n--" + b + b"\r\n" + inner +
                 b"\r\n--" + b + b"--\r\n")
    p = write("deep.eml", b"From: a@example.com\r\nSubject: deep\r\nMIME-Version: 1.0\r\n" + inner)
    c, r, _ = run("inspect_mail.py", p, "--json")
    assert c == 1 and r["complete"] is False and r["status"] == "incomplete" and r["incomplete"], r.get("incomplete")
    assert r["risks"][0]["kind"] == "parse-incomplete" and r["overall_risk"] in ("medium", "high")
    assert run("inspect_mail.py", p, "--json", "--allow-incomplete")[0] == 0
    c, r, _ = run("extract_attachments.py", p, os.path.join(TMP, "deep-out"), "--json")
    assert c == 1 and r["status"] == "incomplete" and not os.path.exists(os.path.join(TMP, "deep-out"))


@test("v0.1.1: attachment count cap refuses (exit 3) for .eml; huge boundary counts refused before parsing")
def _():
    parts = b"".join(b"--B\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; "
                     b"filename=f%d.bin\r\n\r\nx\r\n" % i for i in range(30))
    p = write("many.eml", b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B"
              b"\r\n\r\n" + parts + b"--B--\r\n")
    c, r, _ = run("extract_attachments.py", p, os.path.join(TMP, "many-out"), "--max-attachments", "20", "--json")
    assert c == 3 and r["status"] == "refused" and not os.path.exists(os.path.join(TMP, "many-out")), r
    assert run("inspect_mail.py", p, "--json", "--max-attachments", "20")[0] == 3
    assert run("inspect_mail.py", p, "--json")[0] == 0
    big = b"".join(b"--B\r\nContent-Disposition: attachment; filename=f%d\r\n\r\nx\r\n" % i for i in range(6000))
    big = write("big.eml", b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n"
                + big + b"--B--\r\n")
    c, r, _ = run("extract_attachments.py", big, os.path.join(TMP, "big-out"), "--json")
    assert c == 3 and not os.path.exists(os.path.join(TMP, "big-out")), r
    q = write("bounds.eml", b"From: a@example.com\r\n\r\n" + b"boundary=x\r\n" * 2100)
    assert run("inspect_mail.py", q, "--json")[0] == 3


@test("v0.1.1: --timeout refuses with exit 3; usage errors are JSON under --json; --version")
def _():
    parts = b"".join(b"--B\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename=f%d.txt"
                     b"\r\n\r\n%s\r\n" % (i, b"y" * 2000) for i in range(400))
    p = write("slow.eml", b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B"
              b"\r\n\r\n" + parts + b"--B--\r\n")
    c, r, _ = run("inspect_mail.py", p, "--json", "--timeout", "0.01")
    assert c == 3 and "time limit" in r["error"] and r["status"] == "refused", r
    c, r, _ = run("inspect_mail.py", p, "--json", "--fail-on-risk", "bogus")
    assert c == 2 and r["status"] == "error" and r["error"].startswith("usage"), r
    for sc in ("inspect_mail.py", "extract_attachments.py", "inspect_ics.py"):
        cp = subprocess.run([sys.executable, os.path.join(SCRIPTS, sc), "--version"], capture_output=True, text=True)
        assert cp.returncode == 0 and cp.stdout.strip() == mailsafe.VERSION, (sc, cp.stdout)


@test("v0.1.1: JSON has schema, status, complete, not_checked; remote images are a risk")
def _():
    c, r, _ = run("inspect_mail.py", FX["phish.eml"], "--json")
    for k in ("schema", "status", "complete", "incomplete", "not_checked", "risks", "overall_risk"):
        assert k in r, k
    assert r["schema"] == "microsoft-outlook/inspect-mail/1" and isinstance(r["not_checked"], list)
    c, r2, _ = run("inspect_mail.py", FX["phish.eml"], "--json", "--fail-on-risk", "medium")
    assert c == 1 and r2["status"] == "risk-threshold"
    html = (b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: text/html\r\n\r\n"
            b"<p>hi<img src=\"https://t.example/p.gif\" width=1 height=1></p>")
    c, r, _ = run("inspect_mail.py", write("img.eml", html), "--json")
    assert "html-remote-images" in kinds(r) and "html-tracking-pixels" in kinds(r)


@test("v0.1.1 unit: risk rules (long names keep extension, .dat/TNEF containers, html high, %-host)")
def _():
    long = "invoice" + " " * 400 + "x" * 300 + ".exe"
    assert mailsafe.attachment_risk(long)[0] == "high"
    sf = mailsafe.safe_filename("a" * 400 + ".exe")
    assert sf.endswith(".exe") and len(sf.encode()) <= 150
    assert mailsafe.attachment_risk("winmail.dat")[0] == "medium"
    assert mailsafe.attachment_risk("x.bin", "application/ms-tnef")[0] == "medium"
    assert mailsafe.attachment_risk("Payment.html")[0] == "high"
    a = mailsafe.analyze_url("https://login.example.com%2F@evil.example/")
    assert a["risk"] == "high"
    a = mailsafe.analyze_url("https://paypal.com%2Eevil.example/")
    assert "encoded-chars-in-host" in a["reasons"] and a["risk"] == "high", a


@test("v0.1.1 unit: short CFB error names truncation; TNEF MAPI failure is incomplete, not a soft ok")
def _():
    import msgcfb, tnef, mailparse
    try:
        msgcfb.Cfb(msgcfb.SIG + b"\0" * 20)
        raise AssertionError("no error")
    except msgcfb.CfbError as e:
        assert "truncated" in str(e)
    data = open(FX["winmail.dat"], "rb").read()
    # corrupt the first MAPI property block (attMsgProps 0x00069003) length so its parse fails
    i = data.find(struct.pack("<I", 0x00069003))
    if i > 0:
        ln = struct.unpack_from("<I", data, i + 4)[0]
        body = data[i + 8:i + 8 + ln]
        bad = struct.pack("<I", 0xFFFF) + body[4:]
        ck = sum(bad) & 0xFFFF
        data2 = data[:i + 8] + bad + struct.pack("<H", ck) + data[i + 10 + ln:]
        m = mailparse.parse_bytes(data2)
        assert m["incomplete"] and "properties" in m["incomplete"][0], m["incomplete"]


@test("v0.1.1 unit: compressed RTF (MS-OXRTFCP) round trip and HTML de-encapsulation (MS-OXRTFEX)")
def _():
    import rtfbody
    rtf = (b"{\\rtf1\\ansi\\ansicpg1252\\fromhtml1 {\\*\\htmltag19 <html>}{\\*\\htmltag84 <a href=\"https://e.example/\">}"
           b"\\htmlrtf {\\htmlrtf0 Caf\\'e9 \\u8364?{\\*\\htmltag92 </a>}\\htmlrtf }\\htmlrtf0 {\\*\\htmltag27 </html>}}")
    comp = make_fixtures.lzfu_literal(rtf)
    out, w, dmg = rtfbody.decompress(comp)
    assert out == rtf and not w and not dmg, (w, dmg)
    b = rtfbody.to_body(out)
    assert b["kind"] == "html" and b["content"] == '<html><a href="https://e.example/">Caf\u00e9 \u20ac</a></html>', b
    # a back-reference into the preloaded dictionary: "{\\rtf1" sits at offset 0, length 6
    end = struct.pack(">H", ((207 + 8) & 0xFFF) << 4)
    body = bytes([0b00001001]) + struct.pack(">H", (0 << 4) | (6 - 2)) + b"x}" + end
    data = struct.pack("<IIII", len(body) + 12, 8, rtfbody.LZFU, rtfbody.crc32(body)) + body
    out, w, dmg = rtfbody.decompress(data)
    assert out == b"{\\rtf1x}" and not w and not dmg, (out, w, dmg)
    try:
        rtfbody.decompress(b"\0" * 8)
        raise AssertionError("no error")
    except rtfbody.RtfError:
        pass
    if os.environ.get("XCHECK_PYTHON"):
        code = ("import sys,compressed_rtf;sys.path.insert(0,%r);import rtfbody,os;"
                "d=os.urandom(5000)+b'abcabcabc'*300;assert rtfbody.decompress(compressed_rtf.compress(d))==(d,[],[]);"
                "print('ok')" % SCRIPTS)
        cp = subprocess.run([os.environ["XCHECK_PYTHON"], "-c", code], capture_output=True, text=True)
        assert cp.stdout.strip() == "ok", cp.stderr


@test("v0.1.1 unit: Windows zone table and DST gap / overlap flags")
def _():
    import inspect_ics, zoneinfo
    assert inspect_ics.windows_to_iana("Pakistan Standard Time") == "Asia/Karachi"
    assert inspect_ics.windows_to_iana("Eastern Standard Time") == "America/New_York"
    import datetime as dtm
    ny = zoneinfo.ZoneInfo("America/New_York")
    assert inspect_ics._local_check(dtm.datetime(2026, 3, 8, 2, 30), ny) == "nonexistent"
    assert inspect_ics._local_check(dtm.datetime(2026, 11, 1, 1, 30), ny) == "ambiguous"
    assert inspect_ics._local_check(dtm.datetime(2026, 7, 1, 9, 0), ny) is None


@test("release: SKILL.md frontmatter is valid and matches the folder")
def _():
    src = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    assert src.startswith("---\n")
    fm = src.split("---\n", 2)[1]
    name = re.search(r"(?m)^name: (.+)$", fm).group(1).strip()
    desc = re.search(r"(?m)^description: (.+)$", fm).group(1).strip()
    assert name == "microsoft-outlook" and re.fullmatch(r"[a-z0-9-]{1,64}", name)
    assert 50 <= len(desc) <= 1024 and "<" not in desc
    assert re.search(r'(?m)^\s+version: "\d+\.\d+\.\d+"$', fm)
    top = re.findall(r"(?m)^([A-Za-z][\w-]*):", fm)
    allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    assert set(top) <= allowed and {"name", "description"} <= set(top), top
    assert len(top) == len(set(top)), "duplicate top-level key"
    comp = re.search(r'(?m)^compatibility: (.+)$', fm).group(1)
    assert len(comp.strip('"')) <= 500


@test("v0.1.2 RTF hardening: hostile RTF marks the parse incomplete or decodes safely, never exit 2")
def _():
    import mailparse, rtfbody
    cases = {
        "huge-u": b"{\\rtf1\\ansi \\u9999999999 ? and \\u-99999 ? done}",
        "bad-cp": b"{\\rtf1\\ansi\\ansicpg1200 caf\\'e9}",
        "bin": b"{\\rtf1\\ansi \\bin5 HELLO after}",
        "deep": b"{\\rtf1 " + b"{" * 250 + b"x" + b"}" * 250 + b"}",
    }
    for k, rtf in cases.items():
        m = mailparse._new("msg")
        mailparse._rtf_body(m, make_fixtures.lzfu_literal(rtf))
        if k == "deep":
            assert m["incomplete"] and "nesting" in m["incomplete"][0], m
        else:
            assert not m["incomplete"], (k, m["incomplete"])
    assert "\ufffd" in rtfbody.to_body(cases["huge-u"])["content"]
    assert rtfbody.to_body(cases["bad-cp"])["content"].startswith("caf")
    assert rtfbody.to_body(cases["bin"])["content"].strip() == "after"
    # MELA (uncompressed) with a nonzero CRC field is damaged; LZFu CRC mismatch too
    body = b"{\\rtf1 hi}"
    mela = struct.pack("<IIII", len(body) + 12, len(body), rtfbody.MELA, 1234) + body
    m = mailparse._new("msg")
    mailparse._rtf_body(m, mela)
    assert m["text"] == "hi" and any("CRC" in x for x in m["incomplete"]), m
    bad = bytearray(make_fixtures.lzfu_literal(body))
    bad[12] ^= 0xFF
    m = mailparse._new("msg")
    mailparse._rtf_body(m, bytes(bad))
    assert any("CRC" in x for x in m["incomplete"]), m
    # output cap on a single huge text run
    out = rtfbody.to_body(b"{\\rtf1 " + b"a" * 5000 + b"}", max_out=1000)
    assert len(out["content"]) <= 1000 and out["truncated"]


@test("v0.1.2: an Outlook .msg or winmail.dat attached under any name is detected by bytes and parsed")
def _():
    import base64
    msg = open(FX["sample.msg"], "rb").read()
    dat = open(FX["winmail.dat"], "rb").read()
    def part(name, data):
        return (b"--B\r\nContent-Type: application/octet-stream\r\nContent-Transfer-Encoding: base64\r\n"
                b"Content-Disposition: attachment; filename=" + name + b"\r\n\r\n" + base64.encodebytes(data) + b"\r\n")
    eml = (b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n"
           + part(b"scan.bin", msg) + part(b"data.bin", dat) + b"--B--\r\n")
    c, r, _ = run("inspect_mail.py", write("hidden-msg.eml", eml), "--json")
    kinds_ = {a["index"]: a["kind"] for a in r["attachments"]}
    assert kinds_["1"] == "msg" and kinds_["2"] == "tnef", kinds_
    assert any(i.startswith("1/") for i in kinds_) and any(i.startswith("2/") for i in kinds_), kinds_
    assert r["complete"] is True and c == 0, r["incomplete"]
    import msgcfb
    assert not msgcfb.is_msg(b"not a cfb") and msgcfb.is_msg(msg)


@test("v0.1.2: --timeout cleans the hidden .extract-* folder; the timer is cancelled on success")
def _():
    parent = os.path.join(TMP, "tparent")
    os.makedirs(parent, exist_ok=True)
    parts = b"".join(b"--B\r\nContent-Disposition: attachment; filename=f%d.bin\r\n\r\n%s\r\n" % (i, b"z" * 200000)
                     for i in range(300))
    p = write("slowwrite.eml", b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B"
              b"\r\n\r\n" + parts + b"--B--\r\n")
    for t in ("0.05", "0.3", "0.6"):
        out = os.path.join(parent, "o" + t)
        c, r, txt = run("extract_attachments.py", p, out, "--json", "--timeout", t)
        assert c in (0, 3), (c, txt[:300])
        assert not [f for f in os.listdir(parent) if f.startswith(".extract-")], os.listdir(parent)
        if c == 3:
            assert r["status"] == "refused" and not os.path.exists(out)
    # deterministic: run extract in-process, and fire the registered timeout cleanup mid-write
    import io, contextlib, extract_attachments as ex
    captured, real_on, real_rename = [], mailsafe.on_timeout, os.rename
    mailsafe.on_timeout = lambda fn: (captured.append(fn), fn)[1]
    notes = []

    def fake_rename(src, dst):
        notes.append(captured[-1]())
        raise OSError("simulated: timer fired during the write")
    os.rename = fake_rename
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ex.main([FX["phish.eml"], os.path.join(parent, "mid"), "--json", "--timeout", "0"])
    finally:
        os.rename, mailsafe.on_timeout = real_rename, real_on
        mailsafe._RUN["done"] = False
    assert rc == 3 and notes and "removed" in notes[0], notes
    assert not [f for f in os.listdir(parent) if f.startswith(".extract-")] and not os.path.exists(os.path.join(parent, "mid"))
    for _i in range(3):
        c, r, txt = run("inspect_mail.py", FX["clean.eml"], "--json", "--timeout", "2")
        assert c == 0 and txt.count('"schema"') == 1, txt[:200]


@test("v0.1.2: inspect_ics survives month 00 and year 9999 with --tz; boundary*= counts toward the cap")
def _():
    ics = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART;TZID=Pakistan Standard Time:20260014T100000\r\n"
           b"END:VEVENT\r\nBEGIN:VEVENT\r\nUID:b\r\nDTSTART:99991231T235959Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    c, r, txt = run("inspect_ics.py", write("bad-dates.ics", ics), "--json", "--tz", "Pacific/Kiritimati")
    assert c == 0 and r["ok"], txt[:300]
    assert r["events"][0]["start"]["converted"] is None and r["events"][1]["start"]["converted"] is None
    q = write("bstar.eml", b"From: a@example.com\r\n\r\n" + b"Content-Type: multipart/mixed; boundary*0=x\r\n" * 2100)
    c, r, _ = run("inspect_mail.py", q, "--json")
    assert c == 3 and "boundar" in r["error"], r


@test("v0.1.2: --js and --json=1 give JSON usage errors (no abbreviations)")
def _():
    for flag in ("--js", "--json=1"):
        c, r, txt = run("inspect_mail.py", FX["clean.eml"], flag)
        assert c == 2 and r and r["status"] == "error" and r["error"].startswith("usage"), (flag, txt[:200])


@test("v0.1.3: a .msg or TNEF found by bytes is a container (medium+) whatever its name; extract skips the container")
def _():
    import base64
    msg = open(FX["sample.msg"], "rb").read()
    dat = open(FX["winmail.dat"], "rb").read()
    def part(name, ctype, data):
        return (b"--B\r\nContent-Type: " + ctype + b"\r\nContent-Transfer-Encoding: base64\r\n"
                b"Content-Disposition: attachment; filename=" + name + b"\r\n\r\n" + base64.encodebytes(data) + b"\r\n")
    eml = (b"From: a@example.com\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n"
           + part(b"invoice.bin", b"application/octet-stream", msg) + part(b"photo.jpg", b"image/jpeg", dat) + b"--B--\r\n")
    f = write("disguised.eml", eml)
    c, r, _ = run("inspect_mail.py", f, "--json")
    top = {a["index"]: a for a in r["attachments"]}
    for i in ("1", "2"):
        assert top[i]["risk"] in ("medium", "high") and "container" in top[i]["reasons"], top[i]
    out = os.path.join(TMP, "disg-out")
    c, r, _ = run("extract_attachments.py", f, out, "--json")
    items = {i["index"]: i for i in r["attachments"]}
    assert items["1"]["saved_as"] is None and "container" in items["1"]["skipped"], items["1"]
    assert items["2"]["saved_as"] is None and "container" in items["2"]["skipped"], items["2"]
    assert "invoice.bin" not in os.listdir(out) and "photo.jpg" not in os.listdir(out), os.listdir(out)
    assert any(k.startswith("1/") and v["saved_as"] for k, v in items.items()), items
    # high-risk nested files stay skipped
    assert all(v["saved_as"] is None for v in items.values() if v["risk"] == "high")


@test("v0.1.3: --only-ext allowlist; content-type-mismatch; \\bin past EOF reported; negative \\uc clamped")
def _():
    import mailsafe, rtfbody
    out = os.path.join(TMP, "onlyext-out")
    c, r, _ = run("extract_attachments.py", FX["sample.msg"], out, "--json", "--only-ext", ".txt")
    saved = [i for i in r["attachments"] if i["saved_as"]]
    assert saved and all(i["name"].lower().endswith(".txt") for i in saved), saved
    assert any(i["skipped"] == "extension not in --only-ext" for i in r["attachments"]), r["attachments"]
    risk, reasons = mailsafe.attachment_risk("report.vbs", "text/plain")
    assert risk == "high" and "content-type-mismatch" in reasons, reasons
    assert "content-type-mismatch" not in mailsafe.attachment_risk("notes.txt", "text/plain")[1]
    b = rtfbody.to_body(b"{\\rtf1 ok \\bin100 xy}")
    assert b["truncated"] and "past the end" in b["truncated"][0], b
    b = rtfbody.to_body(b"{\\rtf1 \\uc-1 A\\u66 ?AF}")
    assert "B" in b["content"] and "\ufffd" not in b["content"], b


@test("real files: every file in REAL_FIXTURES_DIR gives JSON without a traceback (optional)")
def _():
    d = os.environ.get("REAL_FIXTURES_DIR")
    if not d:
        raise Skip("set REAL_FIXTURES_DIR to a folder of Outlook-saved .msg/.eml/winmail.dat files")
    n = 0
    for f in sorted(os.listdir(d)):
        if f.lower().rsplit(".", 1)[-1] in ("msg", "eml", "dat"):
            c, r, txt = run("inspect_mail.py", os.path.join(d, f), "--json", "--allow-incomplete")
            assert c in (0, 1, 2, 3) and r is not None and "Traceback" not in txt, (f, txt[:300])
            n += 1
    assert n, "no .msg, .eml or .dat files in REAL_FIXTURES_DIR"


# ---------------- inspect_ics ----------------
@test("ics: method, folding, quoted CN with colon, RRULE, EXDATE, Teams link")
def _():
    c, r, out = run("inspect_ics.py", FX["invite.ics"], "--json")
    assert c == 0 and r["method"] == "REQUEST", out
    e = r["events"][0]
    assert e["organizer"]["name"] == "Khan, Sara: PMO" and e["organizer"]["address"] == "sara@contoso.example"
    assert e["rrule"] == "FREQ=WEEKLY;BYDAY=WE" and e["exdates"] == 1 and e["busy_status"] == "TENTATIVE"
    hosts = [l["host"] for l in e["links"]]
    assert "teams.microsoft.com" in hosts and "192.0.2.44" in hosts, hosts


@test("ics: time zones: UTC, IANA and Windows (CLDR table) converted; Windows mapping is labelled")
def _():
    c, r, out = run("inspect_ics.py", FX["invite.ics"], "--json", "--tz", "Asia/Karachi")
    ev = r["events"]
    assert ev[0]["start"]["converted"] == "2026-10-14T10:00:00+05:00" and ev[0]["start"]["iana"] == "Asia/Karachi"
    assert "CLDR" in ev[0]["start"]["note"]
    assert ev[1]["start"]["converted"] == "2026-10-15T14:00:00+05:00"
    assert ev[2]["start"]["converted"] == "2026-10-16T18:00:00+05:00"
    assert "non-iana-tzid" in kinds(r) and "meeting-request" in kinds(r)


@test("ics: PROCEDURE alarm and file: attachment are high risk")
def _():
    c, r, out = run("inspect_ics.py", FX["invite.ics"], "--json")
    assert "alarm-action" in kinds(r) and r["overall_risk"] == "high"
    assert any(x.get("scheme") == "file" for x in r["events"][0]["attachments"])


@test("ics: not iCalendar, END mismatch exit 2; too many events, too big exit 3; bad --tz exit 2")
def _():
    assert run("inspect_ics.py", FX["clean.eml"], "--json")[0] == 2
    p = write("mismatch.ics", b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")
    assert run("inspect_ics.py", p, "--json")[0] == 2
    many = "BEGIN:VCALENDAR\r\n" + "BEGIN:VEVENT\r\nUID:x\r\nEND:VEVENT\r\n" * 20 + "END:VCALENDAR\r\n"
    assert run("inspect_ics.py", write("many.ics", many.encode()), "--max-events", "10", "--json")[0] == 3
    assert run("inspect_ics.py", FX["invite.ics"], "--max-bytes", "100", "--json")[0] == 3
    assert run("inspect_ics.py", FX["invite.ics"], "--tz", "../../etc/passwd", "--json")[0] == 2


# ---------------- general ----------------
@test("all: --max-bytes refusal exits 3; non-email exits 2; JSON has ok and error")
def _():
    c, r, _ = run("inspect_mail.py", FX["phish.eml"], "--max-bytes", "100", "--json")
    assert c == 3 and r["ok"] is False and r["error"]
    c, r, _ = run("inspect_mail.py", write("junk.bin", b"\x00\x01\x02 not mail"), "--json")
    assert c == 2 and set(r) >= {"ok", "error"}
    c, r, _ = run("inspect_mail.py", os.path.join(TMP, "missing.eml"), "--json")
    assert c == 2


@test("unit: link analysis and safe file names")
def _():
    import mailsafe as m
    assert m.analyze_url("https://login.microsoftonline.com/x", "login.microsoftonline.com")["risk"] == "low"
    assert "text-shows-other-host" in m.analyze_url("https://evil.example/", "https://www.microsoft.com")["reasons"]
    assert "userinfo-in-url" in m.analyze_url("https://www.microsoft.com@evil.example/")["reasons"]
    assert "punycode-host" in m.analyze_url("https://xn--micrsoft-q0a.com/")["reasons"]
    assert m.analyze_url("ms-msdt:/id PCWDiagnostic")["risk"] == "high"
    assert m.safe_filename("..\\..\\a.txt") == "a.txt" and m.safe_filename("nul") == "_nul"
    assert m.safe_filename("a\u202etxt.exe") == "atxt.exe" and m.safe_filename("") == "attachment"
    assert len(m.OUTLOOK_BLOCKED) == 133


@test("release: versions, names and files in step")
def _():
    pkg = json.load(open(os.path.join(ROOT, "package.json")))
    sk = json.load(open(os.path.join(ROOT, "skill.json")))
    md = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    fm = md.split("---")[1]
    ver = re.search(r'version: "([^"]+)"', fm).group(1)
    assert pkg["name"] == sk["name"] == "microsoft-outlook" and re.search(r"^name: microsoft-outlook$", fm, re.M)
    assert pkg["version"] == sk["version"] == ver
    assert ("## %s" % ver) in open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    import mailsafe
    assert mailsafe.VERSION == ver
    desc = re.search(r'description: "([^"]+)"', fm).group(1)
    assert desc.startswith("Use when") and len(desc) <= 1024
    assert len(md.splitlines()) < 500
    assert "scripts" not in pkg and "bin" not in pkg and pkg["publishConfig"]["access"] == "public"
    for f in pkg["files"]:
        assert os.path.exists(os.path.join(ROOT, f.split("*")[0].rstrip("/") or ".")), f


@test("release: no em dashes; every script documents exit codes and takes --json")
def _():
    for d, _, fs in os.walk(ROOT):
        if ".git" in d or "__pycache__" in d:
            continue
        for f in fs:
            if f.endswith((".md", ".py", ".json", ".txt")):
                assert "\u2014" not in open(os.path.join(d, f), encoding="utf-8").read(), f
    for s in ("inspect_mail.py", "extract_attachments.py", "inspect_ics.py"):
        src = open(os.path.join(SCRIPTS, s), encoding="utf-8").read()
        assert "Exit codes" in src and '"--json"' in src, s


@test("release: every --flag named in SKILL.md exists in a script")
def _():
    md = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    src = "".join(open(os.path.join(SCRIPTS, f), encoding="utf-8").read() for f in os.listdir(SCRIPTS) if f.endswith(".py"))
    src += open(os.path.abspath(__file__), encoding="utf-8").read()
    for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", md)):
        assert '"%s"' % flag in src or flag in ("--version",), flag  # --version is python's own


def main():
    for t in TESTS:
        t()
    w = max(len(n) for n, _, _ in RESULTS)
    for n, s, why in RESULTS:
        print("%-4s %s%s" % (s, n.ljust(w), ("  " + why) if why and (s != "PASS") else ""))
    p = sum(1 for _, s, _ in RESULTS if s == "PASS")
    f = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    k = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print("\n%d passed, %d failed, %d skipped" % (p, f, k))
    SRV.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if f else 0

@test("release: the packed npm artifact holds SKILL.md, every referenced file and script (optional: needs npm)")
def _():
    import shutil as _sh
    if not _sh.which("npm"):
        raise Skip("npm not on PATH")
    out = subprocess.run(["npm", "pack", "--dry-run", "--json"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    files = {f["path"] for f in json.loads(out.stdout)[0]["files"]}
    sk = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    need = {"SKILL.md", "skill.json", "LICENSE", "scripts/windows_zones.json", "scripts/LICENSE-CLDR.txt"}
    need |= set(re.findall(r"references/[\w-]+\.md", sk)) | set("scripts/" + x for x in re.findall(r"([\w]+\.py)", sk))
    need = {n for n in need if os.path.exists(os.path.join(ROOT, n))} | {"SKILL.md"}
    assert need <= files, sorted(need - files)
    assert not [f for f in files if "__pycache__" in f or f.endswith(".pyc")], "bytecode packed"



if __name__ == "__main__":
    sys.exit(main())
