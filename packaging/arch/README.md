# Building SomaWave for Arch Linux

Use a fully updated Arch build environment, preferably a clean devtools chroot
with `base-devel`. Build as an unprivileged user. The PKGBUILD declares the
runtime and Python build dependencies. Install missing dependencies through
Pacman in the build environment. Run the following from this directory once
the dependencies, `namcap`, and `desktop-file-utils` are available:

```bash
makepkg --verifysource
makepkg --cleanbuild --clean
package=$(makepkg --packagelist)
namcap PKGBUILD "$package"
desktop-file-validate somawave.desktop somawave-terminal.desktop
pacman -Qip "$package"
pacman -Qlp "$package"
```

Use a public packager identity in the makepkg configuration and a build path
without personal information. Review the archive and its metadata before
distribution. In a disposable Arch environment, verify installation, playback,
desktop launch, upgrade, removal, and reinstallation. Use an isolated XDG
profile to verify that settings, favorites, history, and the cache survive.

For each release, update `pkgver`, reset `pkgrel` to 1, and verify the versioned
GitHub source distribution against that release's manifest before recording its
SHA-256 in the PKGBUILD. Verify packaging file checksums after any launcher
changes. Increase `pkgrel` for packaging-only revisions.

Copy the validated package to the permanent release directory. From that
directory:

```bash
package=somawave-1.0.1-1-any.pkg.tar.zst  # Match the version just built.
sha256sum "$package" > SHA256SUMS-arch
sha256sum -c SHA256SUMS-arch
```
