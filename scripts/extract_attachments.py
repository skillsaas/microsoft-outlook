#!/usr/bin/env python3
"""Save the attachments of an .eml, .msg or winmail.dat into a new folder, safely.
Never opens, previews or runs a saved file. Standard library only.

Usage: python extract_attachments.py FILE OUTDIR [--json] [--dry-run] [--include-risky]
                                     [--skip-inline] [--only 1,2/1] [--only-ext .pdf,.docx] [--max-file N] [--max-total N]
                                     [--max-attachments N] [--timeout S] [--allow-incomplete]

- OUTDIR must not exist. Files are written into a private temp folder beside it (mode 0700, files
  0600, no execute bit) and the folder is renamed into place only after every write succeeded.
- Names are reduced to a base name: no path separators, controls, bidi or zero-width characters,
  Windows device names or trailing dots; case-insensitive duplicates get " (2)", " (3)".
- High-risk types (Outlook's blocked list, double extensions, bidi tricks, OLE objects) are
  skipped. With --include-risky they are saved with ".quarantine" appended so a double click
  does not run them.
- --only-ext .pdf,.docx is an allowlist: other extensions are skipped ("extension not in --only-ext").
  It never overrides the high-risk skip.
- An attached message or winmail.dat is a container (risk at least medium) whether it is found by
  name or by its bytes; the container itself is not saved, its attachments are (like TNEF).
- Attachments of nested messages (attached .msg or .eml, winmail.dat) are saved too, numbered
  by path ("2/1" is attachment 1 of attachment 2).
- manifest.json (mode 0600) lists every attachment: index, original and saved name, size,
  SHA-256, risk.
- Incomplete-parse policy (same in every script): fails closed on a partial parse: if any part of the file could not be read (depth cap, a broken
  nested message, unreadable TNEF properties), nothing is written and the exit is 1 with
  status "incomplete". --allow-incomplete saves what was read and still reports what was not.

Exit codes (JSON "status" in quotes): 0 "ok" (all saved); 1 "risky-skipped" (saved, but some were skipped
as high risk: tell the user which) or "incomplete"; 2 "error" (not an email file or corrupt);
3 "refused" (OUTDIR exists, a symlink in the path, size, count or time caps).
"""
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
    only_ext = None
    if a.only_ext:
        only_ext = {x.strip().lower().lstrip(".") for x in a.only_ext.split(",") if x.strip()}
    for idx, att in walk(m):
        risk, reasons = mailsafe.attachment_risk(att["name"], att["content_type"])
        risk, reasons = mailsafe.kind_risk(att["kind"], risk, reasons + mailparse.att_reasons(att), att["data"], att["name"])
        it = {"index": idx, "name": mailsafe.clean_text(att["name"], 300), "kind": att["kind"],
              "size": len(att["data"] or b""), "sha256": mailparse.sha256(att["data"]) if att["data"] else None,
              "risk": risk, "reasons": reasons, "saved_as": None, "skipped": None}
        items.append(it)
        if only is not None and idx not in only:
            it["skipped"] = "not selected (--only)"
            continue
        # a container is exempt only when its contents were read (they are filtered one by one);
        # an unreadable container is filtered like any file, so it can never slip past the allowlist
        if only_ext is not None and not (att["kind"] in mailsafe.CONTAINER_KINDS and att.get("nested")) and \
                mailsafe.ext_of(att["name"] or "") not in only_ext:
            it["skipped"] = "extension not in --only-ext"
            continue
        if att["kind"] == "tnef" and att.get("nested"):
            it["skipped"] = "TNEF container: its contents are saved instead"
            continue
        if att["kind"] == "msg" and att.get("nested"):
            it["skipped"] = "Outlook message container (found by content): its attachments are saved instead"
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
        held = mailsafe.HOLD_BACK & set(reasons)
        if risk == "high" and not a.include_risky:
            it["skipped"] = "high risk: not saved (use --include-risky to save as .quarantine)"
            continue
        if held and not a.include_risky:
            it["skipped"] = "high risk: %s, not saved (use --include-risky to save as .quarantine)" % ", ".join(sorted(held))
            continue
        total += it["size"]
        if total > a.max_total:
            raise OverflowError("attachments total over --max-total (%d bytes)" % a.max_total)
        fallback = "attachment-%s" % idx.replace("/", "-")
        name = mailsafe.safe_filename(att["name"], fallback)
        if att["kind"] == "embedded-message" and not os.path.splitext(name)[1]:
            name += ".eml"
        if risk == "high" or held:
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
    # A symlinked parent is fine (macOS /tmp and many home folders are symlinks): resolve it once
    # and write under the real path. OUTDIR itself must not exist, so it cannot be a symlink.
    real = os.path.realpath(parent)
    return os.path.join(real, os.path.basename(out)), real


def main(argv=None):
    ap = mailsafe.ArgParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("outdir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-risky", action="store_true")
    ap.add_argument("--skip-inline", action="store_true")
    ap.add_argument("--only", help="comma-separated indexes, as listed by inspect_mail.py")
    ap.add_argument("--only-ext", help="allowlist: save only these extensions, e.g. .pdf,.docx (high risk is still skipped)")
    ap.add_argument("--max-file", type=int, default=100 * 1024 * 1024)
    ap.add_argument("--max-total", type=int, default=500 * 1024 * 1024)
    ap.add_argument("--max-bytes", type=int, default=150 * 1024 * 1024, help="input file cap")
    ap.add_argument("--max-attachments", type=int, default=500, help="refuse above this many, nested included")
    ap.add_argument("--timeout", type=float, default=120, help="wall-clock seconds, 0 for none")
    ap.add_argument("--allow-incomplete", action="store_true", help="save what was read from a partial parse")
    ap.add_argument("--version", action="version", version=mailsafe.VERSION)
    a = ap.parse_args(argv)
    mailsafe.watchdog(a.timeout, a.json)
    mailparse.LIMITS["max_attachments"] = a.max_attachments
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
    except mailparse.LimitError as e:
        return mailsafe.fail(a.json, 3, str(e))
    except (mailparse.MailError, msgcfb.CfbError, tnef.TnefError) as e:
        return mailsafe.fail(a.json, 2, str(e))
    except RecursionError:
        return mailsafe.fail(a.json, 3, "nesting too deep to read safely")
    except Exception as e:
        return mailsafe.fail(a.json, 2, "could not parse: %s" % type(e).__name__)
    inc = m.get("incomplete") or []
    if inc and not a.allow_incomplete:
        return mailsafe.fail(a.json, 1, "parse incomplete: nothing was saved", status="incomplete",
                             incomplete=inc[:50], hint="inspect_mail.py shows what was read; "
                             "--allow-incomplete saves it anyway")
    try:
        items = plan(m, a)
    except OverflowError as e:
        return mailsafe.fail(a.json, 3, str(e))
    saved = [i for i in items if i["saved_as"]]
    if not a.dry_run and saved:
        tmp = tempfile.mkdtemp(prefix=".extract-", dir=parent)

        def _cleanup(tmp=tmp):
            # runs from the --timeout watchdog: remove the hidden partial folder and say so
            shutil.rmtree(tmp, ignore_errors=True)
            return ("partial output folder %s removed" % os.path.basename(tmp)) if not os.path.exists(tmp) \
                else ("could not remove partial output folder %s: delete it by hand" % tmp)
        mailsafe.on_timeout(_cleanup)
        # Atomic commit: each write and the final rename run under the watchdog's lock, so a timeout
        # lands only between steps (cleanup removes the temp folder, nothing is left) or, after the
        # rename, is ignored and the full result is reported. Never "nothing completed" with files kept.
        try:
            for it in saved:
                with mailsafe.guarded():
                    fd = os.open(os.path.join(tmp, it["saved_as"]),
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(it["_data"])
            man = [{k: v for k, v in i.items() if k != "_data"} for i in items]
            with mailsafe.guarded():
                fd = os.open(os.path.join(tmp, "manifest.json"),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"source": os.path.basename(a.file), "complete": not inc, "incomplete": inc,
                               "attachments": man}, f, indent=2, ensure_ascii=False)
            with mailsafe.guarded():
                if os.path.lexists(out):
                    raise FileExistsError("OUTDIR appeared while writing")
                os.rename(tmp, out)
                mailsafe.committed()
                mailsafe.off_timeout(_cleanup)
        except Exception as e:
            mailsafe.off_timeout(_cleanup)
            shutil.rmtree(tmp, ignore_errors=True)
            return mailsafe.fail(a.json, 3, "write failed, nothing kept: %s" % e)
    for i in items:
        i.pop("_data", None)
    risky = [i for i in items if i["skipped"] and i["skipped"].startswith("high risk")]
    r = {"ok": True, "status": "risky-skipped" if risky else ("incomplete" if inc else "ok"), "error": None,
         "complete": not inc, "incomplete": inc[:50], "dry_run": a.dry_run, "outdir": None if a.dry_run or not saved else out,
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
    sys.exit(mailsafe.finish(main()))
