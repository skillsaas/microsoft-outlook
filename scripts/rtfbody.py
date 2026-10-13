"""Compressed RTF bodies of Outlook items, read without rendering anything.

decompress(): MS-OXRTFCP "Rich Text Format (RTF) Compression Algorithm" (LZFu and the
uncompressed MELA form), with the CRC check from that spec. to_body(): pulls HTML back out of
RTF that encapsulates HTML (MS-OXRTFEX, \\fromhtml1) or plain text out of ordinary RTF.
Standard library only. Embedded objects and pictures in the RTF are skipped, never decoded.
"""
import re
import struct

LZFU, MELA = 0x75465A4C, 0x414C454D
_PREBUF = (b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss \\fmodern "
           b"\\fscript \\fdecor MS Sans SerifSymbolArialTimes New RomanCourier{\\colortbl\\red0\\green0"
           b"\\blue0\r\n\\par \\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx")
assert len(_PREBUF) == 207


class RtfError(Exception):
    pass


def _crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC = _crc_table()


def crc32(data):
    """MS-OXRTFCP CRC: the CRC-32 table, starting value 0, no final inversion."""
    c = 0
    for b in data:
        c = _CRC[(c ^ b) & 0xFF] ^ (c >> 8)
    return c


def decompress(data, max_out=32 * 1024 * 1024):
    """Return (rtf_bytes, warnings). Raises RtfError on a malformed header or stream."""
    if len(data) < 16:
        raise RtfError("compressed RTF shorter than its 16-byte header")
    comp_size, raw_size, ctype, crc = struct.unpack_from("<IIII", data, 0)
    warnings = []
    if raw_size > max_out:
        raise RtfError("declared RTF size %d is over the %d byte cap" % (raw_size, max_out))
    body = data[16:4 + comp_size] if comp_size >= 12 else b""
    if comp_size + 4 != len(data):
        warnings.append("compressed RTF size field %d does not match the stream (%d bytes)" % (comp_size, len(data) - 4))
    if ctype == MELA:
        return data[16:16 + raw_size], warnings
    if ctype != LZFU:
        raise RtfError("unknown compressed RTF type 0x%08x" % ctype)
    if crc32(body) != crc:
        warnings.append("compressed RTF CRC mismatch")
    d = bytearray(4096)
    d[:207] = _PREBUF
    w = 207
    out = bytearray()
    i, n, done = 0, len(body), False
    while i < n and not done:
        ctrl = body[i]
        i += 1
        for bit in range(8):
            if i >= n:
                break
            if ctrl & (1 << bit):
                if i + 2 > n:
                    raise RtfError("compressed RTF ends inside a reference")
                ref = (body[i] << 8) | body[i + 1]
                i += 2
                off, ln = ref >> 4, (ref & 0xF) + 2
                if off == w:
                    done = True
                    break
                for k in range(ln):
                    c = d[(off + k) & 0xFFF]
                    out.append(c)
                    d[w] = c
                    w = (w + 1) & 0xFFF
            else:
                c = body[i]
                i += 1
                out.append(c)
                d[w] = c
                w = (w + 1) & 0xFFF
            if len(out) > max_out:
                raise RtfError("decompressed RTF over the %d byte cap" % max_out)
    if not done:
        warnings.append("compressed RTF has no end marker (truncated?)")
    if len(out) < raw_size:
        warnings.append("decompressed RTF is %d bytes, header says %d" % (len(out), raw_size))
    return bytes(out[:raw_size]) if raw_size else bytes(out), warnings


_TOKEN = re.compile(rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([\r\n]+)|([^\\{}\r\n]+)", re.S)
_SKIP_DEST = {b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"header", b"footer",
              b"listtable", b"listoverridetable", b"revtbl", b"rsidtbl", b"generator", b"xmlnstbl",
              b"themedata", b"colorschememapping", b"latentstyles", b"datastore", b"filetbl", b"mhtmltag"}


def to_body(rtf, max_out=10 * 1024 * 1024):
    """Return {"kind": "html" | "text", "content": str, "warnings": [...]}. HTML comes only from
    RTF marked \\fromhtml1 (MS-OXRTFEX); anything else is reduced to plain text."""
    if not rtf.lstrip().startswith(b"{\\rtf"):
        raise RtfError("not RTF")
    fromhtml = b"\\fromhtml1" in rtf[:2048]
    cp = "cp1252"
    m = re.search(rb"\\ansicpg(\d{3,5})", rtf[:4096])
    if m:
        cp = "cp%s" % m.group(1).decode()
        try:
            b"".decode(cp)
        except LookupError:
            cp = "cp1252"
    out, pend = [], bytearray()
    # state: skip (ignorable destination), sup (\htmlrtf suppression), tag (inside \*\htmltag), uc
    st = {"skip": False, "sup": False, "tag": False, "uc": 1, "star": False}
    stack, skipn, size, warnings = [], 0, 0, []

    def flush():
        if pend:
            out.append(pend.decode(cp, "replace"))
            pend.clear()

    def emit(s):
        nonlocal size
        flush()
        out.append(s)
        size += len(s)

    def visible():
        return not st["skip"] and (not fromhtml or st["tag"] or not st["sup"])

    first_in_group = False
    for mt in _TOKEN.finditer(rtf):
        word, num, hexb, sym, brace, nl, text = mt.groups()
        if size > max_out:
            warnings.append("RTF body over the output cap; rest not read")
            break
        if brace == b"{":
            stack.append(dict(st))
            st["star"] = False
            first_in_group = True
            if len(stack) > 200:
                warnings.append("RTF nesting over 200 levels; rest not read")
                break
            continue
        if brace == b"}":
            flush()
            if stack:
                st = stack.pop()
            first_in_group = False
            continue
        if nl:
            continue
        if skipn and (text or hexb or sym):
            if text:
                take = min(skipn, len(text))
                skipn -= take
                text = text[take:]
                if not text:
                    continue
            else:
                skipn -= 1
                continue
        if sym is not None:
            if sym == b"*":
                st["star"] = True
                continue
            if visible():
                if sym in (b"\\", b"{", b"}"):
                    pend.extend(sym)
                elif sym == b"~":
                    emit("\u00a0")
            continue
        if hexb is not None:
            if visible():
                pend.append(int(hexb, 16))
            continue
        if word is not None:
            first, first_in_group = first_in_group, False
            if word == b"htmltag" and st["star"]:
                st["tag"], st["skip"] = True, False
                continue
            if st["star"] and first and word != b"htmltag":
                st["skip"] = True
                continue
            if word in _SKIP_DEST:
                st["skip"] = True
                continue
            if word == b"htmlrtf":
                st["sup"] = num != b"0"
                continue
            if word == b"uc":
                st["uc"] = int(num or 1)
                continue
            if word == b"u" and num is not None:
                if visible():
                    v = int(num)
                    emit(chr(v + 65536 if v < 0 else v))
                skipn = st["uc"]
                continue
            if not visible():
                continue
            if word in (b"par", b"line"):
                emit("\r\n" if fromhtml else "\n")
            elif word == b"tab":
                emit("\t")
            elif word == b"emdash":
                emit("\u2014")
            elif word == b"endash":
                emit("\u2013")
            elif word in (b"lquote", b"rquote"):
                emit("'")
            elif word in (b"ldblquote", b"rdblquote"):
                emit('"')
            continue
        if text and visible():
            pend.extend(text)
            size += len(text)
    flush()
    return {"kind": "html" if fromhtml else "text", "content": "".join(out), "warnings": warnings}
