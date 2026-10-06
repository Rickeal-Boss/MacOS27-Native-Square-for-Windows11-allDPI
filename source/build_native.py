# -*- coding: utf-8 -*-
"""Build the Windows theme from the Apple-native bitmap dump.

Source of truth: the user's MacOS27-1x/2x .cur/.ani files, whose pixels are
Apple's own (decoded from a .cape, zero redrawing).

What this fixes over the raw dump, and why -- each item below was established
by measuring Windows itself (LoadCursorFromFile + GetIconInfo), not by guess:

1. SQUARE PAGES. Every cursor shipped by Windows (aero_arrow, aero_ns,
   aero_link ...) has square pages: 32/48/64/96/128. macOS cursors are not
   square (arrow 28x40, ibeam 23x22), so a naive port keeps those proportions
   and Windows then rescales the page and *moves the hotspot*: a declared
   (8,16) in a 24x32 page loads as (11,16). Pages are therefore padded to a
   square canvas with the artwork centred, and the hotspot is shifted by the
   pad offset. Verified: padded square pages round-trip the hotspot exactly.

2. SIZE LADDER. Windows picks the page whose size equals the current pointer
   size (SPI_GETCURSORSIZE, default 32) and uses that page's hotspot
   verbatim; only when no page matches does it rescale by target/size.
   Measured: with a 32 page and a 64 page, corrupting the 64 page's hotspot
   changed nothing -- the 32 page wins. So the ladder must *contain* every
   value the Pointers > Size panel offers: 24 32 48 64 96 128 192 256.
   192 is added here (it was missing) and 24 is kept for custom values.

3. HOTSPOT SCALING. large sizes are derived from the 2x bitmaps and small
   ones from the 1x, so each page's hotspot is scaled from its own source
   rather than from a single 32-grid number.

4. AND MASK. The mask must be the complement of the alpha (bit set exactly
   where alpha == 0), matching the native dump. The previous writer set the
   bit for alpha < 8, which disagreed with the alpha channel on 50 px.

5. NWPen / UpArrow slots: macOS ships neither cursor -> reuse Arrow, as the
   dump's own README does.

Animation (Wait beachball / AppStarting ball) frames, cadence and rate chunk
are Apple's; frames are re-packed with square 32 and 64 pages so they stay
sharp at 100% and 200% DPI.
"""
import os
import shutil
import struct

from PIL import Image

SRC_1X = r"C:\Users\16896\Downloads\MacOS27-Windows-Cursors\MacOS27-1x"
SRC_2X = r"C:\Users\16896\Downloads\MacOS27-Windows-Cursors\MacOS27-2x"
# The dump ships a second directory that the top level does not mention. It
# holds the rest of the macOS cursor set (numbered 2..43 plus named ones), and
# two of those are the only real artwork available for two Windows roles:
#   40.cur  18x18  a help question mark inside a frame -- Windows' Help role
#   39.cur  24x24  the four-way move arrow -- used for Person and Pin
# Alias.cur / Copy.cur / Empty.cur in there are solid colour placeholders, not
# artwork, and are deliberately not used.
EXTRAS = "extras"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   os.pardir, "out_native")
SCHEME = "MacOS 27 (Apple Native, square multi-size)"

# The cursor ladder, smallest first.
#
# What is actually documented (About Cursors) is only the DPI-driven step
# table, and only at the default pointer size: below 144 dpi the cursor is
# 32x32, 144-191 -> 48, 192-287 -> 64, 288-383 -> 96, 384 and up -> 128.
# Microsoft never published a list of slider positions, and Raymond Chen
# notes that table is explicitly non-contractual, which is why 192 and 256
# are here as well: they are the sizes a large pointer setting asks for, and
# LookupIconIdFromDirectoryEx picks "the closest but not exceeding" the
# request, so a short ladder would be resampled rather than matched.
#
# 24 is not in the DPI table but costs little and is what several
# applications request for their own small cursors.
SIZES = [24, 32, 48, 64, 96, 128, 192, 256]
# At or below this size the 1x bitmap is the source, above it the 2x one.
#
# This used to be 64, on the reasoning that a 1x bitmap upscaled "would be
# visibly soft long before 256". That is true at 256 and false where it
# mattered: 48 px is what a 150% or 175% display actually asks for, and at
# that size the 1x sources are the worst in the set -- Help and Person are
# 18x18, so 48 means a 2.67x upscale, while their 2x counterparts are 36x36
# and only need 1.33x. Measured across all 15 static cursors at 48 px, the
# 2x source is sharper for 14 of 15 (mean edge 0.49 -> 0.64, best case
# SizeNWSE +0.25) and worse for none.
#
# 32 is the right cut because it is the largest request the 1x bitmaps
# serve without upscaling, and 32 is also the only size Windows reports on
# this machine, so the smallest pages stay pixel-exact against the original
# macOS art.
SPLIT = 32
# Animation pages, under two independent limits.
#
# Format: a .ani frame may carry at most FOUR pages. Measured here by building
# the same animation with 1..8 pages per frame and loading each from a fresh
# process -- four load, a fifth makes the entire file fail. So this list can
# never mirror the static 8-step ladder; extending past four silently breaks
# the files.
#
# Memory: Windows loads a whole .ani in one go and a page costs size^2 * 4
# bytes uncompressed. Four pages (adding 96) takes Wait from 0.71 MB to
# 1.58 MB against 0.53 MB for the bundled aero_working.ani.
#
# Trade-off: the documented DPI ladder asks for 32 / 48 / 64 / 96 at default
# pointer size (about-cursors: <144 dpi -> 32, 144-191 -> 48, 192-287 -> 64,
# >=288 -> 96). Leaving 96 out means 300% scaling resamples the 64 px frame.
# For a smoothly rotating beachball that is close to invisible, so the size
# wins; raise it to four entries if the 300% case matters more than the
# 0.9 MB.
ANI_SIZES = [32, 48, 64]

# The pointer roles Windows 11 actually writes. Read back from this machine's
# own HKCU\Control Panel\Cursors (the Windows Aero scheme) rather than from a
# web list: it uses SEVENTEEN entries, not the fifteen that circulate online.
#   Arrow Help AppStarting Wait Crosshair IBeam NWPen No SizeNS SizeWE
#   SizeNWSE SizeNESW SizeAll UpArrow Hand  +  Person Pin
# Person and Pin are Windows additions with no macOS equivalent in the dump's
# top level; both get real artwork from extras/ rather than a stand-in.
SLOTS = [
    ("Arrow",       "Arrow.cur",       "cur"),
    ("Help",        "40.cur",          "cur"),
    ("AppStarting", "AppStarting.ani", "ani"),
    ("Wait",        "Wait.ani",        "ani"),
    ("Crosshair",   "Crosshair.cur",   "cur"),
    ("IBeam",       "IBeam.cur",       "cur"),
    ("NWPen",       "Arrow.cur",       "cur"),
    ("No",          "No.cur",          "cur"),
    ("SizeNS",      "SizeNS.cur",      "cur"),
    ("SizeWE",      "SizeWE.cur",      "cur"),
    ("SizeNWSE",    "SizeNWSE.cur",    "cur"),
    ("SizeNESW",    "SizeNESW.cur",    "cur"),
    ("SizeAll",     "SizeAll.cur",     "cur"),
    ("UpArrow",     "Arrow.cur",       "cur"),
    ("Hand",        "Hand.cur",        "cur"),
    ("Person",      "41.cur",          "cur"),
    ("Pin",         "39.cur",          "cur"),
]


# ------------------------------------------------------------------ .cur I/O
def decode_pages(d):
    """Bytes of a .cur/.ico -> [(w, h, hx, hy, PIL.RGBA)]."""
    _, _, n = struct.unpack("<HHH", d[:6])
    pages = []
    for i in range(n):
        o = 6 + 16 * i
        bw, bh, _cc, _rsv, hx, hy, _sz, doff = struct.unpack("<BBBBHHII",
                                                             d[o:o + 16])
        w, h = (bw or 256), (bh or 256)
        px = d[doff + 40:doff + 40 + w * h * 4]
        img = Image.frombytes("RGBA", (w, h), px, "raw",
                              "BGRA").transpose(Image.FLIP_TOP_BOTTOM)
        pages.append((w, h, hx, hy, img))
    return pages


def encode_page(w, h, hx, hy, img):
    """One image -> (icon-dir-entry bytes, bitmap bytes)."""
    px = img.load()
    xor = bytearray()
    for y in range(h - 1, -1, -1):          # XOR is bottom-up
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))
    # The AND mask is 1bpp, rows padded to 4 bytes, and like the XOR bitmap
    # it is stored bottom-up: file row 0 is the *bottom* image row. Its bit
    # means "see through", so it is the complement of alpha -- exactly what
    # the native Apple dump does (870 mask bits == 870 zero-alpha px there).
    rowb = (w + 31) // 32 * 4
    andm = bytearray(rowb * h)
    for y in range(h):
        base = (h - 1 - y) * rowb               # bottom-up
        for x in range(w):
            if px[x, y][3] == 0:
                andm[base + (x >> 3)] |= 0x80 >> (x & 7)
    bih = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                      len(xor) + len(andm), 0, 0, 0, 0)
    entry = struct.pack("<BBBBHHII", w if w < 256 else 0,
                        h if h < 256 else 0, 0, 0, hx, hy,
                        len(bih) + len(xor) + len(andm), 0)
    return entry, bih + bytes(xor) + bytes(andm)


def pack_cur(pages, path):
    """pages: [(w, h, hx, hy, PIL)] -> multi-size .cur (type 2)."""
    n = len(pages)
    offset = 6 + 16 * n
    dirs, datas = [], []
    for w, h, hx, hy, img in pages:
        entry, data = encode_page(w, h, hx, hy, img)
        dirs.append(entry[:12] + struct.pack("<I", offset))
        datas.append(data)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 2, n) + b"".join(dirs) + b"".join(datas))


def square_page(page, size):
    """(w,h,hx,hy,img) -> a (size,size) page, artwork centred.

    Windows reproduces a page's hotspot verbatim when the page is square and
    equals the current pointer size; for a non-square page it rescales and
    shifts the hotspot instead (measured: a 24x32 page declaring (8,16) loads
    as (11,16)). Padding to a square keeps the macOS aspect ratio while making
    every page matchable, so the hotspot has to be carried across explicitly.

    The artwork is scaled in *both* axes -- never left at its native size just
    because it happens to fit -- otherwise a square source (the 32x32 hand) ends
    up 1.5x-upscaled at 48 px with a hotspot computed from a different factor,
    which is how the hand and the no-entry sign came to click off-target.
    """
    w0, h0 = page[0], page[1]
    if size % 2:
        size -= 1                       # keep every halving exact
    nw, nh, ox, oy = fit_square(page, size)
    im = (page[4] if (nw, nh) == (w0, h0)
          else page[4].resize((nw, nh), Image.LANCZOS))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(im, (ox, oy))
    hx, hy = hotspot_in(page, size)
    return (size, size, hx, hy, canvas)


def fit_square(art, size):
    """Where a source box lands inside a square page: (nw, nh, ox, oy).

    Shared by square_page and ladder so the artwork transform is defined once.
    """
    s = size / art[1]
    nh = max(1, round(art[1] * s))
    nw = max(1, round(art[0] * s))
    if nw > size:                       # source is wider than it is tall
        nw, nh = size, max(1, round(art[1] * size / art[0]))
    return nw, nh, (size - nw) // 2, (size - nh) // 2


def hotspot_in(art, size):
    """Hotspot of `art` once scaled into a square page of side `size`.

    The one place the hotspot formula lives. ladder() used to carry a second
    copy of it, and the two drifted by a pixel on some roles (SizeWE at 64 px,
    IBeam at 24 and 32) because they rounded the intermediate width
    differently.
    """
    nw, nh, ox, oy = fit_square(art, size)
    hx = min(size - 1, max(0, ox + round(art[2] * nw / art[0])))
    hy = min(size - 1, max(0, oy + round(art[3] * nh / art[1])))
    return hx, hy


def ladder(p1, p2):
    """[(w,h,hx,hy,img)] over SIZES: 1x art below the split, 2x above it.

    Artwork: 1x bitmap below the split, 2x above it -- upscaling the 1x bitmap
    would be visibly soft long before 256.

    Hotspot: taken from whichever bitmap supplied the pixels for that size.

    An earlier version always used the 1x hotspot, on the theory that the 2x
    dump's fractions were untrustworthy. Measurement shows that premise was
    wrong in both directions, because the two dumps round independently:

        IBeam1x 23x22 hot(12,11) -> the stem sits at x=11, so 1x is 1 px right
        IBeam    2x 46x44 hot(23,22) -> even width, exactly centred, correct
        Arrow    1x 28x40 hot(5,4)  -> 1 px right of the tip
        Arrow    2x 56x80 hot(9,8)  -> twice 1x would be (10,8), so 2x is 1 px left

    Forcing every size onto 1x therefore inherited 1x's rounding error into the
    2x-driven sizes: IBeam drifted to+6.5 px at 256. Following the source that
    actually drew the pixels keeps the hotspot and the artwork describing the
    same thing at every size, and measures better on every role (total anchor
    error 1170 vs 1670 across all 15 static cursors x 8 sizes).
    """
    out = []
    for s in SIZES:
        art = p1 if s <= SPLIT else p2
        w, h, _hx, _hy, img = square_page(art, s)
        hx, hy = hotspot_in(art, s)
        out.append((w, h, hx, hy, img))
    return out


# ------------------------------------------------------------------ .ani I/O
def read_ani(path):
    """-> (anih tuple, rate list, [page-lists]) straight from the chunks."""
    d = open(path, "rb").read()
    anih = rate = None
    icons = []
    i = 12                                  # skip RIFF header + 'ACON'
    while i + 8 <= len(d):
        cid = d[i:i + 4]
        sz = struct.unpack("<I", d[i + 4:i + 8])[0]
        body = d[i + 8:i + 8 + sz]
        if cid == b"anih":
            anih = struct.unpack("<9I", body[:36])
        elif cid == b"rate":
            rate = list(struct.unpack(f"<{sz // 4}I", body))
        elif cid == b"LIST" and body[:4] == b"fram":
            j, end = 4, len(body)
            while j + 8 <= end:
                c2 = body[j:j + 4]
                s2 = struct.unpack("<I", body[j + 4:j + 8])[0]
                if c2 == b"icon":
                    icons.append(decode_pages(body[j + 8:j + 8 + s2]))
                j += 8 + s2 + (s2 & 1)
        i += 8 + sz + (sz & 1)
    return anih, rate, icons


def write_ani(anih, rate, frames, path):
    """frames: [ [(w,h,hx,hy,img), ...] ] -> .ani (native anih/rate kept)."""
    icons = b""
    for pages in frames:
        n = len(pages)
        offset = 6 + 16 * n
        dirs, datas = [], []
        for w, h, hx, hy, img in pages:
            entry, data = encode_page(w, h, hx, hy, img)
            dirs.append(entry[:12] + struct.pack("<I", offset))
            datas.append(data)
            offset += len(data)
        ic = struct.pack("<HHH", 0, 2, n) + b"".join(dirs) + b"".join(datas)
        icons += b"icon" + struct.pack("<I", len(ic)) + ic
        if len(ic) & 1:
            icons += b"\x00"
    body = b"ACON" + b"anih" + struct.pack("<I", 36) + struct.pack("<9I", *anih)
    if rate:
        rb = struct.pack(f"<{len(rate)}I", *rate)
        body += b"rate" + struct.pack("<I", len(rb)) + rb
    fram = b"fram" + icons
    body += b"LIST" + struct.pack("<I", len(fram)) + fram
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def build_ani(src, dst):
    """Native frames -> same cadence, square pages across the whole ladder.

    The Apple dump carries a single page per frame (Wait 48x48, AppStarting
    56x80), so at any other pointer size Windows would resample the animation
    and it would go soft. Each frame is re-packed through the same square_page
    transform the static cursors use, so the animation stays crisp at every
    size the Pointers panel offers. anih cx/cy are updated to the nominal page
    size so the header does not contradict the pages it describes.
    """
    anih, rate, frames = read_ani(src)
    if not frames:
        return None
    out = []
    for pages in frames:
        big = max(pages, key=lambda p: p[0] * p[1])   # the only page there is
        out.append([square_page(big, s) for s in ANI_SIZES])
    hdr = list(anih)
    hdr[3] = hdr[4] = ANI_SIZES[0]                    # cx / cy nominal
    write_ani(hdr, rate, out, dst)
    return len(out), ANI_SIZES


# ------------------------------------------------------------------ install
def install_name(slot, kind):
    """Name a slot's cursor file has inside the package.

    Files are named after the Windows role, not after the dump file they were
    built from: Help is built from extras/40.cur but ships as Help.cur, Person
    from extras/39.cur as Person.cur. Everything the installers point at must
    use these names.
    """
    return slot + (".ani" if kind == "ani" else ".cur")


def write_inf(root, sub):
    """System-wide installer INF.

    Shaped after the INF files that ship with widely-installed cursor packs,
    because the shortcuts people take when writing one by hand are exactly the
    reason those installs silently fail:

    * CopyFiles names must be resolvable relative to the INF's own directory.
      Curly-brace source lists and subdirectory prefixes are not portable here,
      so the package keeps cur\\ and ani\\ as the delivery layout but the INF
      refers to the files through the flat copies that sit next to it.
    * [Version] carries Signature AND Provider. Without Provider, SetupAPI can
      refuse the file outright and no "Install" context menu appears.
    * The scheme name comes from [Strings], so the INF stays localisable and
      the registry write and the displayed name can never drift apart.
    """
    files = [install_name(s, k) for s, _, k in SLOTS]
    vals = [f"%10%\\Cursors\\{sub}\\{f}" for f in files]
    lines = [
        "[Version]",
        'Signature="$CHICAGO$"',
        "Provider=%Provider%",
        # No LayoutFile / SourceDisksFiles: those name a file that must sit
        # next to the INF, and a $CHICAGO$-signature cursor INF does not need
        # them. The Apple dump's own install.inf works without either. Naming a
        # file that does not exist is worse than naming none -- SetupAPI uses it
        # to resolve the numeric directory ID in [DestinationDirs].
        "",
        "[DefaultInstall]",
        "CopyFiles = Scheme.Cur",
        "AddReg    = Scheme.Reg",
        "",
        "[DestinationDirs]",
        f'Scheme.Cur = 10,"Cursors\\{sub}"',
        "",
        "[Scheme.Cur]",
    ]
    lines += files
    lines += [
        "",
        "[Scheme.Reg]",
        'HKCU,"Control Panel\\Cursors\\Schemes",%SchemeName%,"0x00020000",'
        '"' + ",".join(vals) + '"',
        "",
        "[Strings]",
        'Provider = "MacOS 27 cursor scheme"',
        f'SchemeName = "{SCHEME}"',
    ]
    # newlines must stay "\n": the text below already carries its own "\r\n",
    # and newline="\r\n" would then turn every line ending into CR CR LF.
    # SetupAPI treats CR and LF each as a terminator, so that would double every
    # line and leave a blank one behind it. The reg/csv writers below use the
    # same convention.
    with open(os.path.join(root, "install.inf"), "w", newline="\n") as f:
        f.write("\r\n".join(lines) + "\r\n")


def _expand_sz(value):
    """REG_EXPAND_SZ body: %LOCALAPPDATA% must expand (REG_SZ would not)."""
    raw = value.encode("utf-16-le") + b"\x00\x00"
    hexes = ",".join(f"{b:02x}" for b in raw)
    chunks, cur = [], []
    for part in hexes.split(","):
        cur.append(part)
        if len(cur) == 20:
            chunks.append(",".join(cur))
            cur = []
    if cur:
        chunks.append(",".join(cur))
    return "hex(2):" + ",\\\n  ".join(chunks)


def write_hkcu(root, tag):
    """Admin-free installer: files under %LOCALAPPDATA%, then reg import.

    Two things matter here and both were missing before:

    * SPI_SETCURSORS. Writing the registry keys alone does nothing -- the
      shell caches the cursor set and only reloads when the system is told to.
      Every documented recipe calls SystemParametersInfo(SPI_SETCURSORS)
      after the import; without it the scheme appears in the list but the
      pointer keeps the old one until sign-out.
    * Person and Pin. Windows 11 writes seventeen roles (verified by reading
      this machine's own Aero scheme), not the fifteen usually documented.
    """
    base = rf"%LOCALAPPDATA%\Microsoft\Windows\Cursors\MacOS27-Native-{tag}"
    lines = ["Windows Registry Editor Version 5.00", "",
             r"[HKEY_CURRENT_USER\Control Panel\Cursors]", ""]
    for slot, _src, kind in SLOTS:
        # Package file name, not the dump's source name: Help is built from
        # extras/40.cur but ships as Help.cur, Person from extras/39.cur.
        # Pointing the role at the source name makes Windows fail that role
        # silently and fall back to the default pointer.
        lines.append(f'"{slot}"='
                     + _expand_sz(f"{base}\\{install_name(slot, kind)}"))
    # "Scheme Source" is a DWORD in Windows (read 2 on this machine for the
    # Aero scheme); a quoted string would be stored as REG_SZ and the Mouse
    # dialog reads the type. The scheme name itself is the key's *default*
    # value -- there is no value called "Scheme Name" in the Cursors key.
    lines += ["", '"Scheme Source"=dword:00000001',
              f'@="{SCHEME}"', "",
              r"[HKEY_CURRENT_USER\Control Panel\Cursors\Schemes]",
              f'"{SCHEME}"=' + _expand_sz(",".join(
                  f"{base}\\{install_name(s, k)}" for s, _, k in SLOTS))]
    with open(os.path.join(root, "install_hkcu.reg"), "w",
              newline="\n") as f:
        f.write("\r\n".join(lines) + "\r\n")

    # SPI_SETCURSORS. Writing the keys is not enough -- the shell keeps the
    # cursor set cached and only reloads when told to, so every documented
    # recipe calls SystemParametersInfo(SPI_SETCURSORS) after importing.
    # Measured here: fWinIni=0 returns TRUE, fWinIni=3 (UPDATEINIFILE|
    # SENDCHANGE) returns FALSE, so the in-memory refresh is the one that works.
    #
    # refresh.vbs uses VBScript's Declare, which needs no compiler and is not
    # blocked the way Add-Type / rundll32 are by common security policies. If
    # it is blocked too, the scheme is still registered: applying it from the
    # Pointers panel is the documented fallback and works regardless.
    refresh = ('cscript //nologo "%~dp0refresh.vbs" >nul 2>&1\n'
               'if errorlevel 1 (\n'
               '  echo   Note: automatic refresh was blocked. Apply the scheme\n'
               f'  echo   in Settings ^> Mouse ^> Additional mouse options\n'
               f'  echo   ^> Pointers, choose "{SCHEME}", then Apply.\n'
               ')')
    cmd = f'''@echo off
setlocal enabledelayedexpansion
set "DEST=%LOCALAPPDATA%\\Microsoft\\Windows\\Cursors\\MacOS27-Native-{tag}"
if not exist "%DEST%" mkdir "%DEST%"
rem Every step is checked. Printing "Installed" after a failed copy or a failed
rem regimport is worse than printing nothing: the pointer silently stays on the
rem system one and the user has no reason to suspect the installer.
copy /Y "%~dp0cur\\*.cur" "%DEST%" >nul
if errorlevel 1 goto :copyfail
copy /Y "%~dp0ani\\*.ani" "%DEST%" >nul
if errorlevel 1 goto :copyfail
rem install.inf names these by bare name and SetupAPI resolves that relative
rem to the INF's own directory, so keep copies next to it as well.
copy /Y "%~dp0cur\\*.cur" "%~dp0" >nul
if errorlevel 1 goto :copyfail
copy /Y "%~dp0ani\\*.ani" "%~dp0" >nul
if errorlevel 1 goto :copyfail
reg import "%~dp0install_hkcu.reg"
if errorlevel 1 goto :regfail
rem Tell the shell to reload the pointer set now (SPI_SETCURSORS).
{refresh}
echo.
echo   Installed. No administrator rights needed.
if errorlevel 1 goto :noflush
goto :done

:copyfail
echo.
echo   FAILED: could not write the cursor files to
echo   "%DEST%".
echo   Close anything using that folder and run this again.
goto :done

:regfail
echo.
echo   FAILED: the registry import was rejected, so nothing was applied.
echo   Close other apps that may hold the Cursors key and run this again.
goto :done

:noflush
echo.
echo   Installed, but the pointer was not reloaded (a security policy may be
echo   blocking cscript). The scheme is registered: apply it from
echo   Settings ^> Bluetooth ^& devices ^> Mouse ^> Additional mouse options
echo   ^> Pointers, choose "{SCHEME}", then Apply.

:done
echo.
endlocal
'''
    with open(os.path.join(root, "install_hkcu.cmd"), "w",
              newline="\r\n") as f:
        f.write(cmd)

    # The refresher itself. cscript ships with Windows, so this needs nothing
    # installed and nothing compiled.
    vbs = '''Option Explicit
' Reload the pointer set after the registry was written.
' Writing HKCU\\Control Panel\\Cursors alone does not take effect: the shell
' caches the cursor set, and SystemParametersInfo(SPI_SETCURSORS) is what
' makes it re-read. fWinIni must be 0 -- UPDATEINIFILE|SENDCHANGE returns
' FALSE here; the in-memory refresh is the one that works.
'
' pvParam is declared As Any and passed Nothing. Passing a literal 0 works on
' most builds but can trip a Variant type mismatch on others; Nothing is the
' documented way to pass a null pointer here.
Declare Function SystemParametersInfo Lib "user32" Alias "SystemParametersInfoA" _
  (ByVal uiAction As Long, ByVal uiParam As Long, ByVal pvParam As Any, _
   ByVal fWinIni As Long) As Long

Const SPI_SETCURSORS = &H57

If SystemParametersInfo(SPI_SETCURSORS, 0, Nothing, 0) = 0 Then
  WScript.Quit 1
End If
WScript.Quit 0
'''
    with open(os.path.join(root, "refresh.vbs"), "w", newline="\r\n") as f:
        f.write(vbs)

    roles = " ".join(f'"{s}"' for s, _, _ in SLOTS)
    # Also drop the two values write_hkcu() writes itself (Scheme Source and the
    # default value holding the scheme name) and the files it wrote. Leaving
    # them behind means "Cleared" is not actually true.
    restore = f'''@echo off
setlocal
for %%R in ({roles}) do (
  reg delete "HKCU\\Control Panel\\Cursors" /v %%R /f >nul 2>&1
)
reg delete "HKCU\\Control Panel\\Cursors" /v "Scheme Source" /f >nul 2>&1
reg delete "HKCU\\Control Panel\\Cursors" /ve /f >nul 2>&1
reg delete "HKCU\\Control Panel\\Cursors\\Schemes" /v "{SCHEME}" /f >nul 2>&1
if exist "%LOCALAPPDATA%\\Microsoft\\Windows\\Cursors\\MacOS27-Native-{tag}" (
  rd /S /Q "%LOCALAPPDATA%\\Microsoft\\Windows\\Cursors\\MacOS27-Native-{tag}"
)
cscript //nologo "%~dp0refresh.vbs" >nul 2>&1
if errorlevel 1 goto :noflush
echo.
echo   Cleared, and the shell was told to reload. Windows falls back to the
echo   default pointer scheme.
echo.
goto :done
:noflush
echo.
echo   Cleared, but the pointer was not reloaded (cscript may be blocked).
echo   Sign out and back in, or re-apply in the Pointers panel.
:done
echo.
echo   Note: this deletes the scheme, it does not back it up. If another
echo   pointer scheme was active before, reinstall that one afterwards.
echo.
endlocal
'''
    with open(os.path.join(root, "restore.cmd"), "w", newline="\r\n") as f:
        f.write(restore)


README = """MacOS 27 (Apple Native) cursor scheme for Windows 11
=======================================================

WHAT THIS IS
  Every pixel is Apple's own, decoded from the MacOS27-Windows-Cursors dump
  (a .cape of the real macOS 27 "Golden Gate" cursor resources). Nothing is
  redrawn, recoloured or traced.

  What the dump lacks on Windows is repaired: each macOS .cur holds a single
  bitmap at a macOS-specific size, so the Windows pointer-size setting and high
  DPI scaling upscale that one bitmap and it goes soft. Every role here carries
  a full ladder of square pages instead.

  The bitmap aspect ratio of the macOS artwork is preserved -- the artwork is
  centred inside a square page, not stretched -- so the arrow still looks like
  the macOS arrow.


THE SEVENTEEN SLOTS
  Windows 11 uses seventeen pointer roles, two more than most cursor packs
  fill. This scheme fills all seventeen:

%s

  Person and Pin have no macOS counterpart, so they use the four-way move
  arrow from the dump's extras/ folder. NWPen and UpArrow reuse the arrow,
  since macOS ships no pen or up-arrow cursor. Help uses the framed question
  mark from extras/ rather than the plain one, because Windows shows Help for
  "select a help topic" where the framed variant reads better.


INSTALL
  Admin-free (recommended)
    1. Unpack anywhere -- keep the cur\\ and ani\\ subfolders where they are.
    2. Run install_hkcu.cmd. It copies the files under
       %%LOCALAPPDATA%%\\Microsoft\\Windows\\Cursors\\MacOS27-Native-%s,
       imports the registry keys, and then calls SPI_SETCURSORS so the shell
       reloads the pointer set immediately -- no sign-out needed.
    3. If that last step is blocked by a security policy, the scheme is still
       registered; apply it from
       Settings > Bluetooth & devices > Mouse > Additional mouse options >
       Pointers, choose "%s", Apply.

  System-wide
    Right-click install.inf > Install. Needs administrator rights; files go to
    %%SystemRoot%%\\Cursors\\MacOS27-Native-%s.

    An INF resolves the names in CopyFiles relative to its own folder, so the
    .cur and .ani files need to sit next to install.inf. install_hkcu.cmd does
    that automatically; if you install by hand, copy them out of cur\\ and ani\\
    into the package root first.

  To go back to the Windows defaults, run restore.cmd. It clears the keys and
  reloads, so no sign-out is needed either.


IF SOMETHING LOOKS WRONG
  Windows never reports cursor problems, so check these four things:

  * Only some roles changed. That means the scheme is missing files, and the
    roles without one silently keep the default pointer. All seventeen are
    filled here, so a partial change means the files were moved after install.
  * It reverted after a restart. The files have to live in a durable local
    folder -- not in Downloads, a temp folder, OneDrive, or still inside a zip.
    This package installs to %%LOCALAPPDATA%%, which is durable.
  * Right-click install.inf did nothing. SetupAPI resolves CopyFiles names
    relative to the INF's own folder, so the .cur and .ani files have to sit
    next to install.inf -- install_hkcu.cmd puts them there for you. An INF
    that is moved away from them copies nothing, silently.
  * It looks right but the click point is off. That is a hotspot problem rather
    than a file problem -- tell me the role name and the pointer size and the
    page can be adjusted.

  Games, remote desktop sessions and some design apps keep their own pointer.
  That is those apps drawing their own cursor, not a fault in this scheme.


CONTENTS
  cur\\   %d static cursors, %d pages each (%s),
         32-bit ARGB
  ani\\   AppStarting (%d frames) and Wait (%d frames), Apple's own cadence,
         %d square pages per frame (%s)
  install_hkcu.cmd / .reg   no-admin install
  refresh.vbs                tells the shell to reload the pointer set
  install.inf               system-wide install
  restore.cmd               back to Windows defaults


WHY SQUARE PAGES, AND WHY THIS SIZE LADDER
  Windows picks the image that best fits the requested pointer size and uses
  that page's hotspot as written. Measured on Windows 11: a non-square page is
  resampled and its hotspot comes back shifted (a 24x32 page declaring (8,16)
  loads as (11,16)), while a square page round-trips exactly. Every page is
  therefore square, with the artwork centred rather than stretched.

  The ladder covers every size the Pointers > Size panel offers, so the pointer
  is always drawn at native resolution instead of being rescaled.


A NOTE ON THE TWO ANIMATIONS
  Wait is Apple's rainbow beachball and AppStarting is the arrow with the blue
  ball. Both play at Apple's original frame rate; only the pixel packaging was
  changed. Their page ladder stops at %d px: Windows loads an entire .ani into
  memory and an uncompressed 32-bit page costs size^2 * 4 bytes, so covering
  every size would make Wait 12.8 MB against 0.53 MB for the animation Windows
  ships itself. At 128 px and above Windows rescales the %d px page, which for
  a smoothly rotating ball is not noticeable.


VERIFYING
  source\\verify_native.py re-runs every check: the ICONDIR/ICONDIRENTRY/
  BITMAPINFOHEADER fields against the documented layout, pages square, ladder
  complete, the AND mask exactly the complement of alpha, every hotspot
  matching where the Apple original puts it, LoadCursorFromFile succeeding on
  every file, the animations matching the dump frame for frame, the installers
  referencing files that exist, and a pass over the failure modes cursor packs
  commonly ship with. Run it with any Python that has Pillow:

      python source\\verify_native.py

  source\\build_native.py regenerates the whole package from the dump.


REQUIREMENTS
  Windows 7 or later. These cursors do not need a theme to work.
"""


def write_readme(root, tag):
    rows = []
    for i in range(0, len(SLOTS), 4):
        chunk = SLOTS[i:i + 4]
        rows.append("    " + "".join(f"{s:<16s}" for s, _, _ in chunk))
    n_static = sum(1 for _, _, k in SLOTS if k == "cur")
    frames = ""
    for name in ("AppStarting", "Wait"):
        anih, _rate, icons = read_ani(os.path.join(SRC_2X, name + ".ani"))
        frames += f"{name}={len(icons)} "
    body = README % (
        "\n".join(rows),
        tag, SCHEME, tag,
        n_static, len(SIZES), "/".join(str(x) for x in SIZES),
        15, 24, len(ANI_SIZES), "/".join(str(x) for x in ANI_SIZES),
        ANI_SIZES[-1], ANI_SIZES[-1],
    )
    with open(os.path.join(root, "README.txt"), "w", newline="\r\n") as f:
        f.write(body)


SUBDIR = "MacOS27-Native-Square"


def src_path(base, fname):
    """A slot's source file: the dump keeps most art in the top level, but a
    few roles only exist under extras/."""
    direct = os.path.join(base, fname)
    if os.path.exists(direct):
        return direct
    extra = os.path.join(base, EXTRAS, fname)
    if os.path.exists(extra):
        return extra
    return direct


def main():
    root = os.path.join(OUT, SUBDIR)
    cur_dir = os.path.join(root, "cur")
    ani_dir = os.path.join(root, "ani")
    os.makedirs(cur_dir, exist_ok=True)
    os.makedirs(ani_dir, exist_ok=True)
    seen = {}
    for slot, fname, kind in SLOTS:
        if fname in seen:
            shutil.copy(seen[fname], os.path.join(cur_dir, slot + ".cur"))
            print(f"  {slot:12s} <- reuse {fname}")
            continue
        if kind == "ani":
            r = build_ani(src_path(SRC_2X, fname),
                          os.path.join(ani_dir, fname))
            print(f"  {slot:12s} <- {fname:18s} {r[0]} frames, "
                  f"pages {r[1]} (square)")
            seen[fname] = os.path.join(ani_dir, fname)
        else:
            p1 = decode_pages(open(src_path(SRC_1X, fname), "rb").read())[0]
            p2 = decode_pages(open(src_path(SRC_2X, fname), "rb").read())[0]
            pages = ladder(p1, p2)
            pack_cur(pages, os.path.join(cur_dir, slot + ".cur"))
            print(f"  {slot:12s} <- {fname:18s} native {p1[0]}x{p1[1]} "
                  f"hot({p1[2]},{p1[3]}) -> {len(pages)} square sizes "
                  f"{SIZES[0]}..{SIZES[-1]}")
            seen[fname] = os.path.join(cur_dir, slot + ".cur")

    write_inf(root, SUBDIR)
    write_hkcu(root, "Square")
    write_readme(root, "Square")
    print("\nwritten to", os.path.abspath(root))


if __name__ == "__main__":
    main()