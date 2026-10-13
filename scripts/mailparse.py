"""Turn an .eml, .msg or winmail.dat into one neutral model for inspect_mail.py and
extract_attachments.py. Standard library only. Nothing is fetched, opened or executed.

Model: {"format", "headers": {...}, "auth": {...}, "text", "html", "attachments": [ {name,
content_type, data, inline, content_id, kind, nested} ], "warnings", "flags", "incomplete"}.

"incomplete" lists every place where content was not read (a depth, part or size cap, a nested
item that failed to parse, unreadable MAPI properties, an undecodable body). Nested lists are
copied up to the top model, so a caller only has to look at the top level. Callers must treat a
non-empty list as "this report is partial", never as a clean result.
"""
import email
import email.policy
import email.utils
import hashlib
import re
import struct
from html.parser import HTMLParser

import msgcfb
import rtfbody
import tnef
import mailsafe

MAX_DEPTH = 4
MAX_MIME_DEPTH = 50
LIMITS = {"max_attachments": 500}
_count = {"n": 0}


class MailError(Exception):
    pass


class LimitError(Exception):
    """A safety cap that makes the scripts refuse (exit 3) instead of returning a partial view."""


def _new(fmt):
    return {"format": fmt, "headers": {}, "auth": [], "text": None, "html": None, "attachments": [],
            "warnings": [], "flags": [], "incomplete": []}


def _promote(a):
    """An attachment whose bytes are an Outlook message or TNEF is read as one, whatever its
    name or MIME type says (a .msg sent as application/octet-stream, a renamed winmail.dat).
    A Compound File counts as a .msg only if it has the MS-OXMSG property stream, so Word and
    Excel 97-2003 files stay ordinary files."""
    if a["kind"] != "file" or not a["data"]:
        return
    d = a["data"]
    claims_msg = (a.get("name") or "").lower().rstrip(". ").endswith((".msg", ".oft")) or \
        (a.get("content_type") or "").lower() == "application/vnd.ms-outlook"
    ok = msgcfb.is_msg(d) if d[:8] == msgcfb.SIG else False
    if ok or (ok is None and claims_msg):
        # a damaged Compound File that claims to be a message is read as one: the nested read then
        # fails and the parse is reported incomplete instead of the attachment passing as a file
        a["kind"] = "msg"
    elif ok is None:
        a["damaged_cfb"] = True  # a damaged .doc/.xls (or unnamed) Compound File: not called a message
    elif len(d) >= 4 and int.from_bytes(d[:4], "little") == tnef.SIG:
        a["kind"] = "tnef"
    elif (a.get("name") or "").lower().rstrip(". ").endswith(".msg") or \
            (a.get("content_type") or "").lower() == "application/vnd.ms-outlook":
        a["unreadable_msg"] = True  # says it is an Outlook message, but the bytes are not one


def att_reasons(a):
    """Extra reasons from what parsing found: a container whose contents could not be read, or a
    damaged Compound File. Both are held back by extract unless --include-risky."""
    out = []
    if a["kind"] in ("msg", "tnef") and a.get("data") and not a.get("nested"):
        out.append("unreadable-container")
    if a.get("damaged_cfb") or a.get("unreadable_msg"):
        out.append("damaged-compound-file" if a.get("damaged_cfb") else "unreadable-container")
    return out


def _add_att(m, a):
    _promote(a)
    _count["n"] += 1
    if _count["n"] > LIMITS["max_attachments"]:
        raise LimitError("over %d attachments in total, nested ones included (--max-attachments)"
                         % LIMITS["max_attachments"])
    m["attachments"].append(a)


def sniff(data):
    if data[:8] == msgcfb.SIG:
        return "msg"
    if len(data) >= 4 and int.from_bytes(data[:4], "little") == tnef.SIG:
        return "tnef"
    head = data[:4096].lstrip()
    if re.match(rb"(?i)^(from |[!-9;-~]+:)", head):
        return "eml"
    return None


def _addr_list(values):
    out = []
    for name, addr in email.utils.getaddresses([v for v in values if v]):
        if name or addr:
            out.append({"name": mailsafe.clean_text(name, 200), "address": mailsafe.clean_text(addr, 320)})
    return out


def parse_auth(values):
    """Results from Authentication-Results headers. Only the topmost header added by the
    recipient's own server is meaningful; anything lower may be written by the sender."""
    res = []
    for v in values:
        v = str(v)
        item = {"authserv_id": mailsafe.clean_text(v.split(";", 1)[0].strip(), 200)}
        for k in ("spf", "dkim", "dmarc", "arc", "compauth"):
            m = re.search(r"(?i)\b%s=([a-z]+)" % k, v)
            if m:
                item[k] = m.group(1).lower()
        res.append(item)
    return res


def _hdr_model(get_all):
    h = {}
    for key in ("subject", "date", "message-id", "x-mailer", "user-agent"):
        v = get_all(key)
        h[key.replace("-", "_")] = mailsafe.clean_text(str(v[0]), 1000) if v else None
    for key in ("from", "sender", "reply-to", "to", "cc", "bcc", "return-path"):
        h[key.replace("-", "_")] = _addr_list([str(x) for x in (get_all(key) or [])])
    h["received_count"] = len(get_all("received") or [])
    h["list_unsubscribe"] = bool(get_all("list-unsubscribe"))
    return h


def _decode_text(part):
    try:
        return part.get_content()
    except (LookupError, ValueError, AssertionError):
        raw = part.get_payload(decode=True) or b""
        return raw.decode("utf-8", "replace")


def _leaves(msg, lost, depth=0):
    """Leaf parts in order, without descending into attached messages (message/rfc822),
    which are parsed separately as nested messages. Parts below MAX_MIME_DEPTH are not read and
    are recorded in lost, so the caller can mark the parse incomplete."""
    if msg.is_multipart() and msg.get_content_type() != "message/rfc822":
        if depth >= MAX_MIME_DEPTH:
            lost.append("MIME parts nested over %d levels were not read" % MAX_MIME_DEPTH)
            return
        for p in msg.get_payload():
            yield from _leaves(p, lost, depth + 1)
    else:
        yield msg


MAX_BOUNDARIES = 2000


def from_eml(data, depth=0):
    # The stdlib parser builds the whole tree first. Refuse absurd multipart nesting up front so it
    # cannot exhaust memory or the recursion limit (each nested multipart declares a boundary).
    # RFC 2231 forms count too: boundary*=, boundary*0=, boundary*0*=
    nb = len(re.findall(rb"(?i)boundary(?:\*\d*\*?)?\s*=", data))
    if nb > MAX_BOUNDARIES:
        raise LimitError("%d MIME boundaries declared, over the %d cap" % (nb, MAX_BOUNDARIES))
    # Every MIME part starts at a "--boundary" line, so this bounds the part count cheaply,
    # before the stdlib spends seconds building a tree of 100,000 parts.
    cap = 2 * LIMITS["max_attachments"] + 2 * MAX_BOUNDARIES
    nd = len(re.findall(rb"(?m)^--[!-~]", data))
    if nd > cap:
        raise LimitError("%d MIME delimiter lines, over the %d cap for --max-attachments %d"
                         % (nd, cap, LIMITS["max_attachments"]))
    msg = email.message_from_bytes(data, policy=email.policy.default)
    m = _new("eml")
    m["headers"] = _hdr_model(msg.get_all)
    m["auth"] = parse_auth(msg.get_all("authentication-results") or [])
    ct = msg.get_content_type()
    if ct in ("application/pkcs7-mime", "application/x-pkcs7-mime") or ct == "multipart/encrypted":
        m["flags"].append("encrypted")
    if ct == "multipart/signed":
        m["flags"].append("signed")
    if msg.defects:
        m["warnings"].extend("MIME defect: %s" % type(d).__name__ for d in msg.defects[:20])
    lost = []
    for part in _leaves(msg, lost):
        pct = part.get_content_type()
        disp = part.get_content_disposition()
        fname = part.get_filename()
        if pct == "text/plain" and disp != "attachment" and not fname and m["text"] is None:
            m["text"] = _decode_text(part)
            continue
        if pct == "text/html" and disp != "attachment" and not fname and m["html"] is None:
            m["html"] = _decode_text(part)
            continue
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if pct == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            payload = inner.as_bytes() if hasattr(inner, "as_bytes") else (payload or b"")
        a = {"name": fname, "content_type": pct, "data": payload or b"", "inline": disp == "inline",
             "content_id": mailsafe.clean_text(part.get("content-id"), 200), "kind": "file", "nested": None}
        if pct == "message/rfc822":
            a["kind"] = "embedded-message"
            a["name"] = fname or "attached-message.eml"
        elif pct == "application/ms-tnef" or (fname or "").lower() == "winmail.dat":
            a["kind"] = "tnef"
        elif pct == "text/calendar":
            a["kind"] = "calendar"
        _add_att(m, a)
    for x in lost[:1]:
        m["incomplete"].append(x)
    _nest(m, depth)
    return m


def _nest(m, depth):
    for i, a in enumerate(m["attachments"], 1):
        if a.get("damaged_cfb"):
            m["incomplete"].append("attachment %d: Compound File (Office 97-2003 or similar) could not be read" % i)
        if a.get("unreadable_msg") and a["kind"] == "file":
            m["incomplete"].append("attachment %d: looks like an Outlook message but could not be read" % i)
        if a["kind"] in ("embedded-message", "tnef", "msg") and a["data"]:
            if depth + 1 > MAX_DEPTH:
                m["incomplete"].append("attachment %d: nested message not read (depth over %d)" % (i, MAX_DEPTH))
                continue
            try:
                a["nested"] = parse_bytes(a["data"], depth + 1)
            except (MailError, msgcfb.CfbError, tnef.TnefError, rtfbody.RtfError,
                    struct.error, IndexError, ValueError, RecursionError) as e:
                m["incomplete"].append("attachment %d: nested %s not read: %s" % (i, a["kind"], e))
    _bubble(m)


def _bubble(m):
    """Copy nested incomplete notes and warnings up, prefixed with the attachment index."""
    for i, a in enumerate(m["attachments"], 1):
        n = a.get("nested")
        if not n:
            continue
        m["incomplete"].extend("attachment %d/%s" % (i, x[len("attachment "):]) if x.startswith("attachment ")
                               else "attachment %d: %s" % (i, x) for x in n["incomplete"])
        m["warnings"].extend("attachment %d: %s" % (i, x) for x in n["warnings"][:20])


def _rtf_body(m, raw):
    """Fill text or html from a compressed RTF body when nothing better is stored."""
    if not isinstance(raw, bytes) or m["html"] or m["text"]:
        return
    if not raw:  # Outlook sometimes writes an empty RTF stream beside a plain body: no body, not damage
        return
    try:
        rtf, w, damaged = rtfbody.decompress(raw)
        b = rtfbody.to_body(rtf)
    except rtfbody.RtfError as e:
        m["incomplete"].append("RTF body not decoded: %s" % e)
        return
    m["warnings"].extend(w + b["warnings"])
    m["incomplete"].extend("RTF body: %s" % x for x in damaged + b["truncated"])
    if b["kind"] == "html":
        m["html"] = b["content"]
    else:
        m["text"] = b["content"]
    m["flags"].append("body-from-rtf")


def from_tnef(data, depth=0):
    r = tnef.parse(data, max_attachments=LIMITS["max_attachments"])
    mm = r["message"]
    m = _new("tnef")
    m["headers"] = {"subject": mailsafe.clean_text(mm.get("subject"), 1000), "message_class": mm.get("message_class")}
    m["text"] = mm.get("body") if isinstance(mm.get("body"), str) else None
    m["warnings"] = list(r["warnings"])
    m["incomplete"] = list(r["incomplete"])
    h = mm.get("body_html")
    if isinstance(h, bytes):
        m["html"] = h.decode("utf-8", "replace")
    elif isinstance(h, str):
        m["html"] = h
    _rtf_body(m, mm.get("rtf_compressed"))
    for a in r["attachments"]:
        kind = "file"
        if a.get("embedded_tnef"):
            kind = "tnef"
        elif a.get("object_iid"):
            kind = "ole-object"
        _add_att(m, {"name": a["filename"], "content_type": a.get("mime"), "data": a["data"] or b"",
                     "inline": False, "content_id": None, "kind": kind, "nested": None})
    _nest(m, depth)
    return m


def _s(v):
    return v if isinstance(v, str) else None


def _msg_model(props, recips, atts, depth):
    P = msgcfb.NAMES
    g = lambda pid: props.get(pid)
    m = _new("msg")
    m["text"] = _s(g(0x1000))
    hdrs = _s(g(0x007D))
    if hdrs:
        hm = email.message_from_string(hdrs + "\n\n", policy=email.policy.default)
        m["headers"] = _hdr_model(hm.get_all)
        m["auth"] = parse_auth(hm.get_all("authentication-results") or [])
    h = m["headers"]
    h["subject"] = mailsafe.clean_text(_s(g(0x0037)), 1000) or h.get("subject")
    h["message_class"] = _s(g(0x001A))
    if not h.get("from"):
        addr = _s(g(0x5D01)) or _s(g(0x0C1F))
        h["from"] = [{"name": mailsafe.clean_text(_s(g(0x0C1A)), 200), "address": mailsafe.clean_text(addr, 320)}] if (addr or g(0x0C1A)) else []
    h["sent_representing"] = mailsafe.clean_text(_s(g(0x0042)), 200)
    h["client_submit_time"] = g(0x0039)
    h["message_id"] = h.get("message_id") or mailsafe.clean_text(_s(g(0x1035)), 300)
    kinds = {1: "to", 2: "cc", 3: "bcc"}
    if recips:
        for k in kinds.values():
            h[k] = []
        for r in recips:
            k = kinds.get(r.get(0x0C15), "to")
            h[k].append({"name": mailsafe.clean_text(_s(r.get(0x3001)), 200),
                         "address": mailsafe.clean_text(_s(r.get(0x39FE)) or _s(r.get(0x3003)), 320)})
    html = g(0x1013)
    if isinstance(html, bytes):
        cp = props.get(0x3FDE)
        enc = {65001: "utf-8", 1252: "cp1252", 28591: "latin-1", 20127: "ascii"}.get(cp, "utf-8")
        m["html"] = html.decode(enc, "replace")
    elif isinstance(html, str):
        m["html"] = html
    _rtf_body(m, g(0x1009))
    if (h["message_class"] or "").upper().startswith("IPM.NOTE.SMIME"):
        m["flags"].append("smime")
    for a in atts:
        method = a.get(0x3705)
        name = _s(a.get(0x3707)) or _s(a.get(0x3704)) or _s(a.get(0x3001))
        item = {"name": name, "content_type": _s(a.get(0x370E)), "data": b"", "inline": bool(a.get(0x7FFE)),
                "content_id": mailsafe.clean_text(_s(a.get(0x3712)), 200), "kind": "file", "nested": None}
        d = a.get(0x3701)
        if isinstance(d, dict) and "embedded" in d:
            item["kind"] = "embedded-message"
            item["name"] = item["name"] or "attached-message.msg"
            if isinstance(d["embedded"], tuple):
                if depth + 1 > MAX_DEPTH:
                    m["incomplete"].append("attachment %d: nested message not read (depth over %d)"
                                           % (len(m["attachments"]) + 1, MAX_DEPTH))
                else:
                    item["nested"] = _msg_model(*d["embedded"], depth + 1)
            else:
                m["incomplete"].append("attachment %d: %s" % (len(m["attachments"]) + 1, d["embedded"]))
        elif isinstance(d, bytes):
            item["data"] = d
        elif method == 6:
            item["kind"] = "ole-object"
            m["warnings"].append("OLE attachment %r not decoded" % (name,))
        elif method in (2, 3, 4, 7):
            item["kind"] = "reference"
            m["warnings"].append("attachment %r is a link or reference, not stored in the file" % (name,))
        if (name or "").lower() == "winmail.dat" or item["content_type"] == "application/ms-tnef":
            item["kind"] = "tnef"
        _add_att(m, item)
    _nest(m, depth)
    return m


def from_msg(data, depth=0):
    props, recips, atts = msgcfb.open_msg(data)
    return _msg_model(props, recips, atts, depth)


def parse_bytes(data, depth=0):
    if depth == 0:
        _count["n"] = 0
    kind = sniff(data)
    if kind == "msg":
        return from_msg(data, depth)
    if kind == "tnef":
        return from_tnef(data, depth)
    if kind == "eml":
        return from_eml(data, depth)
    raise MailError("not an .eml, .msg or TNEF file")


# ---- HTML findings ----
class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.stack, self.f = [], [], {"scripts": 0, "forms": 0, "form_targets": [], "remote_images": 0,
                                                  "tracking_pixels": 0, "iframes": 0, "meta_refresh": 0,
                                                  "base_tag": 0, "hidden_blocks": 0, "event_handlers": 0}
        self.cur = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if any(k.startswith("on") for k in a):
            self.f["event_handlers"] += 1
        style = a.get("style", "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style or "font-size:0" in style:
            self.f["hidden_blocks"] += 1
        if tag == "a" and self.cur is not None:
            self.links.append(self.cur)  # an unclosed <a> before a new one is still a link
            self.cur = None
        if tag == "a" and "href" in a:
            self.cur = {"href": a["href"], "text": ""}
        elif tag == "area" and "href" in a:
            self.links.append({"href": a["href"], "text": a.get("alt", "")})
        elif tag == "script":
            self.f["scripts"] += 1
        elif tag == "form":
            self.f["forms"] += 1
            self.f["form_targets"].append(a.get("action", ""))
        elif tag in ("iframe", "frame", "object", "embed"):
            self.f["iframes"] += 1
        elif tag == "base":
            self.f["base_tag"] += 1
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            self.f["meta_refresh"] += 1
        elif tag == "img":
            src = a.get("src", "")
            if re.match(r"(?i)^(https?:)?//", src):
                self.f["remote_images"] += 1
                if a.get("width") in ("0", "1") or a.get("height") in ("0", "1"):
                    self.f["tracking_pixels"] += 1

    def handle_endtag(self, tag):
        if tag == "a" and self.cur is not None:
            self.links.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None and len(self.cur["text"]) < 500:
            self.cur["text"] += data


def html_scan(html):
    p = _Html()
    try:
        p.feed(html[:5_000_000])
        p.close()
    except Exception:  # html.parser is lenient; any surprise is reported, not raised
        p.f["parse_error"] = True
    if p.cur is not None:  # an <a href> never closed (end of input) is still a link
        p.links.append(p.cur)
        p.cur = None
    return p.links, p.f


def html_to_text(html):
    t = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    import html as _h
    t = _h.unescape(t)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


def sha256(b):
    return hashlib.sha256(b or b"").hexdigest()
