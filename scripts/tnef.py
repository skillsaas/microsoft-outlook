"""Decode TNEF (winmail.dat, application/ms-tnef), as specified in MS-OXTNEF. Standard library
only, read-only, bounded. Returns message attributes and attachments; never runs anything.

Checksums are verified and a mismatch is reported (not fatal: some senders write bad ones).
"""
import struct

SIG = 0x223E9F78
LVL_MESSAGE, LVL_ATTACHMENT = 1, 2
ATT = {  # attribute id (low 16 bits of the attribute) -> name
    0x9006: "tnef_version", 0x9007: "oem_codepage", 0x8008: "message_class", 0x8004: "subject",
    0x8000: "from", 0x8005: "date_sent", 0x8006: "date_received", 0x800C: "body",
    0x9003: "msg_props", 0x9002: "attach_rend_data", 0x8010: "attach_title",
    0x800F: "attach_data", 0x9005: "attachment", 0x8013: "attach_modify_date",
    0x8009: "message_id",
}


class TnefError(Exception):
    pass


def _mapi_props(b, max_props=5000):
    """Parse an attMAPIProps blob. Returns {prop_id: value} for string, binary and int types."""
    out = {}
    if len(b) < 4:
        return out
    count = struct.unpack_from("<I", b, 0)[0]
    if count > max_props:
        raise TnefError("too many MAPI properties")
    o = 4

    def need(n):
        if o + n > len(b):
            raise TnefError("truncated MAPI property block")

    for _ in range(count):
        need(4)
        ptype, pid = struct.unpack_from("<HH", b, o)
        o += 4
        if pid >= 0x8000:  # named property: GUID, kind, then id or name
            need(20)
            kind = struct.unpack_from("<I", b, o + 16)[0]
            o += 20
            if kind == 0:
                need(4)
                o += 4
            else:
                need(4)
                ln = struct.unpack_from("<I", b, o)[0]
                o += 4
                need(ln)
                o += (ln + 3) & ~3
        multi = bool(ptype & 0x1000)
        base = ptype & 0x0FFF
        n = 1
        if multi or base in (0x001E, 0x001F, 0x0102, 0x000D):
            need(4)
            n = struct.unpack_from("<I", b, o)[0]
            o += 4
            if n > 100000:
                raise TnefError("bad value count")
        vals = []
        for _ in range(n):
            if base in (0x001E, 0x001F, 0x0102, 0x000D):
                need(4)
                ln = struct.unpack_from("<I", b, o)[0]
                o += 4
                need(ln)
                raw = b[o:o + ln]
                o += (ln + 3) & ~3
                if base == 0x001F:
                    vals.append(raw.decode("utf-16-le", "replace").rstrip("\0"))
                elif base == 0x001E:
                    vals.append(raw.decode("cp1252", "replace").rstrip("\0"))
                else:
                    vals.append(raw)
            elif base in (0x0002, 0x0003, 0x000A, 0x000B, 0x0004):
                need(4)
                vals.append(struct.unpack_from("<I", b, o)[0])
                o += 4
            elif base in (0x0005, 0x0006, 0x0007, 0x0014, 0x0040):
                need(8)
                vals.append(struct.unpack_from("<Q", b, o)[0])
                o += 8
            elif base == 0x0048:  # GUID
                need(16)
                vals.append(b[o:o + 16])
                o += 16
            else:
                raise TnefError("unknown MAPI type 0x%04x" % base)
        if pid < 0x8000:
            if base == 0x000D:  # PtypObject: 16-byte interface id, then the object
                vals = [("object", v[:16], v[16:]) for v in vals]
            out[pid] = vals if multi else vals[0]
    return out


def parse(data, max_attachments=500, max_total=256 * 1024 * 1024):
    if len(data) < 6 or struct.unpack_from("<I", data, 0)[0] != SIG:
        raise TnefError("not TNEF (signature 0x223E9F78 missing)")
    o, msg, atts, warnings, cur, total = 6, {}, [], [], None, 0
    while o < len(data):
        if o + 9 > len(data):
            warnings.append("trailing bytes after the last attribute")
            break
        level = data[o]
        attr, ln = struct.unpack_from("<II", data, o + 1)
        o += 9
        if ln > len(data) - o:
            raise TnefError("attribute length runs past the end of the data")
        val = data[o:o + ln]
        o += ln
        if o + 2 <= len(data):
            cks = struct.unpack_from("<H", data, o)[0]
            if sum(val) & 0xFFFF != cks:
                warnings.append("checksum mismatch in attribute 0x%08x" % attr)
        else:
            warnings.append("data ends before the checksum of attribute 0x%08x (truncated)" % attr)
        o += 2
        name = ATT.get(attr & 0xFFFF, "0x%04x" % (attr & 0xFFFF))
        if level == LVL_ATTACHMENT:
            if name == "attach_rend_data" or cur is None:
                if len(atts) >= max_attachments:
                    raise TnefError("over %d attachments" % max_attachments)
                cur = {"name": None, "long_name": None, "data": None, "mime": None, "method": None,
                       "object_iid": None, "embedded_tnef": False}
                atts.append(cur)
            if name == "attach_title":
                cur["name"] = val.split(b"\0")[0].decode("cp1252", "replace")
            elif name == "attach_data":
                total += len(val)
                if total > max_total:
                    raise TnefError("attachments over the size cap")
                cur["data"] = val
            elif name == "attachment":
                try:
                    p = _mapi_props(val)
                except TnefError as e:
                    warnings.append("attachment properties: %s" % e)
                    p = {}
                if isinstance(p.get(0x3707), str):
                    cur["long_name"] = p[0x3707]
                if isinstance(p.get(0x370E), str):
                    cur["mime"] = p[0x370E]
                if isinstance(p.get(0x3705), int):
                    cur["method"] = p[0x3705]
                v = p.get(0x3701)
                if isinstance(v, list) and v:
                    v = v[0]
                if isinstance(v, tuple):  # embedded message or OLE object
                    cur["object_iid"] = v[1].hex()
                    cur["data"] = v[2]
                    cur["embedded_tnef"] = v[2][:4] == struct.pack("<I", SIG)
                    total += len(v[2])
                elif cur["data"] is None and isinstance(v, bytes):
                    cur["data"] = v
                    total += len(v)
                if total > max_total:
                    raise TnefError("attachments over the size cap")
        elif level == LVL_MESSAGE:
            if name in ("subject", "message_class", "message_id"):
                msg[name] = val.split(b"\0")[0].decode("cp1252", "replace")
            elif name == "body":
                msg["body"] = val.decode("cp1252", "replace")
            elif name == "msg_props":
                try:
                    p = _mapi_props(val)
                except TnefError as e:
                    warnings.append("message properties: %s" % e)
                    p = {}
                for pid, key in ((0x0037, "subject"), (0x1000, "body"), (0x1013, "body_html"),
                                 (0x1009, "rtf_compressed")):
                    if pid in p and key not in msg:
                        msg[key] = p[pid]
        else:
            warnings.append("unknown attribute level %d" % level)
    for a in atts:
        a["filename"] = a["long_name"] or a["name"]
    return {"message": msg, "attachments": atts, "warnings": warnings}
