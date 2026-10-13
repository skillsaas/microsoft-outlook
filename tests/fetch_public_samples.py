#!/usr/bin/env python3
"""Fetch the public sample files used for the 0.1.4 real-file run, check their SHA-256, and save
them into a new folder for REAL_FIXTURES_DIR. Standard library only. Nothing runs on install;
this downloads only when you run it.

Usage: python tests/fetch_public_samples.py DEST
       REAL_FIXTURES_DIR=DEST python tests/smoke_test.py

The files are not shipped with the skill: they belong to other projects (MSGReader and ruby-msg,
MIT; msg-extractor, GPL-3.0) and are test fixtures from those projects, pinned to one commit each.
Their Outlook versions are unknown. Every file must match its pinned SHA-256 or it is discarded.
Exit codes: 0 all fetched and verified; 1 some failed (listed); 2 bad usage or DEST exists.
"""
import hashlib
import os
import sys
import urllib.parse
import urllib.request

REPOS = {
    "MSGReader": ("Sicos1977/MSGReader", "b9b04a7aef354c12872b48c29da87ba247f6b46b"),
    "msg-extractor": ("TeamMsgExtractor/msg-extractor", "18172ea4730fcfef6edaa0bd20e7a9c64bea20b9"),
    "ruby-msg": ("aquasync/ruby-msg", "a31ffaff0e0f4064e9c51bb5b6d9898671c31a5a"),
}
LICENSES = {"MSGReader": "MIT", "msg-extractor": "GPL-3.0", "ruby-msg": "MIT"}
FILES = [  # (saved name, project, path in the project, sha256)
    ("EmailWith2Attachments.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWith2Attachments.msg", "513a894a87de02ecbb312ada79ea19318378607bcb593ddb05ddecbade2d511f"),
    ("EmailWithAttachments.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithAttachments.msg", "59d2f6bd9287b77bc22402b302fd4aff547363545bbf744a10b106e36ca555f2"),
    ("EmailWithISO_8859_1_From.eml", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithISO_8859_1_From.eml", "5cfb430688c3e96591cde82dad3cc499c7d8f1ad9ca1852dd5dd6e213d1df7b1"),
    ("EmailWithInnerMailAndAttachments.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithInnerMailAndAttachments.msg", "217351a4f8860921d4b3b1e7badd2d7ad29b22eddb4bb2e236118230db286cc7"),
    ("EmailWithMsgAttachment.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithMsgAttachment.msg", "65dfb9f58cd55c4753d2690d18e4eaa34b8e36efb9fb8f578ec077c03707a329"),
    ("EmailWithMultilineSubject.eml", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithMultilineSubject.eml", "80902a9a45896b6aa3c7240931f3448d97512b6730c9cfbe97e8cb8b429d76e3"),
    ("EmailWithReactions.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithReactions.msg", "92d61b8207f415355fe1009411e4490bfa24f082eff4bfb58cc58e438131e0b8"),
    ("EmailWithSpecialCharsInSubject.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithSpecialCharsInSubject.msg", "b496e842665ff430f3b1d9674f4653919732047fd759b8a809e4f686b3b0795c"),
    ("EmailWithSpecialCharsInSubject_2.msg", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithSpecialCharsInSubject_2.msg", "d83b198269a322048c8695d699a60b81e1f8c1d8b2b38d47712390b3992b3671"),
    ("EmailWithUnknownContentDispositionParam.eml", "MSGReader", "MsgReaderTests/SampleFiles/EmailWithUnknownContentDispositionParam.eml", "3742e69df9175aee90e2f1e3e63e9898a066cf81d2b50d54dec45ca61c5656fd"),
    ("HtmlSampleEmail.msg", "MSGReader", "MsgReaderTests/SampleFiles/HtmlSampleEmail.msg", "e1e90f03ac3342522c1a61c36b082e27ffc4deb5ed492d1d214aeb3fed2c59f9"),
    ("HtmlSampleEmailWithAttachment.msg", "MSGReader", "MsgReaderTests/SampleFiles/HtmlSampleEmailWithAttachment.msg", "d00c73d8e550aded13e078bf35842a3e31e01894e16bdb49355b072db9293e51"),
    ("IssueSample.eml", "MSGReader", "MsgReaderTests/SampleFiles/IssueSample.eml", "2ea2c107c18ac93f4375fecc3a16fba482336ef2f471383305d4b0e068496dba"),
    ("RtfSampleEmail.msg", "MSGReader", "MsgReaderTests/SampleFiles/RtfSampleEmail.msg", "935c97bb657e395bd27cf20170a73b72b4795f967876f7221539b3c053f6f032"),
    ("RtfSampleEmailWithAttachment.msg", "MSGReader", "MsgReaderTests/SampleFiles/RtfSampleEmailWithAttachment.msg", "95c972bfff21e393889bf55c8eaad7c862553a577965c8f8b674b0fce5cef1d8"),
    ("RtfWithShortRussianString.msg", "MSGReader", "MsgReaderTests/SampleFiles/RtfWithShortRussianString.msg", "fcf8a775cc2d70a9d8e98f08b83bb698506d069512f1bd1cf0e45db36be51824"),
    ("TestWithAttachments.eml", "MSGReader", "MsgReaderTests/SampleFiles/TestWithAttachments.eml", "eb5445c17c9c8211b352b45958f144bd18978cb130a6a3670052d4e6044d6ee6"),
    ("TestWithAttachmentsAndInlines.eml", "MSGReader", "MsgReaderTests/SampleFiles/TestWithAttachmentsAndInlines.eml", "6f1744aeb73d7d019db5e9e971fa709d3519141a63dc03d170ee89b4ad370788"),
    ("TestWithInlineHavingContentDisposition.eml", "MSGReader", "MsgReaderTests/SampleFiles/TestWithInlineHavingContentDisposition.eml", "2c815266617495ff41ec7f9fed72e987dc8524a2a4d2dc40a2989009e202c794"),
    ("TestWithInlineHavingNoContentDisposition.eml", "MSGReader", "MsgReaderTests/SampleFiles/TestWithInlineHavingNoContentDisposition.eml", "3df4dd2b37a4b780bc44cfdfa277355e21290a9a8e12a455ed5f19241ce781fb"),
    ("TestWithInlineHavingWindows1252Fields.eml", "MSGReader", "MsgReaderTests/SampleFiles/TestWithInlineHavingWindows1252Fields.eml", "216189537a654462ab24aa37780ade27d859eb993a69699f80d524bfb9eb4282"),
    ("TxtSampleEmail.msg", "MSGReader", "MsgReaderTests/SampleFiles/TxtSampleEmail.msg", "13a5037e94a00bf78aa75532287a4e3f4b58230bae54c7f851010ab50a63e144"),
    ("TxtSampleEmailWithAttachment.msg", "MSGReader", "MsgReaderTests/SampleFiles/TxtSampleEmailWithAttachment.msg", "16c1d79495d1eb3be668a36fd59d4f6af32f04f2e9c3800f8b26cdb09e0708ed"),
    ("UTF-8_Test.eml", "MSGReader", "MsgReaderTests/SampleFiles/UTF-8_Test.eml", "a8aca31e8fd952b1b36699b04e1a3d58e5decae1c9d8233fa7982dfdf8e8c424"),
    ("multi-to-to.msg", "msg-extractor", "example-msg-files/multi-to-to.msg", "3c36553ded2e59a5683b5172daebb0fadb5564a8af26a1f68f9b0f60da0794f9"),
    ("multi-to.msg", "msg-extractor", "example-msg-files/multi-to.msg", "3d5dd27a6705a0a5d3627d33f788e0b520d1d0c1ae0ad8f3a75044e734fabbe1"),
    ("rb-Swetlana Novikova.msg", "ruby-msg", "test/Swetlana Novikova.msg", "2e516c4c425aa1a08e78571a0401e3521403b3e16d78a8f5ffac35d556b0b46f"),
    ("rb-contact-plain.msg", "ruby-msg", "test/contact-plain.msg", "06fcfd00e92da93d2a0b2d6a419de4f6b00e150fc607b8081cd4355f0c694c86"),
    ("rb-contact-unicode.msg", "ruby-msg", "test/contact-unicode.msg", "6b6ac0c62c4019ee68d3adb627997f3b3cc20d21df3809d4a30a38ccb4cab8f8"),
    ("rb-note.msg", "ruby-msg", "test/note.msg", "5adb511618b5d53acc8f450b79ce2f29ba504875257ada81390632dabfd8c567"),
    ("rb-qwerty_1-orig.msg", "ruby-msg", "test/qwerty_1-orig.msg", "529efcef29dd7961746931af731eeed35a4b8b96e5e27040e24f788fe8dd596c"),
    ("rb-qwerty_2-with_custom_properties.msg", "ruby-msg", "test/qwerty_2-with_custom_properties.msg", "fb3350dfda464e643e8216e5aab87003b024279226806a3862a9826cccc53811"),
    ("rb-qwerty_3.msg", "ruby-msg", "test/qwerty_3.msg", "e53211eed6cf7514cc33c00732832e6e53bf16784a31e6f245a8d26211aa8f9e"),
    ("rb-test_Blammo.msg", "ruby-msg", "test/test_Blammo.msg", "8d198f50a5c0cc6e60f6146c26206019ae040f476ff1db4823af9bc4a2098566"),
    ("sender_not_found_from_exchange.msg", "MSGReader", "MsgReaderTests/SampleFiles/sender_not_found_from_exchange.msg", "fcd191e1d66cb9a108ca34140bf546218faa6fc80880d7455544ef934a655bc7"),
    ("strangeDate.msg", "msg-extractor", "example-msg-files/strangeDate.msg", "9676ca02b32c15bf47bcf4295131d807a2729c2d1cddc53c4d40b57aa6c6d32b"),
    ("unicode-header.msg", "msg-extractor", "example-msg-files/unicode-header.msg", "fe13d8dfba467cd1a6dbc538bef43fccc8ac3fcdcba46cfda1fc15b72fe18a7f"),
    ("unicode.msg", "msg-extractor", "example-msg-files/unicode.msg", "3c67dc70854b994e469fc14496d23bf778e718831806ebafc72436c840439f9c"),
]


def main(argv):
    if len(argv) != 2 or argv[1].startswith("-"):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    dest = argv[1]
    if os.path.lexists(dest):
        print("DEST exists: choose a new folder", file=sys.stderr)
        return 2
    os.makedirs(dest, mode=0o700)
    bad = []
    for name, proj, path, want in FILES:
        repo, sha = REPOS[proj]
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, urllib.parse.quote(path))
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read(20 * 1024 * 1024)
        except OSError as e:
            bad.append("%s: %s" % (name, e))
            continue
        if hashlib.sha256(data).hexdigest() != want:
            bad.append("%s: SHA-256 mismatch, discarded" % name)
            continue
        with open(os.path.join(dest, name), "wb") as f:
            f.write(data)
    print("%d of %d files saved in %s" % (len(FILES) - len(bad), len(FILES), dest))
    for b in bad:
        print("  failed: " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
