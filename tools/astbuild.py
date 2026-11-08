#!/usr/bin/env python3
"""
astbuild.py - rebuild an EA BGFA1.05 (.AST) archive with resized entries.

build_patch.py (OfflineWarningMod) could only swap bytes inside an entry whose
compressed stream still fit the original slot.  This tool re-lays the archive
out so an entry may grow or shrink: it recompresses every replaced entry with
zlib level 9 (EA's own compressor - an untouched entry round-trips byte for
byte), packs the entries back in their original order at the original
alignment, and rewrites the three per-entry TOC fields.

TOC entry (lens from header bytes 33..37, e.g. [1,8,2,2,2] or [1,8,2,3,3]):
    flag u8 | id u64 | start (<< shift) | size = compressed bytes
          | extra = decompressed_size - compressed_size
The third field was thought to be a hash; it is not - in every archive checked
(30+ entries, both field widths) decompressed - compressed == extra exactly.
So a rebuilt archive only needs the true sizes; nothing is hashed.

Library:
    a = Archive.read(path)            # a.entries[i].dec = decompressed bytes
    a.entries[1].dec = new_bytes       # replace / grow
    a.write(out_path)                  # re-lays out, rewrites TOC, verifies
CLI:
    astbuild.py info   in.AST
    astbuild.py rebuild in.AST out.AST [--replace IDX=file.bin]... [--append-cstring IDX=text]...
        --append-cstring pads the entry to 8 bytes and appends text + NUL
        (the Apt Data C-string table layout); prints the string's offset.
"""
import struct, sys, zlib

ZLIB_MAGIC = (b"\x78\xda", b"\x78\x9c", b"\x78\x01", b"\x78\x5e")


class Entry:
    def __init__(self, idx, toc_pos, flag, eid, start, size, extra, raw):
        self.idx, self.toc_pos, self.flag, self.eid = idx, toc_pos, flag, eid
        self.start, self.size, self.extra, self.raw = start, size, extra, raw
        self.compressed = raw[:2] in ZLIB_MAGIC
        self.dec = zlib.decompress(raw) if self.compressed else raw
        self.orig_dec = self.dec

    def __repr__(self):
        return (f"Entry[{self.idx}] id={self.eid.hex()} flag={self.flag:04x} start={self.start} "
                f"size={self.size} extra={self.extra} dec={len(self.dec)} head={self.dec[:14]!r}")


class Archive:
    def __init__(self, data):
        d = data
        assert d[:8] == b"BGFA1.05", "not a BGFA1.05 archive"
        self.toc_off = struct.unpack_from("<i", d, 16)[0]
        self.toc_len = struct.unpack_from("<i", d, 24)[0]
        self.lens = [d[33 + i] for i in range(5)]           # flag, id, start, size, extra
        self.shift, self.add_off, self.desc_len = d[38], d[40] * 4, d[44]
        assert self.desc_len == 0, "entries with descriptions are not handled"
        self.entry_len = sum(self.lens) + 1
        self.toc_start = self.toc_off + self.add_off          # toc_len counts the add_off bytes too
        self.toc_end = self.toc_off + self.toc_len
        self.entries = []
        p = self.toc_start
        lf, li, ls, lz, lx = self.lens
        while p + self.entry_len <= self.toc_end:
            e = d[p:p + self.entry_len]
            flag = e[0]; q = 1                               # leading byte, then lens[0] 'unk' byte(s)
            unk = e[q:q + lf]; q += lf
            eid = e[q:q + li]; q += li
            start = int.from_bytes(e[q:q + ls], "little") << self.shift; q += ls
            size = int.from_bytes(e[q:q + lz], "little"); q += lz
            extra = int.from_bytes(e[q:q + lx], "little"); q += lx
            self.entries.append(Entry(len(self.entries), p, (flag << 8) | int.from_bytes(unk, 'little'), eid, start, size, extra, d[start:start + size]))
            p += self.entry_len
        self.first_data = min(e.start for e in self.entries)
        # header + TOC + whatever EA left in the alignment gap before the first entry
        # (node_fe/corenode has 4 non-zero bytes there; keep them verbatim)
        self.header = d[:self.first_data]
        # sanity: the fields mean what we think they mean
        for e in self.entries:
            assert len(e.dec) - e.size == e.extra, f"{e}: extra != dec-size (layout assumption broken)"
        self.orig_len = len(d)

    @classmethod
    def read(cls, path):
        return cls(open(path, "rb").read())

    def _pack(self, e):
        if not e.compressed:
            return e.dec
        c = zlib.compressobj(9, zlib.DEFLATED, 15, 8, zlib.Z_DEFAULT_STRATEGY)
        return c.compress(e.dec) + c.flush()

    def build(self):
        align = 1 << self.shift
        hdr = bytearray(self.header)
        out = bytearray(hdr)
        # keep the original on-disk order of the entries (TOC order != file order)
        order = sorted(self.entries, key=lambda e: e.start)
        pos = self.first_data
        assert pos >= len(hdr)
        lf, li, ls, lz, lx = self.lens
        for e in order:
            comp = self._pack(e)
            if len(out) < pos:
                out += b"\0" * (pos - len(out))
            out += comp
            size, extra = len(comp), len(e.dec) - len(comp)
            for name, val, width in (("start", pos >> self.shift, ls), ("size", size, lz), ("extra", extra, lx)):
                if val >= 1 << (8 * width):
                    raise OverflowError(f"{e}: {name}={val} does not fit in {width} byte(s); "
                                        "the TOC field widths in the header would have to change")
            q = e.toc_pos + 1 + lf + li
            hdr[q:q + ls] = (pos >> self.shift).to_bytes(ls, "little"); q += ls
            hdr[q:q + lz] = size.to_bytes(lz, "little"); q += lz
            hdr[q:q + lx] = extra.to_bytes(lx, "little")
            e.new_start, e.new_size, e.new_extra = pos, size, extra
            pos = (len(out) + align - 1) // align * align
        out[:len(hdr)] = hdr
        return bytes(out)

    def write(self, path, verbose=True):
        data = self.build()
        # verify: re-parse and compare every entry's decompressed bytes
        chk = Archive(data)
        assert len(chk.entries) == len(self.entries)
        for a, b in zip(self.entries, chk.entries):
            assert a.eid == b.eid and b.dec == a.dec, f"round-trip mismatch on {a}"
        open(path, "wb").write(data)
        if verbose:
            print(f"wrote {path}: {len(data)} bytes (was {self.orig_len})")
            for e in self.entries:
                ch = "" if (e.start, e.size, e.extra) == (e.new_start, e.new_size, e.new_extra) else "  <-- changed"
                print(f"  [{e.idx}] id={e.eid.hex()} start {e.start}->{e.new_start} size {e.size}->{e.new_size} "
                      f"extra {e.extra}->{e.new_extra} dec {len(e.orig_dec)}->{len(e.dec)}{ch}")
        return data


def append_cstring(entry, text):
    """Append text+NUL at the next 8-aligned offset of an Apt Data entry; returns the absolute offset."""
    d = entry.dec
    off = (len(d) + 7) // 8 * 8
    entry.dec = d + b"\0" * (off - len(d)) + text.encode("ascii") + b"\0"
    return off


def main(argv):
    if len(argv) >= 2 and argv[0] == "info":
        a = Archive.read(argv[1])
        print(f"{argv[1]}: {a.orig_len} bytes, lens={a.lens} shift={a.shift} toc@{a.toc_start}..{a.toc_end}")
        for e in a.entries:
            print(" ", e)
        return
    if len(argv) >= 3 and argv[0] == "rebuild":
        a = Archive.read(argv[1])
        i = 3
        while i < len(argv):
            opt, arg = argv[i], argv[i + 1]; i += 2
            idx, _, val = arg.partition("=")
            e = a.entries[int(idx)]
            if opt == "--replace":
                e.dec = open(val, "rb").read()
            elif opt == "--append-cstring":
                print(f"appended {val!r} to entry {idx} at offset {append_cstring(e, val)}")
            else:
                sys.exit(f"unknown option {opt}")
        a.write(argv[2])
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
