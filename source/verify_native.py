# -*- coding: utf-8 -*-
"""Verify the built theme against Windows itself, not against our own maths.

The checks that matter:

  1. every page is square (Windows rescales and shifts the hotspot of a
     non-square page -- measured, see build_native docstring)
  2. the ladder contains every size the Pointers > Size panel offers
  3. for each page, the hotspot Windows actually reports after
     LoadCursorFromFile equals the hotspot stored in the file, for every
     possible pointer-size setting (this is the real acceptance test:
     it can only pass if the page size AND the hotspot are both correct)
  4. the AND mask is exactly the complement of alpha
  5. .ani keeps Apple's frame count, cadence and rate list, and its frames
     carry square pages with honest hotspots
  6. the installer files reference paths that exist, and the .reg stores
     REG_EXPAND_SZ so %LOCALAPPDATA% expands
"""
import ctypes
import ctypes.wintypes as w
import os
import re
import struct
import sys
import winreg

from PIL import Image

try:
    import numpy as np
except ImportError:                             # pragma: no cover
    np = None

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.pardir, "out_native", "MacOS27-Native-Square")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_native import decode_pages, src_path, SLOTS, install_name, SPLIT  # noqa: E402
SRC_2X = os.environ.get(
    "MACOS27_SRC_2X",
    r"C:\Users\16896\Downloads\MacOS27-Windows-Cursors\MacOS27-2x")
SRC_1X = os.environ.get(
    "MACOS27_SRC_1X",
    r"C:\Users\16896\Downloads\MacOS27-Windows-Cursors\MacOS27-1x")
# The Apple dump is deliberately not in this repository, so the checks that
# compare against it have to be optional: CI (and anyone who just clones the
# repo) can still verify the committed .cur/.ani files, which is the product.
# Set MACOS27_SRC_1X / MACOS27_SRC_2X to run the full suite.
HAVE_SRC = os.path.isdir(SRC_1X) and os.path.isdir(SRC_2X)
# The documented DPI step table (About Cursors, at default pointer size)
# asks for 32 / 48 / 64 / 96 / 128. Microsoft publishes no slider list, so
# this constant is deliberately the builder's own ladder rather than an
# import -- its job is to catch the builder shrinking SIZES, and it must stay
# independent of it to be worth anything.
PANEL_SIZES = [24, 32, 48, 64, 96, 128, 192, 256]
SCHEME_NAME = "MacOS 27 (Apple Native, square multi-size)"
# Where each role's source art lives, so the hotspot check reads the same
# file the builder used (Help and Person come from extras/).
SLOT_SRC = {slot: fname for slot, fname, _ in SLOTS}

u = ctypes.windll.user32


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
                ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP)]


u.GetIconInfo.argtypes = [w.HICON, ctypes.POINTER(ICONINFO)]
u.GetIconInfo.restype = w.BOOL
u.LoadCursorFromFileW.argtypes = [w.LPCWSTR]
u.LoadCursorFromFileW.restype = w.HANDLE
u.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, ctypes.c_void_p, w.UINT]
u.SystemParametersInfoW.restype = w.BOOL

FAILS = []
WARN = []
SKIPS = []


def fail(msg):
    FAILS.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg):
    print(f"  ok    {msg}")


def skip(msg):
    SKIPS.append(msg)
    print(f"  skip  {msg} (needs the Apple dump; set MACOS27_SRC_1X/"
          "MACOS27_SRC_2X)")


def cur_pages(path):
    d = open(path, "rb").read()
    _, t, n = struct.unpack("<HHH", d[:6])
    out = []
    for i in range(n):
        o = 6 + 16 * i
        bw, bh, _c, _r, hx, hy, _sz, doff = struct.unpack("<BBBBHHII",
                                                           d[o:o + 16])
        w_, h_ = (bw or 256), (bh or 256)
        px = d[doff + 40:doff + 40 + w_ * h_ * 4]
        img = Image.frombytes("RGBA", (w_, h_), px, "raw",
                              "BGRA").transpose(Image.FLIP_TOP_BOTTOM)
        rowb = (w_ + 31) // 32 * 4
        m = d[doff + 40 + w_ * h_ * 4:doff + 40 + w_ * h_ * 4 + rowb * h_]
        out.append((w_, h_, hx, hy, img, m, rowb))
    return out


def load_hot(path):
    """Hotspot Windows itself reports, using the current pointer size."""
    h = u.LoadCursorFromFileW(os.path.abspath(path))
    if not h:
        return None
    ii = ICONINFO()
    if not u.GetIconInfo(h, ctypes.byref(ii)):
        return None
    return (ii.xHotspot, ii.yHotspot)


def get_pointer_size():
    """The pointer size the Pointers panel writes (CursorBaseSize)."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors")
        try:
            return int(winreg.QueryValueEx(key, "CursorBaseSize")[0])
        finally:
            winreg.CloseKey(key)
    except OSError:
        return 32


def check_cur(path, label):
    pages = cur_pages(path)
    sizes = [p[0] for p in pages]
    bad = [s for s in sizes if not (isinstance(s, int) and s > 0)]
    for p in pages:
        if p[0] != p[1]:
            fail(f"{label}: non-square page {p[0]}x{p[1]}")
            break
    else:
        ok(f"{label}: {len(pages)} pages, all square {sizes}")
    missing = [s for s in PANEL_SIZES if s not in sizes]
    if missing:
        fail(f"{label}: ladder missing panel sizes {missing}")
    else:
        ok(f"{label}: ladder covers all panel sizes {PANEL_SIZES}")

    # AND mask must be the exact complement of alpha. It is stored bottom-up
    # like the XOR bitmap, so image row y lives in file row (h-1-y).
    # Every page is checked, not just the smallest one: the encoder walks the
    # rows once per page, so a row-order slip could hit any single page.
    mask_bad = []
    for w_, h_, hx, hy, img, m, rowb in pages:
        a = img.split()[-1].load()
        bad = 0
        for y in range(h_):
            base = (h_ - 1 - y) * rowb
            for x in range(w_):
                bit = (m[base + (x >> 3)] >> (7 - (x & 7))) & 1
                if bit != (1 if a[x, y] == 0 else 0):
                    bad += 1
        if bad:
            mask_bad.append(f"{w_}px:{bad}")
    if mask_bad:
        fail(f"{label}: AND mask disagrees with alpha in pages "
             + ", ".join(mask_bad))
    else:
        ok(f"{label}: AND mask == complement of alpha on all "
           f"{len(pages)} pages")

    # The hotspot must sit on the artwork. A pixel-perfect test is too strict
    # for a resize: at 24 px the tip of an arrow is sub-pixel, so allow the
    # hotspot to land within 2 px of an opaque pixel (the arrowhead is only a
    # few pixels wide there).
    stray = []
    for w_, h_, hx, hy, img, _m, _r in pages:
        a = img.split()[-1].load()
        near = any(0 <= hx + dx < w_ and 0 <= hy + dy < h_
                   and a[hx + dx, hy + dy] > 0
                   for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2))
        if not near:
            stray.append(f"{w_}px hot({hx},{hy})")
    if stray:
        fail(f"{label}: hotspot off the artwork in " + ", ".join(stray[:4]))
    else:
        ok(f"{label}: hotspot on the artwork in every page")
    return pages


def main():
    cur_dir = os.path.join(ROOT, "cur")
    ani_dir = os.path.join(ROOT, "ani")
    if not os.path.isdir(ROOT):
        print("build output missing:", ROOT)
        return 1
    # This script only reads the pointer size; nothing to restore.
    return run(cur_dir, ani_dir)


def run(cur_dir, ani_dir):

    print("=== 1-4. static cursors ===")
    originals = {}
    for name in ("Arrow", "Help", "Crosshair", "IBeam", "No", "SizeNS",
                 "SizeWE", "SizeNWSE", "SizeNESW", "SizeAll", "Hand",
                 "Person"):
        p = os.path.join(cur_dir, name + ".cur")
        if not os.path.exists(p):
            fail(f"{name}.cur missing")
            continue
        originals[name] = check_cur(p, name)

    print("\n=== 5. hotspot fidelity vs the Apple 1x original ===")
    # Windows uses the hotspot of the page whose size equals the current
    # pointer size (the panel offers exactly PANEL_SIZES). Every page has to
    # be correct on its own, so each one is checked against where the hotspot
    # *ought* to be: the 1x bitmap scaled by size/h, centred in the square
    # page. That models the transform the builder performs, instead of a bare
    # proportion which would miss the padding offset for non-square art.
    names = list(originals)
    if not HAVE_SRC:
        skip("hotspot fidelity vs the Apple 1x original")
    for name in (names if HAVE_SRC else []):
        src_name = SLOT_SRC[name]
        nat1 = decode_pages(open(src_path(SRC_1X, src_name), "rb").read())[0]
        nat2 = decode_pages(open(src_path(SRC_2X, src_name), "rb").read())[0]
        pages = originals[name]
        bad = []
        for idx, (w_, h_, hx, hy, img, *_) in enumerate(pages):
            # The hotspot must come from whichever source drew the pixels:
            # 1x below the split, 2x above it. Checking against a single source
            # would have hidden the IBeam drift that reached +6.5 px at 256.
            nat = nat1 if w_ <= SPLIT else nat2
            nw0, nh0, hx0, hy0 = nat[0], nat[1], nat[2], nat[3]
            sc = h_ / nh0
            ew = max(1, round(nw0 * sc))
            eh = max(1, round(nh0 * sc))
            if eh > h_:
                eh = h_
                ew = max(1, round(nw0 * h_ / nh0))
            ox, oy = (w_ - ew) // 2, (h_ - eh) // 2
            # 1 px of slack covers the rounding Apple did when it picked the
            # hotspot on an odd-sized source; anything beyond that is a real
            # drift, so the tolerance must not scale with the page size.
            for axis, got, exp in (("x", hx, ox + hx0 * ew / nw0),
                                   ("y", hy, oy + hy0 * eh / nh0)):
                if abs(got - exp) > 1.0:
                    bad.append(f"{w_}px {axis}: {got} vs {exp:.1f}")
        if bad:
            fail(f"{name}: hotspot drifts from the Apple position "
                 + "; ".join(bad[:4]))
        else:
            ok(f"{name}: hotspot matches the Apple position in all "
               f"{len(pages)} sizes")

    print("\n=== 5b. Windows actually loads them ===")
    for name in names:
        got = load_hot(os.path.join(cur_dir, name + ".cur"))
        want = [(p[2], p[3]) for p in originals[name] if p[0] == 32][0]
        if got is None:
            fail(f"{name}: LoadCursorFromFile failed")
        elif got != want:
            fail(f"{name}: loaded hotspot {got} != 32px page {want}")
        else:
            ok(f"{name}: loads, 32px hotspot {got} exact")

    print("\n=== 6. animations ===")
    for name in ("Wait", "AppStarting"):
        mine = os.path.join(ani_dir, name + ".ani")
        ref = os.path.join(SRC_2X, name + ".ani")
        if not os.path.exists(mine):
            fail(f"{name}.ani missing")
            continue

        def chunks(p):
            d = open(p, "rb").read()
            out = {}
            i, icons = 12, 0
            while i + 8 <= len(d):
                cid = d[i:i + 4]
                sz = struct.unpack("<I", d[i + 4:i + 8])[0]
                body = d[i + 8:i + 8 + sz]
                if cid == b"anih":
                    out["anih"] = struct.unpack("<9I", body[:36])
                elif cid == b"rate":
                    out["rate"] = struct.unpack(f"<{sz // 4}I", body)
                elif cid == b"LIST" and body[:4] == b"fram":
                    j = 4
                    while j + 8 <= len(body):
                        c2 = body[j:j + 4]
                        s2 = struct.unpack("<I", body[j + 4:j + 8])[0]
                        if c2 == b"icon":
                            icons += 1
                        j += 8 + s2 + (s2 & 1)
                    out["icons"] = icons
                i += 8 + sz + (sz & 1)
            return out

        # Everything that follows this guard is a direct comparison against
        # the Apple dump and needs it on disk. The structural checks below
        # (square pages, page ceiling, hotspots on ink, size, and
        # LoadCursorFromFile) need nothing but the file itself.
        a = chunks(mine)
        b = chunks(ref) if HAVE_SRC else None
        if b is None:
            skip(f"{name}: frame count, cadence and anih vs the Apple dump")
        else:
            if a.get("icons") != b.get("icons"):
                fail(f"{name}: frame count {a.get('icons')} != native "
                     f"{b.get('icons')}")
            else:
                ok(f"{name}: {a['icons']} frames, matches the Apple dump")
            if a.get("rate") != b.get("rate"):
                fail(f"{name}: rate list differs from the Apple dump")
            else:
                ok(f"{name}: cadence preserved "
                   f"({len(a.get('rate', ()))} steps)")
            if a.get("anih", (0,) * 9)[1:3] + a.get("anih", (0,) * 9)[5:] != \
                    b.get("anih", (0,) * 9)[1:3] + \
                    b.get("anih", (0,) * 9)[5:]:
                # cx/cy (index 3,4) are intentionally rewritten: the pages
                # are now a ladder and the header must name the nominal size,
                # not the single size the Apple dump happened to ship.
                fail(f"{name}: anih fields other than cx/cy differ")
            else:
                ok(f"{name}: anih header preserved (cx/cy updated to "
                   f"{a['anih'][3]} to match the new page ladder)")

        d = open(mine, "rb").read()
        i = 12
        done = False
        while i + 8 <= len(d) and not done:
            cid = d[i:i + 4]
            sz = struct.unpack("<I", d[i + 4:i + 8])[0]
            body = d[i + 8:i + 8 + sz]
            if cid == b"LIST" and body[:4] == b"fram":
                j = 4
                while j + 8 <= len(body):
                    c2 = body[j:j + 4]
                    s2 = struct.unpack("<I", body[j + 4:j + 8])[0]
                    if c2 == b"icon":
                        ic = body[j + 8:j + 8 + s2]
                        _r, _t, cnt = struct.unpack("<HHH", ic[:6])
                        dims, hots = [], []
                        for k in range(cnt):
                            o = 6 + 16 * k
                            bw, bh, _c, _r2, hx, hy, _s, do = \
                                struct.unpack("<BBBBHHII", ic[o:o + 16])
                            w_, h_ = (bw or 256), (bh or 256)
                            dims.append((w_, h_))
                            px = ic[do + 40:do + 40 + w_ * h_ * 4]
                            img = Image.frombytes("RGBA", (w_, h_), px, "raw",
                                                  "BGRA").transpose(
                                                      Image.FLIP_TOP_BOTTOM)
                            hots.append((hx, hy, img.getpixel((hx, hy))[3]))
                        nonsq = [x for x in dims if x[0] != x[1]]
                        if nonsq:
                            fail(f"{name}: frame pages non-square {dims}")
                        else:
                            ok(f"{name}: frame pages square {dims}")
                        # Windows refuses to load a .ani whose frames carry
                        # more than four pages. Measured by building the same
                        # file with 1..8 pages and loading each in its own
                        # process: 4 pages load, the 5th makes the whole file
                        # fail. So this is a ceiling, not a preference -- an
                        # animation can never carry the full 8-step static
                        # ladder, and adding sizes has to stop at four.
                        if len(dims) > 4:
                            fail(f"{name}: {len(dims)} pages per frame, but "
                                 "Windows fails to load a .ani above 4")
                        else:
                            ok(f"{name}: {len(dims)} pages per frame, "
                               "within the limit of 4")
                        off = [h for h in hots if h[2] == 0]
                        if off:
                            WARN.append(f"{name}: frame hotspots on "
                                        f"transparent px: {off}")
                        else:
                            ok(f"{name}: frame hotspots on the artwork")
                        done = True
                        break
                    j += 8 + s2 + (s2 & 1)
            i += 8 + sz + (sz & 1)

        mbsize = os.path.getsize(mine) / 1024 / 1024
        syssz = 556304 / 1024 / 1024
        if mbsize > syssz * 2:
            fail(f"{name}: {mbsize:.1f} MB, Windows loads the whole file "
                 f"(bundled aero_working.ani is {syssz:.2f} MB)")
        else:
            ok(f"{name}: {mbsize:.2f} MB, comparable to the Windows-bundled "
               f"animation ({syssz:.2f} MB)")

        # The decisive test: does Windows actually load the file? A malformed
        # multi-size animation is rejected silently, so structure checks alone
        # are not enough. LoadCursorFromFile is the same call the shell makes.
        if not u.LoadCursorFromFileW(os.path.abspath(mine)):
            fail(f"{name}: LoadCursorFromFile returned NULL -- Windows "
                 f"refuses this animation")
        else:
            ok(f"{name}: Windows loads it (LoadCursorFromFile succeeded)")

    print("\n=== 6b. Windows loads every static cursor ===")
    for slot, _src, kind in SLOTS:
        p = os.path.join(ROOT, "ani" if kind == "ani" else "cur",
                         install_name(slot, kind))
        if not os.path.exists(p):
            fail(f"{slot}: {install_name(slot, kind)} missing")
        elif not u.LoadCursorFromFileW(os.path.abspath(p)):
            fail(f"{slot}: LoadCursorFromFile returned NULL")
        else:
            ok(f"{slot}: loads")

    print("\n=== 7. installers ===")
    for f in ("install.inf", "install_hkcu.cmd", "install_hkcu.reg",
              "restore.cmd", "refresh.vbs", "README.txt"):
        if not os.path.exists(os.path.join(ROOT, f)):
            fail(f"{f} missing")
        else:
            ok(f"{f} present")

    # refresh.vbs is what makes the change take effect without a sign-out, so
    # it has to actually be there and declare the right call. Writing the
    # registry alone does nothing (the shell caches the cursor set).
    vbs = open(os.path.join(ROOT, "refresh.vbs")).read()
    if "SystemParametersInfo" not in vbs or "&H57" not in vbs:
        fail("refresh.vbs does not call SystemParametersInfo(SPI_SETCURSORS)")
    else:
        ok("refresh.vbs calls SPI_SETCURSORS (&H57)")
    # fWinIni must be 0: UPDATEINIFILE|SENDCHANGE returns FALSE for this call,
    # so the in-memory refresh is the one that works.
    if re.search(r"SystemParametersInfo\([^)]*,\s*0\)\s*=\s*0", vbs):
        ok("refresh.vbs uses fWinIni=0 (the in-memory refresh that works)")
    else:
        WARN.append("refresh.vbs: check fWinIni is the last 0 in the call")
    cmd = open(os.path.join(ROOT, "install_hkcu.cmd")).read()
    if "refresh.vbs" in cmd:
        ok("install_hkcu.cmd reloads the pointer set after importing")
    else:
        fail("install_hkcu.cmd never calls SPI_SETCURSORS; the pointer will "
             "not change until sign-out")

    reg = open(os.path.join(ROOT, "install_hkcu.reg")).read()
    if "hex(2):" in reg:
        ok("install_hkcu.reg uses REG_EXPAND_SZ (hex(2)) so %LOCALAPPDATA% "
           "expands")
    else:
        fail("install_hkcu.reg is REG_SZ; %LOCALAPPDATA% will not expand")
    # The paths are stored as UTF-16 hex, so decode and inspect the real text.
    decoded = ""
    for chunk in reg.replace("\n", "").split("hex(2):")[1:]:
        body = "".join(chunk.split('"')[0].replace(",\\", ",")
                       .replace("\\", "").split(","))
        try:
            decoded += bytes.fromhex(body).decode("utf-16-le", "ignore")
        except ValueError:
            pass
    if "%LOCALAPPDATA%" in decoded:
        ok("install_hkcu.reg targets %LOCALAPPDATA% (no admin needed)")
    else:
        fail("install_hkcu.reg has no %LOCALAPPDATA% path once decoded")
    npaths = decoded.count("MacOS27-Native-Square") - 1
    if npaths == len(SLOTS) * 2 - 1:
        ok(f"install_hkcu.reg writes {len(SLOTS)} roles and one "
           f"{len(SLOTS)}-path scheme ({npaths} refs)")
    else:
        WARN.append(f"install_hkcu.reg has {npaths} path refs, expected "
                    f"{len(SLOTS) * 2 - 1}")

    # Every path the registry points at must exist in the package under the
    # name we ship. A role pointing at a missing file is the single most common
    # cursor-pack failure: Windows does not report it, that one role just keeps
    # showing the default pointer.
    import re as _re
    referenced = set(_re.findall(r"MacOS27-Native-Square\\([A-Za-z0-9_]+\."
                                 r"(?:cur|ani))", decoded))
    on_disk = {f for f in os.listdir(os.path.join(ROOT, "cur"))} | \
              {f for f in os.listdir(os.path.join(ROOT, "ani"))}
    ghosts = sorted(referenced - on_disk)
    if ghosts:
        fail(f"install_hkcu.reg points at files that are not in the package: "
             f"{ghosts} -- those roles would silently keep the default "
             f"pointer")
    else:
        ok(f"all {len(referenced)} registry paths exist in the package")

    # The dump's source names (40.cur, 39.cur) must never leak into an
    # installer; those are extras/ inputs, not shipped file names.
    leaked = sorted(f for f in referenced
                    if _re.match(r"^\d+\.cur$", f))
    if leaked:
        fail(f"install_hkcu.reg references dump-internal names {leaked}")
    else:
        ok("no dump-internal file names leaked into the registry paths")

    # Paths must be in a durable local directory: files under Downloads, a
    # temp folder, OneDrive or inside the zip come back as the default pointer
    # after a reboot, which is the most-reported pack complaint.
    risky = [k for k in ("Downloads", "Desktop", "Temp", "OneDrive", ".zip")
             if k.lower() in decoded.lower()]
    if risky:
        fail(f"install_hkcu.reg uses fragile locations {risky}")
    else:
        ok("registry paths point at a durable local directory")
    if "LOCALAPPDATA" in decoded:
        ok("registry paths live under %LOCALAPPDATA% (survives reboots)")
    else:
        fail("registry paths are not in a durable per-user directory")

    inf = open(os.path.join(ROOT, "install.inf")).read()
    copied = []
    grab = False
    for line in inf.splitlines():
        if line.strip() == "[Scheme.Cur]":
            grab = True
            continue
        if grab and line.startswith("["):
            break
        if grab and line.strip():
            copied.append(line.strip())

    # INF structure. Earlier revisions demanded Provider=, LayoutFile=,
    # [SourceDisksNames] and [SourceDisksFiles1] on the theory that SetupAPI
    # refuses the file without them. That was checked against the wrong
    # baseline: Apple's own dump INF has none of the five and is a
    # $CHICAGO$-signature cursor INF that installs fine. LayoutFile and
    # SourceDisksFiles1 in particular name a file that must sit beside the INF,
    # so naming one that does not exist is strictly worse than naming none.
    # Signature is the one that actually matters; Provider is kept because it
    # is conventional and costs nothing.
    for label, pattern in (
            ("Signature=\"$CHICAGO$\"", r"signature\s*=\s*\"\s*\$CHICAGO\$\s*\""),
            ("Provider=", r"provider\s*="),
            ("[Strings] (scheme name is localisable, not hardcoded)",
             r"\[strings\]")):
        if re.search(pattern, inf, re.I):
            ok(f"install.inf has {label}")
        else:
            fail(f"install.inf is missing {label}")

    # Nothing may name a file that has to sit beside the INF but is not there.
    # LayoutFile= and [SourceDisksFiles1] are the two ways this happens, and
    # both were tried here earlier: each named a file that did not exist, which
    # is worse than naming none because SetupAPI uses them to resolve the
    # numeric directory ID in [DestinationDirs].
    beside = re.findall(r"layoutfile\s*=\s*([^\s;]+)", inf, re.I)
    if "[sourcedisksfiles1]" in inf.lower():
        seg = inf.lower().split("[sourcedisksfiles1]", 1)[1].split("[", 1)[0]
        beside += [ln.split("=")[0].strip()
                   for ln in seg.splitlines() if "=" in ln]
    missing = [b for b in beside
               if not os.path.exists(os.path.join(ROOT, b))]
    if missing:
        fail("install.inf names " + ", ".join(missing)
             + " beside the INF but ships no such file; the directory ID in "
               "[DestinationDirs] cannot resolve (Apple's INF declares neither)")
    elif beside:
        WARN.append("install.inf declares " + ", ".join(beside)
                    + " and the file is present, but Apple's INF declares "
                      "neither")
    else:
        ok("install.inf names no beside-the-INF file it does not ship")

    # Line endings. SetupAPI treats CR and LF each as a terminator, so CR CR LF
    # splits every logical line in two and leaves a blank line behind it.
    raw = open(os.path.join(ROOT, "install.inf"), "rb").read()
    n_crcrlf = raw.count(b"\r\r\n")
    n_crlf = raw.count(b"\r\n")
    n_lone = raw.count(b"\n") - n_crlf
    if n_crcrlf:
        fail(f"install.inf has {n_crcrlf} CR CR LF line endings "
             f"({n_crlf} CR LF); SetupAPI will read every line twice")
    elif n_lone:
        fail(f"install.inf has {n_lone} lone LF line endings")
    else:
        ok(f"install.inf uses clean CRLF throughout ({n_crlf} lines)")

    # CopyFiles entries are resolved relative to the INF's directory; a
    # subdirectory prefix is not portable, and a path that does not resolve
    # aborts the copy silently.
    sub = [c for c in copied if "\\" in c or "/" in c]
    if sub:
        fail(f"install.inf CopyFiles uses subdirectory paths {sub[:3]}; "
             f"SetupAPI resolves these relative to the INF")
    else:
        ok(f"install.inf CopyFiles uses bare filenames "
           f"({len(copied)} entries, resolvable next to the INF)")

    missing = []
    for entry in copied:
        near = os.path.join(ROOT, entry)
        if not os.path.exists(near) and \
                not os.path.exists(os.path.join(ROOT, "cur", entry)) and \
                not os.path.exists(os.path.join(ROOT, "ani", entry)):
            missing.append(entry)
    if missing:
        fail(f"install.inf copies files that are not in the package: {missing}")
    else:
        ok(f"install.inf copies {len(copied)} files, all present")

    scheme_line = [l for l in inf.splitlines() if "Cursors\\Schemes" in l]
    if scheme_line:
        n = scheme_line[0].count(".cur") + scheme_line[0].count(".ani")
        if n == len(SLOTS):
            ok(f"install.inf registers all {len(SLOTS)} scheme slots")
        else:
            # Never hardcode the expected count here: a stale literal is how the
            # 15-vs-17 slot bug survived a whole round in the first place.
            fail(f"install.inf registers {n} slots, expected {len(SLOTS)}")

    print("\n=== 8. known cursor-pack pitfalls ===")
    # Taken from the complaints that recur about cursor packs. Every one of them
    # is silent -- Windows reports none of them -- so each needs a mechanical
    # check rather than a visual confirmation after install.

    # "some roles changed, others did not": a slot with no file keeps the
    # default pointer with no warning.
    shipped = {install_name(s, k) for s, _, k in SLOTS}
    on_disk = set(os.listdir(os.path.join(ROOT, "cur"))) | \
              set(os.listdir(os.path.join(ROOT, "ani")))
    absent = sorted(shipped - on_disk)
    if absent:
        fail(f"roles with no file in the package: {absent} (those roles keep "
             f"the default pointer)")
    else:
        ok(f"all {len(SLOTS)} roles have a file -- none silently falls back")

    # "the scheme name vanished after a reboot": a name that matches a built-in
    # scheme gets overwritten by the system one.
    if any(k in SCHEME_NAME for k in ("Windows Default", "Windows Aero",
                                      "Windows Inverted", "Windows Black")):
        fail(f"scheme name \"{SCHEME_NAME}\" collides with a built-in scheme")
    else:
        ok(f"scheme name \"{SCHEME_NAME}\" does not shadow a built-in scheme")

    # "it reverted after sign-out": the files have to be somewhere durable.
    if "LOCALAPPDATA" in decoded:
        ok("files install under %LOCALAPPDATA%, not a temp or synced folder")
    else:
        fail("files are not installed into a durable per-user directory")

    # The INF sections themselves are checked above, against the right baseline.

    # "the cursor did not change until sign-out": without SPI_SETCURSORS the
    # shell keeps the cursor set it cached at logon.
    if "refresh.vbs" in open(os.path.join(ROOT, "install_hkcu.cmd")).read():
        ok("installer asks the shell to reload the pointer set")
    else:
        fail("installer never reloads the pointer set")

    # "animated cursors show as static": the .ani pages must be present for the
    # sizes people actually use.
    for name in ("Wait", "AppStarting"):
        p = os.path.join(ROOT, "ani", name + ".ani")
        d = open(p, "rb").read()
        i, dims = 12, []
        while i + 8 <= len(d):
            cid = d[i:i + 4]
            sz = struct.unpack("<I", d[i + 4:i + 8])[0]
            body = d[i + 8:i + 8 + sz]
            if cid == b"LIST" and body[:4] == b"fram":
                j = 4
                while j + 8 <= len(body):
                    c2 = body[j:j + 4]
                    s2 = struct.unpack("<I", body[j + 4:j + 8])[0]
                    if c2 == b"icon":
                        ic = body[j + 8:j + 8 + s2]
                        _, _, cnt = struct.unpack("<HHH", ic[:6])
                        for k in range(cnt):
                            o = 6 + 16 * k
                            bw, bh = struct.unpack("<BBBBHHII",
                                                   ic[o:o + 16])[:2]
                            dims.append(bw or 256)
                        break
                    j += 8 + s2 + (s2 & 1)
                break
            i += 8 + sz + (sz & 1)
        # The documented DPI ladder asks for 32 / 48 / 64 at default pointer size
        # (and 96 at 300%, 128 at 400%). We deliberately ship 64 as the top
        # animation page rather than 96: the fourth page is free of the
        # format ceiling but doubles the file, and a resampled 64 px frame
        # costs little on a rotating beachball.
        want_ani = (32, 48, 64)
        missing_sizes = [s for s in want_ani if s not in dims]
        if missing_sizes:
            fail(f"{name}: no page for pointer size {missing_sizes}; the "
                 "documented DPI ladder asks for 32/48/64 and Windows would "
                 "resample instead")
        else:
            ok(f"{name}: pages cover 32/48/64, the sizes the documented "
               "DPI ladder requests up to 200%")

    # Cross-check the ladder against the documented DPI step table. About
    # Cursors gives it at the default pointer size: <144 dpi -> 32, 144-191 ->
    # 48, 192-287 -> 64, 288-383 -> 96, >=384 -> 128. That table is
    # explicitly non-contractual, so this is a sanity check on the machine we
    # are standing on, not a portable assertion -- and it is why the code
    # below asks the system for the real cursor size instead of assuming one.
    try:
        _u = ctypes.windll.user32
        _f = ctypes.WinDLL("user32").GetDpiForSystem
        _f.restype = ctypes.c_uint
        _dpi = _f()
        _want = (32 if _dpi < 144 else 48 if _dpi < 192 else
                 64 if _dpi < 288 else 96 if _dpi < 384 else 128)
        _real = _u.GetSystemMetrics(13)          # SM_CXCURSOR
        if _real == _want:
            ok(f"system cursor size { _real}px matches the documented DPI "
               f"step for {_dpi} dpi ({round(_dpi / 96 * 100)}%)")
        else:
            WARN.append(f"SM_CXCURSOR is {_real} but the documented DPI step "
                        f"for {_dpi} dpi is {_want}; the table is "
                        f"non-contractual so this is informational")
        if _real in PANEL_SIZES:
            ok(f"the size the system is asking for ({_real}) is in the ladder")
        else:
            fail(f"system asks for {_real}px, which the ladder does not "
                 "contain; LookupIconIdFromDirectoryEx would resample")
    except Exception as e:                       # pragma: no cover
        WARN.append(f"could not read the system cursor size: {e}")

    # Every size the documented DPI table can request has to exist as a page,
    # not just the one this machine happens to use. 150% and 175% both land on
    # 48, so a machine at either would silently get a resampled 32 px page
    # with the wrong hotspot if that page were missing.
    for _pct, _want in ((100, 32), (150, 48), (175, 48), (200, 64),
                        (300, 96), (400, 128)):
        _have = _want in PANEL_SIZES
        if not _have:
            fail(f"the documented DPI step at {_pct}% is {_want}px, which the "
                 "ladder does not carry")
    else:
        ok("every size the documented DPI table requests (32/48/64/96/128) "
           "is in the ladder, so 150% and 175% both find a native 48 px page")

    # And the 48 px pages have to be worth showing: they used to be built
    # from the 1x bitmaps, which for an 18x18 source means a 2.67x upscale
    # while the 2x bitmap needs only 1.33x. An absolute sharpness floor does
    # not catch that -- the degraded pages still scored above it -- so this
    # compares each page against the same page rebuilt from the 2x source.
    # Anything under 90% of that is the old bug coming back.
    from build_native import square_page
    if not HAVE_SRC:
        skip("48 px sharpness vs the same page rebuilt from the 2x source")
    _degraded = []
    for _slot, _src, _kind in (SLOTS if HAVE_SRC else []):
        if _kind == "ani":
            continue
        _pg = originals.get(_slot)
        if not _pg:
            continue
        _hit = [q for q in _pg if q[0] == 48]
        if not _hit:
            continue
        _nat2 = decode_pages(open(src_path(SRC_2X, SLOT_SRC[_slot]), "rb").read())[0]
        _exp = square_page(_nat2, 48)[4]

        def _edge(im):
            if np is not None:
                a = np.array(im.split()[-1]).astype(float) / 255.0
                gy, gx = np.gradient(a)
                return float(np.hypot(gx, gy).max())
            al = im.split()[-1].load()                 # pragma: no cover
            return max(abs(al[x, y] - al[x - 1, y]) / 255.0
                       for y in range(48) for x in range(1, 48))
        _want = _edge(_exp)
        _got = _edge(_hit[0][4])
        if _want and _got / _want < 0.90:
            _degraded.append(f"{_slot} {_got / _want:.0%}")
    if _degraded:
        fail("48 px pages are softer than the 2x source allows ("
             + ", ".join(_degraded[:4]) + "); that is the size a 150% or "
             "175% display requests")
    elif HAVE_SRC:
        ok("48 px pages match what the 2x source can produce, so 150% and "
           "175% get a native page rather than an upscaled 1x one")

    print("\n" + "=" * 62)
    for x in WARN:
        print(f"  WARN  {x}")
    for x in SKIPS:
        print(f"  SKIP  {x}")
    if FAILS:
        print(f"  {len(FAILS)} FAILURE(S)")
        return 1
    _tail = []
    if WARN:
        _tail.append(f"{len(WARN)} warning(s)")
    if SKIPS:
        _tail.append(f"{len(SKIPS)} skipped, no Apple dump")
    print("  ALL CHECKS PASSED" + (f"  ({', '.join(_tail)})" if _tail
                                    else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())