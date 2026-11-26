"""Copy the three jars PowerShock builds against out of your own leJOS EV3 SD card.

    python pc/tools/extract_libs.py <folder with your SD card's files>

The folder is a copy of (or the mounted) leJOS 0.9.1 SD card: it holds lejosimage.bz2 and
ejre-7u60-*.tar.gz. Writes lib/ev3classes.jar, lib/jna.jar and lib/rt7.jar.

These files aren't in the repository: Oracle's Java runtime may not be redistributed, and
leJOS and JNA come with their own licences, so everyone takes them from their own card.
Only the three named files are read from the archives; nothing else is unpacked.
"""
import glob
import os
import shutil
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "lib")


def copy_member(archive, mode, endswith, dest):
    with tarfile.open(archive, mode) as t:
        for m in t:
            if m.isfile() and m.name.replace("\\", "/").endswith(endswith):
                src = t.extractfile(m)
                with open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                return m.name
    return None


def main(sd, lib=LIB):
    lejos = os.path.join(sd, "lejosimage.bz2")
    ejre = sorted(glob.glob(os.path.join(sd, "ejre-7u60*.tar.gz")))
    if not os.path.isfile(lejos) or not ejre:
        sys.exit(f"Couldn't find lejosimage.bz2 and ejre-7u60*.tar.gz in {sd}")
    os.makedirs(lib, exist_ok=True)
    jobs = [(lejos, "r:bz2", "/ev3classes.jar", "ev3classes.jar"),
            (lejos, "r:bz2", "/usr/share/java/jna-3.2.7.jar", "jna.jar"),  # what the brick's libjna/.../jna.jar links to
            (ejre[0], "r:gz", "/lib/rt.jar", "rt7.jar")]
    for archive, mode, member, name in jobs:
        found = copy_member(archive, mode, member, os.path.join(lib, name))
        print(f"{name:16} {'from ' + found if found else 'NOT FOUND in ' + os.path.basename(archive)}")
        if not found:
            sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(*sys.argv[1:])
