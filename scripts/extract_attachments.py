#!/usr/bin/env python3
"""Save the attachments of an .eml, .msg or winmail.dat into a new folder, safely.
Never opens, previews or runs a saved file. Standard library only.

Usage: python extract_attachments.py FILE OUTDIR [--json] [--dry-run] [--include-risky]
                                     [--skip-inline] [--only 1,2/1] [--max-file N] [--max-total N]

- OUTDIR must not exist. Files are written into a private temp folder beside it (mode 0700, files
  0600, no execute bit) and the folder is renamed into place only after every write succeeded.
- Names are reduced to a base name: no path separators, controls, bidi or zero-width characters,
  Windows device names or trailing dots; case-insensitive duplicates get " (2)", " (3)".
- High-risk types (Outlook's blocked list, double extensions, bidi tricks, OLE objects) are
  skipped. With --include-risky they are saved with ".quarantine" appended so a double click
  does not run them.
- Attachments of nested messages (attached .msg or .eml, winmail.dat) are saved too, numbered
  by path ("2/1" is attachment 1 of attachment 2).
- manifest.json lists every attachment: index, original and saved name, size, SHA-256, risk.

Exit codes: 0 all saved; 1 saved, but some were skipped as risky (tell the user which);
2 not an email file or corrupt; 3 refused (OUTDIR exists, a symlink in the path, size caps).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailsafe  # noqa: E402
import mailparse  # noqa: E402
import msgcfb  # noqa: E402
import tnef  # noqa: E402


def walk(m, prefix=""):
    for i, a in enumerate(m["attachments"], 1):
        idx = "%s%d" % (prefix, i)
        yield idx, a
        if a.get("nested"):
            yield from walk(a["nested"], idx + "/")


def plan(m, a):
    used, items, total = set(), [], 0
    only = set(a.only.split(",")) if a.only else None
    for idx, att in walk(m):
        risk, reasons = mailsafe.attachment_risk(att["name"], att["content_type"])
        if att["kind"] == "ole-object":
            risk, reasons = "high", reasons + ["ole-object"]
        it = {"index": idx, "name": mailsafe.clean_text(att["name"], 300), "kind": att["kind"],
              "size": len(att["data"] or b""), "sha256": mailparse.sha256(att["data"]) if att["data"] else None,
              "risk": risk, "reasons": reasons, "saved_as": None, "skipped": None}
        items.append(it)
        if only is not None and idx not in only:
            it["skipped"] = "not selected (--only)"
            continue
        if att["kind"] == "tnef" and att.get("nested"):
            it["skipped"] = "TNEF container: its contents are saved instead"
            continue
        if att["kind"] == "embedded-message" and not att["data"]:
            it["skipped"] = "embedded .msg storage: its attachments are saved instead"
            continue
        if att["kind"] == "reference" or not att["data"]:
            it["skipped"] = "no data stored in the file"
            continue
        if a.skip_inline and att["inline"]:
            it["skipped"] = "inline (--skip-inline)"
            continue
        if it["size"] > a.max_file:
            it["skipped"] = "over --max-file"
            continue
        if risk == "high" and not a.include_risky:
            it["skipped"] = "high risk: not saved (use --include-risky to save as .quarantine)"
            continue
        total += it["size"]
        if total > a.max_total:
            raise OverflowError("attachments total over --max-total (%d bytes)" % a.max_total)
        fallback = "attachment-%s" % idx.replace("/", "-")
        name = mailsafe.safe_filename(att["name"], fallback)
        if att["kind"] == "embedded-message" and not os.path.splitext(name)[1]:
            name += ".eml"
        if risk == "high":
            name += ".quarantine"
        stem, ext = os.path.splitext(name)
        n, cand = 1, name
        while cand.lower() in used:
            n += 1
            cand = "%s (%d)%s" % (stem, n, ext)
        used.add(cand.lower())
        it["saved_as"] = cand
        it["_data"] = att["data"]
    return items


def check_outdir(path):
    out = os.path.abspath(path)
    if os.path.lexists(out):
        raise FileExistsError("OUTDIR exists: %s (choose a new folder; nothing is overwritten)" % path)
    parent = os.path.dirname(out)
    if not os.path.isdir(parent):
        raise FileNotFoundError("parent folder does not exist: %s" % parent)
    if os.path.realpath(parent) != parent:
        raise PermissionError("the output path goes through a symlink; give a real path")
    return out, parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("outdir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-risky", action="store_true")
    ap.add_argument("--skip-inline", action="store_true")
    ap.add_argument("--only", help="comma-separated indexes, as listed by inspect_mail.py")
    ap.add_argument("--max-file", type=int, default=100 * 1024 * 1024)
    ap.add_argument("--max-total", type=int, default=500 * 1024 * 1024)
    ap.add_argument("--max-bytes", type=int, default=150 * 1024 * 1024, help="input file cap")
    a = ap.parse_args(argv)
    try:
        data = mailsafe.read_capped(a.file, a.max_bytes)
    except OverflowError as e:
        return mailsafe.fail(a.json, 3, str(e))
    except (OSError, ValueError) as e:
        return mailsafe.fail(a.json, 2, "cannot read: %s" % e)
    try:
        out, parent = check_outdir(a.outdir)
    except (FileExistsError, PermissionError) as e:
        return mailsafe.fail(a.json, 3, str(e))
    except FileNotFoundError as e:
        return mailsafe.fail(a.json, 2, str(e))
    try:
        m = mailparse.parse_bytes(data)
    except (mailparse.MailError, msgcfb.CfbError, tnef.TnefError) as e:
        return mailsafe.fail(a.json, 2, str(e))
    except Exception as e:
        return mailsafe.fail(a.json, 2, "could not parse: %s" % type(e).__name__)
    try:
        items = plan(m, a)
    except OverflowError as e:
        return mailsafe.fail(a.json, 3, str(e))
    saved = [i for i in items if i["saved_as"]]
    if not a.dry_run and saved:
        tmp = tempfile.mkdtemp(prefix=".extract-", dir=parent)
        try:
            for it in saved:
                fd = os.open(os.path.join(tmp, it["saved_as"]),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(it["_data"])
            man = [{k: v for k, v in i.items() if k != "_data"} for i in items]
            with open(os.path.join(tmp, "manifest.json"), "x", encoding="utf-8") as f:
                json.dump({"source": os.path.basename(a.file), "attachments": man}, f, indent=2, ensure_ascii=False)
            if os.path.lexists(out):
                raise FileExistsError("OUTDIR appeared while writing")
            os.rename(tmp, out)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            return mailsafe.fail(a.json, 3, "write failed, nothing kept: %s" % e)
    for i in items:
        i.pop("_data", None)
    risky = [i for i in items if i["skipped"] and i["skipped"].startswith("high risk")]
    r = {"ok": True, "error": None, "dry_run": a.dry_run, "outdir": None if a.dry_run or not saved else out,
         "saved": len(saved), "skipped_risky": len(risky), "attachments": items,
         "note": "Saved files were not opened. Scan them before anyone opens them."}

    def human(r):
        lines = ["%s %d attachment(s)%s" % ("would save" if r["dry_run"] else "saved", r["saved"],
                                            (" to " + r["outdir"]) if r["outdir"] else "")]
        for i in r["attachments"]:
            lines.append("  [%s] %s -> %s  risk=%s%s" % (i["index"], i["name"], i["saved_as"] or "-", i["risk"],
                                                     ("  skipped: " + i["skipped"]) if i["skipped"] else ""))
        return "\n".join(lines)
    mailsafe.emit(r, a.json, human)
    return 1 if risky else 0


if __name__ == "__main__":
    sys.exit(main())
