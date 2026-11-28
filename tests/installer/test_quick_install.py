"""Quick-install integration tests. All writes and package operations are isolated."""

import errno
import hashlib
import io
import json
import os
import pty
import select
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[2] / "install.sh"
BASE = "https://github.com/StaleUser0101/SomaWave/releases/download"
TAG = "v4.5.6"
PACKAGE = "somawave-4.5.6-2-any.pkg.tar.zst"
ARCHIVE = "SomaWave-4.5.6-linux.tar.gz"
SYSTEM_PYTHON = subprocess.check_output(
    ["/usr/bin/python3", "-I", "-c", 'import sys; print("%d.%d" % sys.version_info[:2])'],
    text=True,
).strip()

MOCK = r'''
import os
import re
import shutil
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
fixture = Path(os.environ["FIXTURE"])
with (fixture / "calls").open("a") as log:
    print(name, *args, file=log)

if name == "uname":
    print(os.environ.get("KERNEL", "Linux") if args == ["-s"] else "x86_64")
elif name == "cat":
    assert args == ["/etc/os-release"], args
    print((fixture / "os-release").read_text(), end="")
elif name == "curl":
    assert args[0] == "--disable"
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--proto-redir") + 1] == "=https"
    url = args[-1]
    assert url.startswith("https://")
    output = Path(args[args.index("--output") + 1])
    asset = url.rsplit("/", 1)[-1]
    if asset == os.environ.get("FAIL_ASSET"):
        output.write_text("interrupted")
        print(os.environ.get("FAIL_STATUS", "000"), end="")
        sys.exit(22)
    shutil.copyfile(fixture / asset, output)
    print("200", end="")
elif name == "pacman":
    if args == ["-Q", "somawave"]:
        database = fixture / "native"
        if not database.exists():
            sys.exit(1)
        print("somawave", database.read_text())
    else:
        assert args[0] == "-Qp"
        match = re.fullmatch(r"somawave-(.+)-any\.pkg\.tar\.zst", Path(args[1]).name)
        print("somawave", match[1])
elif name == "bsdtar":
    assert args[0] == "-tf"
    print("usr/lib/python" + os.environ["PACKAGE_PYTHON"] +
          "/site-packages/somawave/__init__.py")
elif name == "vercmp":
    def version(value):
        return tuple(map(int, re.split(r"[.-]", value)))
    installed, available = map(version, args)
    print((installed > available) - (installed < available))
elif name == "sudo":
    assert args[:3] == ["pacman", "-U", "--"]
    assert sys.stdin.isatty()
    if os.environ.get("FAIL_PACMAN"):
        sys.exit(1)
    (fixture / "native").write_text("4.5.6-2")
elif name == "mpv":
    raise AssertionError("Quick install must never launch MPV")
else:
    raise AssertionError(name)
'''

STANDALONE_INSTALL = """#!/bin/bash
set -eu
printf 'install\n' >> "$FIXTURE/standalone-calls"
"""
STANDALONE_UNINSTALL = (INSTALLER.parent / "scripts/uninstall.sh").read_text() + """
printf 'uninstall\n' >> "$FIXTURE/standalone-calls"
"""


@unittest.skipUnless(os.geteuid() != 0, "Quick install requires an unprivileged user")
class QuickInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Path(temporary.name)
        self.scratch = self.fixture / "tmp"
        self.home = self.fixture / "home"
        self.commands = self.fixture / "commands"
        for path in (self.scratch, self.home, self.commands):
            path.mkdir()
        self.env = {
            "PATH": str(self.commands),
            "FIXTURE": str(self.fixture),
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.home / "test data"),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "TMPDIR": str(self.scratch),
            "PACKAGE_PYTHON": SYSTEM_PYTHON,
            "LC_ALL": "C",
        }
        for name in ("bash", "sha256sum", "mktemp", "rm", "rmdir", "install",
                     "dirname", "chmod", "mv"):
            self.commands.joinpath(name).symlink_to("/usr/bin/" + name)
        self.commands.joinpath("python3").symlink_to(sys.executable)
        for name in ("uname", "cat", "curl", "pacman", "vercmp", "bsdtar", "sudo", "mpv"):
            command = self.commands / name
            command.write_text(f"#!{sys.executable}\n" + MOCK)
            command.chmod(0o755)
        self.set_distro("cachyos", "arch")
        self.fixture.joinpath(PACKAGE).write_bytes(b"native package fixture")
        with tarfile.open(self.fixture / ARCHIVE, "w:gz") as archive:
            for script, contents in (("install", STANDALONE_INSTALL), ("uninstall", STANDALONE_UNINSTALL)):
                data = contents.encode()
                info = tarfile.TarInfo(f"SomaWave-4.5.6/scripts/{script}.sh")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        for asset, manifest in ((PACKAGE, "SHA256SUMS-arch"), (ARCHIVE, "SHA256SUMS")):
            digest = hashlib.sha256(self.fixture.joinpath(asset).read_bytes()).hexdigest()
            self.fixture.joinpath(manifest).write_text(f"{digest}  {asset}\n")
        self.release = {
            "tag_name": TAG, "draft": False, "prerelease": False,
            "assets": [
                {"name": name, "state": "uploaded", "browser_download_url": f"{BASE}/{TAG}/{name}"}
                for name in (PACKAGE, ARCHIVE, "SHA256SUMS", "SHA256SUMS-arch")
            ],
        }

    def set_distro(self, name, like=""):
        self.fixture.joinpath("os-release").write_text(
            f'ID={name}\nID_LIKE="{like}"\nPRETTY_NAME="{name} test"\n'
        )

    def seed_standalone(self, version="4.5.5"):
        self.data = Path(self.env["XDG_DATA_HOME"])
        venv = self.data / "somawave/venv"
        (venv / f"lib/python{SYSTEM_PYTHON}/site-packages/somawave-{version}.dist-info").mkdir(parents=True)
        (venv / "bin").mkdir()
        (venv / "bin/python").symlink_to(sys.executable)
        self.wrapper = self.home / ".local/bin/somawave"
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_bytes(subprocess.check_output(
            ["/usr/bin/bash", "-c", '''printf '#!/usr/bin/env bash\nexec %q -m somawave "$@"\n' "$1"''',
             "bash", str(venv / "bin/python")]
        ))
        self.settings = Path(self.env["XDG_CONFIG_HOME"]) / "somawave/settings.json"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"favorites": ["a"], "recent": ["b"]}')
        self.cache = Path(self.env["XDG_CACHE_HOME"]) / "somawave/stations.json"
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text('["stations"]')

    def run_install(self, *, answer="y", piped=False, interactive=True, code=0):
        self.fixture.joinpath("latest").write_text(json.dumps(self.release))
        command = ["/usr/bin/bash", str(INSTALLER)]
        if piped:
            command = ["/usr/bin/bash", "-o", "pipefail", "-c",
                       '/usr/bin/cat "$1" | /usr/bin/bash', "bash", str(INSTALLER)]
        if not interactive:
            process = subprocess.run(command, env=self.env, start_new_session=True, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            status, output = process.returncode, process.stdout
        else:
            pid, master = pty.fork()
            if pid == 0:
                os.execve(command[0], command, self.env)
            output = b""
            sent = False
            deadline = time.monotonic() + 10
            try:
                while True:
                    ready, _, _ = select.select([master], [], [], max(0, deadline - time.monotonic()))
                    if not ready:
                        self.fail(f"Installer timed out. Output: {output!r}")
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break
                    if not chunk:
                        break
                    output += chunk
                    if not sent and b"[y/N]" in output:
                        os.write(master, answer.encode() + b"\n")
                        sent = True
            except BaseException:
                os.killpg(pid, signal.SIGKILL)
                raise
            finally:
                os.close(master)
                status = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
        output = output.decode()
        self.assertEqual(status, code, output)
        self.assertEqual(list(self.scratch.iterdir()), [], output)
        return output

    def assert_no_changes(self):
        self.assertFalse(self.fixture.joinpath("native").exists())
        self.assertFalse(self.fixture.joinpath("standalone-calls").exists())
        calls = self.fixture / "calls"
        if calls.exists():
            self.assertNotIn("sudo ", calls.read_text())

    def test_fresh_native_install(self):
        output = self.run_install()
        self.assertIn(f"{PACKAGE}: OK", output)
        self.assertIn("/usr/bin/somawave", output)
        self.assertEqual(self.fixture.joinpath("native").read_text(), "4.5.6-2")

    def test_upgrade_native_package_revision(self):
        self.fixture.joinpath("native").write_text("4.5.6-1")
        self.assertIn("Installed (native): 4.5.6-1", self.run_install())
        self.assertEqual(self.fixture.joinpath("native").read_text(), "4.5.6-2")

    def test_already_current_native(self):
        self.fixture.joinpath("native").write_text("4.5.6-2")
        self.assertIn("latest version is already installed", self.run_install(interactive=False))
        self.assertNotIn("sudo ", self.fixture.joinpath("calls").read_text())

    def test_already_current_standalone(self):
        self.set_distro("ubuntu", "debian")
        self.seed_standalone("4.5.6")
        self.assertIn("latest version is already installed", self.run_install(interactive=False))
        self.assert_no_changes()

    def test_standalone_upgrade(self):
        self.set_distro("ubuntu", "debian")
        self.seed_standalone()
        self.assertIn("Installed (standalone): 4.5.5", self.run_install())
        self.assertEqual(self.fixture.joinpath("standalone-calls").read_text(), "install\n")
        self.assertTrue(self.wrapper.exists())

    def test_migrate_standalone(self):
        self.seed_standalone()
        output = self.run_install()
        self.assertIn("remove the standalone installation", output)
        self.assertIn(f"{ARCHIVE}: OK", output)
        self.assertEqual(self.fixture.joinpath("standalone-calls").read_text(), "uninstall\n")
        self.assertTrue(self.fixture.joinpath("native").exists())
        self.assertFalse(self.wrapper.exists())
        self.assertFalse((self.data / "somawave/venv").exists())
        self.assertEqual(self.settings.read_text(), '{"favorites": ["a"], "recent": ["b"]}')
        self.assertEqual(self.cache.read_text(), '["stations"]')

    def test_finish_migration_when_native_is_already_current(self):
        self.seed_standalone()
        self.fixture.joinpath("native").write_text("4.5.6-2")
        self.run_install()
        self.assertFalse(self.wrapper.exists())
        self.assertNotIn("sudo ", self.fixture.joinpath("calls").read_text())

    def test_failed_native_install_preserves_standalone(self):
        self.seed_standalone()
        self.env["FAIL_PACMAN"] = "1"
        self.assertIn("Pacman installation failed", self.run_install(code=1))
        self.assertTrue(self.wrapper.exists())
        self.assertFalse(self.fixture.joinpath("standalone-calls").exists())

    def test_non_arch_with_pacman_on_path(self):
        self.set_distro("fedora")
        output = self.run_install()
        self.assertIn("standalone (per user)", output)
        self.assertIn(f"{ARCHIVE}: OK", output)
        self.assertEqual(self.fixture.joinpath("standalone-calls").read_text(), "install\n")
        self.assertFalse(self.fixture.joinpath("native").exists())

    def test_unsupported_operating_system(self):
        self.env["KERNEL"] = "Darwin"
        self.assertIn("requires Linux", self.run_install(code=1))
        self.assert_no_changes()

    def test_python_mismatch(self):
        self.env["PACKAGE_PYTHON"] = "3.99"
        self.assertIn("requires Python 3.99", self.run_install(code=1))
        self.assert_no_changes()

    def test_missing_dependency(self):
        self.set_distro("debian")
        self.commands.joinpath("mpv").unlink()
        self.assertIn("Missing required command: mpv", self.run_install(code=1))
        self.assert_no_changes()

    def test_download_failure(self):
        self.env["FAIL_ASSET"] = PACKAGE
        self.assertIn("Download failed", self.run_install(code=1))
        self.assert_no_changes()

    def test_invalid_checksum(self):
        self.fixture.joinpath(PACKAGE).write_bytes(b"changed after publishing")
        self.assertIn("Checksum verification failed", self.run_install(code=1))
        self.assert_no_changes()

    def test_missing_release_asset(self):
        self.release["assets"].pop()
        self.assertIn("missing or invalid release asset: SHA256SUMS-arch", self.run_install(code=1))
        self.assert_no_changes()

    def test_api_failure(self):
        self.env.update(FAIL_ASSET="latest", FAIL_STATUS="429")
        self.assertIn("rate-limited", self.run_install(code=1))
        self.assert_no_changes()

    def test_reject_prerelease(self):
        self.release["prerelease"] = True
        self.assertIn("expected a stable", self.run_install(code=1))
        self.assert_no_changes()

    def test_reject_external_asset_url(self):
        self.release["assets"][0]["browser_download_url"] = "https://example.org/package"
        self.assertIn("missing or invalid release asset", self.run_install(code=1))
        self.assert_no_changes()

    def test_cancelled_migration(self):
        self.seed_standalone()
        self.assertIn("Installation cancelled", self.run_install(answer="n"))
        self.assertTrue(self.wrapper.exists())
        self.assert_no_changes()

    def test_interrupt_cleans_temporary_files(self):
        self.run_install(answer="\x03", code=130)
        self.assert_no_changes()

    def test_piped_bash_with_interactive_confirmation(self):
        self.assertIn("SomaWave v4.5.6 is ready", self.run_install(piped=True))

    def test_confirmation_requires_a_terminal(self):
        self.assertIn("interactive terminal is required", self.run_install(piped=True, interactive=False, code=1))
        self.assert_no_changes()

    def test_unknown_standalone_wrapper(self):
        self.seed_standalone()
        self.wrapper.write_text("unknown local app")
        self.assertIn("Unrecognized user-local", self.run_install(code=1))
        self.assert_no_changes()


if __name__ == "__main__":
    unittest.main()
