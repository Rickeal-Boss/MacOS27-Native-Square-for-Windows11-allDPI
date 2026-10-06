MacOS 27 (Apple Native) cursor scheme for Windows 11
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

    Arrow           Help            AppStarting     Wait            
    Crosshair       IBeam           NWPen           No              
    SizeNS          SizeWE          SizeNWSE        SizeNESW        
    SizeAll         UpArrow         Hand            Person          
    Pin             

  Person and Pin have no macOS counterpart, so they use the four-way move
  arrow from the dump's extras/ folder. NWPen and UpArrow reuse the arrow,
  since macOS ships no pen or up-arrow cursor. Help uses the framed question
  mark from extras/ rather than the plain one, because Windows shows Help for
  "select a help topic" where the framed variant reads better.


INSTALL
  Admin-free (recommended)
    1. Unpack anywhere -- keep the cur\ and ani\ subfolders where they are.
    2. Run install_hkcu.cmd. It copies the files under
       %LOCALAPPDATA%\Microsoft\Windows\Cursors\MacOS27-Native-Square,
       imports the registry keys, and then calls SPI_SETCURSORS so the shell
       reloads the pointer set immediately -- no sign-out needed.
    3. If that last step is blocked by a security policy, the scheme is still
       registered; apply it from
       Settings > Bluetooth & devices > Mouse > Additional mouse options >
       Pointers, choose "MacOS 27 (Apple Native, square multi-size)", Apply.

  System-wide
    Right-click install.inf > Install. Needs administrator rights; files go to
    %SystemRoot%\Cursors\MacOS27-Native-Square.

    An INF resolves the names in CopyFiles relative to its own folder, so the
    .cur and .ani files need to sit next to install.inf. install_hkcu.cmd does
    that automatically; if you install by hand, copy them out of cur\ and ani\
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
    This package installs to %LOCALAPPDATA%, which is durable.
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
  cur\   15 static cursors, 8 pages each (24/32/48/64/96/128/192/256),
         32-bit ARGB
  ani\   AppStarting (15 frames) and Wait (24 frames), Apple's own cadence,
         3 square pages per frame (32/48/64)
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
  changed. Their page ladder stops at 64 px: Windows loads an entire .ani into
  memory and an uncompressed 32-bit page costs size^2 * 4 bytes, so covering
  every size would make Wait 12.8 MB against 0.53 MB for the animation Windows
  ships itself. At 128 px and above Windows rescales the 64 px page, which for
  a smoothly rotating ball is not noticeable.


VERIFYING
  source\verify_native.py re-runs every check: the ICONDIR/ICONDIRENTRY/
  BITMAPINFOHEADER fields against the documented layout, pages square, ladder
  complete, the AND mask exactly the complement of alpha, every hotspot
  matching where the Apple original puts it, LoadCursorFromFile succeeding on
  every file, the animations matching the dump frame for frame, the installers
  referencing files that exist, and a pass over the failure modes cursor packs
  commonly ship with. Run it with any Python that has Pillow:

      python source\verify_native.py

  source\build_native.py regenerates the whole package from the dump.


REQUIREMENTS
  Windows 7 or later. These cursors do not need a theme to work.
