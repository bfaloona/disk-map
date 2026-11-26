"""Create a fake Mac-like home folder with large (preallocated) files for testing.

Usage: python3 tests/make_test_home.py /home/tester
Put it under /home/<name> (Linux) or /Users/<name> (macOS) so the advice rules see a home folder.
Files are preallocated, not written, so this is fast but does reserve about 18 GB of disk.
"""
import os, random, subprocess, sys, time

MB = 1 << 20


def make(home):
    random.seed(7)

    def f(path, size, age_days=0):
        p = os.path.join(home, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if size >= MB:
            if sys.platform == 'darwin':
                subprocess.run(['mkfile', '-n', str(size), p], check=True)
            else:
                subprocess.run(['fallocate', '-l', str(size), p], check=True)
        else:
            with open(p, 'wb') as fh:
                fh.write(b'x' * size)
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(p, (t, t))

    f('Downloads/Xcode_16.xip', 900 * MB, 400)
    f('Downloads/docker-desktop.dmg', 620 * MB, 200)
    f('Downloads/old-project-export.zip', 310 * MB, 800)
    for i in range(40):
        f('Downloads/photo-%02d.jpg' % i, random.randint(2, 9) * MB, random.randint(5, 900))
    f('Movies/Trip 2023/A001_raw.mov', 1400 * MB, 900)
    f('Movies/Trip 2023/A002_raw.mov', 800 * MB, 900)
    f('Movies/DaVinci/CacheClip/cache01.dvcc', 450 * MB, 30)
    f('Documents/taxes/2023.pdf', 4 * MB, 500)
    f('Documents/notes.md', 2000, 2)
    f('Pictures/Photos Library.photoslibrary/originals/0/a.heic', 700 * MB, 100)
    f('Pictures/Photos Library.photoslibrary/database/Photos.sqlite', 120 * MB, 1)
    f('Library/Caches/com.apple.Safari/cache.db', 380 * MB, 3)
    f('Library/Caches/ms-playwright/chromium-1200/chrome', 420 * MB, 60)
    f('Library/Caches/Homebrew/downloads/qt.tar.gz', 260 * MB, 90)
    f('Library/Developer/Xcode/DerivedData/App-abc/Build/big.o', 1100 * MB, 10)
    f('Library/Developer/CoreSimulator/Devices/UUID1/data/disk.img', 900 * MB, 300)
    f('Library/Application Support/MobileSync/Backup/00008030/Manifest.db', 1300 * MB, 450)
    f('Library/Application Support/Code/CachedData/x.bin', 90 * MB, 20)
    f('Library/Application Support/Slack/storage.db', 70 * MB, 1)
    f('Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw', 2300 * MB, 1)
    f('Library/Mobile Documents/com~apple~CloudDocs/big.key', 150 * MB, 40)
    f('Library/Keychains/login.keychain-db', 300 * 1024, 1)
    f('.npm/_cacache/content-v2/sha512/aa/blob', 340 * MB, 15)
    f('.ollama/models/blobs/sha256-llama3', 1900 * MB, 120)
    f('.rustup/toolchains/stable-aarch64/lib/librustc.dylib', 500 * MB, 200)
    f('.claude-worktrees/site/feature-x/README.md', 5000, 12)
    f('.ssh/id_ed25519', 400, 700)
    f('.Trash/old-vm.vmdk', 650 * MB, 25)
    for proj in ('web-app', 'api-server', 'old-site'):
        f('dev/%s/package.json' % proj, 800, 30)
        f('dev/%s/.git/objects/pack/pack-1.pack' % proj, random.randint(40, 200) * MB, 30)
        for i in range(300):
            f('dev/%s/node_modules/pkg%03d/index.js' % (proj, i), random.randint(1000, 60000), 300)
        f('dev/%s/node_modules/esbuild/bin/esbuild' % proj, 180 * MB, 300)
        f('dev/%s/src/app.ts' % proj, 9000, 4)
    f('dev/rusty/Cargo.toml', 300)
    f('dev/rusty/target/debug/rusty', 700 * MB, 50)
    f('dev/model/weights.safetensors', 480 * MB, 80)
    # awkward names: must display as text, never run as markup
    f('weird/<img src=x onerror=window.__xss=1>.mov', 30 * MB)
    f('weird/quote"and\'apos`tick.zip', 37 * MB)
    f('weird/new\nline.dmg', 44 * MB)
    f('weird/percent%20and#hash?.pkg', 51 * MB)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dest = os.path.abspath(sys.argv[1])
    if os.path.exists(dest) and os.listdir(dest):
        sys.exit('%s already exists and is not empty; leaving it alone' % dest)
    make(dest)
    print('created', dest)
