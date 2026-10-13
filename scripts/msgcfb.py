"""Read Outlook .msg files: a Compound File Binary (MS-CFB) container holding MAPI property
streams (MS-OXMSG). Standard library only, read-only, bounded.

Hardening: every sector chain is checked for loops and out-of-range sectors, the directory walk
keeps a visited set, stream sizes are capped, and nesting depth is capped. A malformed file raises
CfbError with a short reason; nothing in it is executed.
"""
import struct
import datetime

SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ENDOFCHAIN, FREESECT, FATSECT, DIFSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
MAX_ENTRIES = 50000


class CfbError(Exception):
    pass


class Cfb:
    def __init__(self, data, max_stream=64 * 1024 * 1024):
        if len(data) < 512 or data[:8] != SIG:
            raise CfbError("not a Compound File (no D0CF11E0 signature)")
        self.d = data
        self.max_stream = max_stream
        h = struct.unpack_from("<HHHHHH", data, 0x18)
        self.major, byteorder, shift, mshift = h[1], h[2], h[3], h[4]
        if byteorder != 0xFFFE or self.major not in (3, 4) or shift not in (9, 12) or mshift != 6:
            raise CfbError("unsupported CFB header (version %d, sector shift %d)" % (self.major, shift))
        self.ss = 1 << shift
        self.mss = 64
        (ndir, nfat, dir1, _tx, self.cutoff, mfat1, nmfat, difat1, ndifat) = struct.unpack_from("<IIIIIIIII", data, 0x28)
        if self.cutoff != 4096:
            raise CfbError("mini stream cutoff is not 4096")
        self.nsect = (len(data) - self.ss) // self.ss + 1
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        s, seen = difat1, set()
        while s not in (ENDOFCHAIN, FREESECT) and ndifat:
            if s in seen or s >= self.nsect:
                raise CfbError("bad DIFAT chain")
            seen.add(s)
            vals = struct.unpack_from("<%dI" % (self.ss // 4), self._sector(s))
            difat.extend(vals[:-1])
            s = vals[-1]
            if len(seen) > ndifat:
                raise CfbError("DIFAT longer than declared")
        fat_secs = [x for x in difat if x not in (FREESECT, ENDOFCHAIN)][:nfat]
        if len(fat_secs) != nfat:
            raise CfbError("FAT sector count mismatch")
        fat = []
        for fs in fat_secs:
            if fs >= self.nsect:
                raise CfbError("FAT sector out of range")
            fat.extend(struct.unpack_from("<%dI" % (self.ss // 4), self._sector(fs)))
        self.fat = fat
        self.dirdata = self._chain_bytes(dir1, None, self.fat, self._sector)
        n = len(self.dirdata) // 128
        if n > MAX_ENTRIES:
            raise CfbError("too many directory entries")
        self.entries = [self._entry(i) for i in range(n)]
        root = self.entries[0]
        if not root or root["type"] != 5:
            raise CfbError("first directory entry is not the root")
        self.minifat = []
        if nmfat and mfat1 not in (ENDOFCHAIN, FREESECT):
            raw = self._chain_bytes(mfat1, None, self.fat, self._sector)
            self.minifat = list(struct.unpack_from("<%dI" % (len(raw) // 4), raw))
        self.ministream = self._chain_bytes(root["start"], root["size"], self.fat, self._sector) if root["size"] else b""

    def _sector(self, n):
        off = (n + 1) * self.ss
        if off >= len(self.d):  # a short last sector is padded, a missing one is an error
            raise CfbError("sector %d beyond end of file" % n)
        return self.d[off:off + self.ss].ljust(self.ss, b"\0")

    def _mini(self, n):
        off = n * self.mss
        if off + self.mss > len(self.ministream):
            raise CfbError("mini sector %d beyond mini stream" % n)
        return self.ministream[off:off + self.mss]

    def _chain_bytes(self, start, size, table, getter):
        out, s, seen = [], start, set()
        limit = self.max_stream if size is None else size
        unit = self.ss if getter == self._sector else self.mss
        while s != ENDOFCHAIN:
            if s in seen:
                raise CfbError("sector chain loops")
            if s >= len(table) or s in (FREESECT, FATSECT, DIFSECT):
                raise CfbError("sector chain points outside the table")
            seen.add(s)
            out.append(getter(s))
            if len(out) * unit > limit + unit:
                if size is None:
                    raise CfbError("stream over the size cap")
                break
            s = table[s]
        b = b"".join(out)
        if size is not None:
            if len(b) < size:
                raise CfbError("stream shorter than its declared size")
            b = b[:size]
        return b

    def _entry(self, i):
        e = self.dirdata[i * 128:(i + 1) * 128]
        nlen, typ = struct.unpack_from("<HB", e, 64)
        if typ == 0:
            return None
        nlen = min(nlen, 64)
        name = e[:max(nlen - 2, 0)].decode("utf-16-le", "replace")
        left, right, child = struct.unpack_from("<III", e, 68)
        start, size = struct.unpack_from("<IQ", e, 116)
        if self.major == 3:
            size &= 0xFFFFFFFF
        return {"name": name, "type": typ, "left": left, "right": right, "child": child,
                "start": start, "size": size}

    def children(self, idx):
        """Child entries of a storage, by index, guarded against cycles."""
        out, stack, seen = [], [self.entries[idx]["child"]], set()
        while stack:
            c = stack.pop()
            if c == NOSTREAM:
                continue
            if c in seen or c >= len(self.entries) or self.entries[c] is None:
                raise CfbError("bad directory tree")
            seen.add(c)
            e = self.entries[c]
            out.append(c)
            stack.extend([e["left"], e["right"]])
        return sorted(out, key=lambda k: self.entries[k]["name"])

    def read(self, idx):
        e = self.entries[idx]
        if e["type"] != 2:
            raise CfbError("not a stream")
        if e["size"] > self.max_stream:
            raise CfbError("stream %r is %d bytes, over the cap" % (e["name"], e["size"]))
        if e["size"] == 0:
            return b""
        if e["size"] < self.cutoff:
            return self._chain_bytes(e["start"], e["size"], self.minifat, self._mini)
        return self._chain_bytes(e["start"], e["size"], self.fat, self._sector)


# ---- MS-OXMSG ----
PT_I2, PT_LONG, PT_BOOL, PT_I8, PT_SYSTIME = 0x0002, 0x0003, 0x000B, 0x0014, 0x0040
PT_STRING8, PT_UNICODE, PT_BINARY, PT_OBJECT = 0x001E, 0x001F, 0x0102, 0x000D
NAMES = {
    0x001A: "message_class", 0x0037: "subject", 0x0039: "client_submit_time", 0x0E06: "delivery_time",
    0x0042: "sent_representing_name", 0x0C1A: "sender_name", 0x0C1F: "sender_email",
    0x5D01: "sender_smtp", 0x0065: "sent_representing_email", 0x007D: "transport_headers",
    0x0E04: "display_to", 0x0E03: "display_cc", 0x0E02: "display_bcc", 0x1000: "body",
    0x1013: "body_html", 0x1009: "rtf_compressed", 0x1035: "internet_message_id",
    0x0E07: "message_flags", 0x0017: "importance", 0x0036: "sensitivity",
    0x3001: "display_name", 0x3003: "email_address", 0x39FE: "smtp_address", 0x0C15: "recipient_type",
    0x3701: "attach_data", 0x3704: "attach_filename", 0x3707: "attach_long_filename",
    0x370E: "attach_mime_tag", 0x3705: "attach_method", 0x3712: "attach_content_id",
    0x7FFE: "attachment_hidden", 0x0E20: "attach_size", 0x370B: "rendering_position",
    0x3716: "attach_content_disposition", 0x0E21: "attach_num",
}


def _filetime(v):
    if not v:
        return None
    try:
        return (datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
                + datetime.timedelta(microseconds=v // 10)).isoformat()
    except OverflowError:
        return None


def _fixed(raw, header_len):
    props = {}
    for off in range(header_len, len(raw) - 15, 16):
        tag, _flags = struct.unpack_from("<II", raw, off)
        pid, ptype = tag >> 16, tag & 0xFFFF
        val = raw[off + 8:off + 16]
        if ptype in (PT_LONG,):
            props[pid] = struct.unpack_from("<i", val)[0]
        elif ptype == PT_I2:
            props[pid] = struct.unpack_from("<h", val)[0]
        elif ptype == PT_BOOL:
            props[pid] = bool(val[0])
        elif ptype == PT_SYSTIME:
            props[pid] = _filetime(struct.unpack_from("<Q", val)[0])
        elif ptype == PT_I8:
            props[pid] = struct.unpack_from("<q", val)[0]
    return props


def read_props(cfb, idx, header_len, depth=0, max_depth=4):
    """Return (props by id, recipients, attachments) for one storage."""
    props, recips, atts = {}, [], []
    for c in cfb.children(idx):
        e = cfb.entries[c]
        n = e["name"]
        if n.startswith("__substg1.0_") and len(n) == 20:
            try:
                pid, ptype = int(n[12:16], 16), int(n[16:20], 16)
            except ValueError:
                continue
            if ptype == PT_OBJECT and e["type"] == 1:
                if depth >= max_depth:
                    props[pid] = {"embedded": "not read: nesting over %d" % max_depth}
                else:
                    sub = read_props(cfb, c, 24, depth + 1, max_depth)
                    props[pid] = {"embedded": sub}
                continue
            if e["type"] != 2:
                continue
            raw = cfb.read(c)
            if ptype == PT_UNICODE:
                props[pid] = raw.decode("utf-16-le", "replace").rstrip("\0")
            elif ptype == PT_STRING8:
                props[pid] = raw.decode("cp1252", "replace").rstrip("\0")
            elif ptype == PT_BINARY:
                props[pid] = raw
        elif n == "__properties_version1.0" and e["type"] == 2:
            for k, v in _fixed(cfb.read(c), header_len).items():
                props.setdefault(k, v)
        elif n.startswith("__recip_version1.0_#") and e["type"] == 1:
            recips.append(read_props(cfb, c, 8, depth, max_depth)[0])
        elif n.startswith("__attach_version1.0_#") and e["type"] == 1:
            atts.append(read_props(cfb, c, 8, depth, max_depth)[0])
    return props, recips, atts


def open_msg(data, max_stream=64 * 1024 * 1024):
    cfb = Cfb(data, max_stream)
    return read_props(cfb, 0, 32)
