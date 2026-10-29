# Ashton Smokeview Internal Release Guide

This document defines how the Ashton custom Smokeview fork is built, tested,
versioned, packaged, and distributed internally. The current release line is
based on Smokeview 6.11.2. The current test build is `6.11.2-af2-rc6`;
`6.11.2-af1` is the previous tagged release.

## Current Customisation

The fork adds CFD result-review workflows intended to reduce repetitive setup.

| Shortcut | Action |
| --- | --- |
| `Ctrl+X` | Cycle X-minimum, X-maximum, and exterior views |
| `Ctrl+Y` | Cycle Y-minimum, Y-maximum, and exterior views |
| `Ctrl+Z` | Cycle Z-minimum, Z-maximum, and exterior views |
| `Ctrl+I` or `Ctrl+L` | Cycle scalar visibility slices |
| `Ctrl+T` | Cycle scalar temperature slices |
| `Ctrl+V` | Cycle scalar velocity-magnitude slices |
| `Ctrl+P` | Cycle scalar pressure slices |
| `Ctrl+U` | Unload all loaded data and end the active result workflow |

`Ctrl+I` and `Ctrl+L` both select visibility. `Ctrl+I` shares its key code with
TAB, which some window managers and remote-desktop clients (NoMachine/NX among
them) intercept before Smokeview ever receives it; `Ctrl+L` is a collision-free
backup that behaves identically. If both are unresponsive over a remote-desktop
session, tapping `d` and, while still holding it, pressing `i` also triggers
the visibility shortcut — `d` is Smokeview's own sticky-Ctrl key, so this
synthesises the Ctrl modifier with a printable `i` instead of relying on the
raw Ctrl+I key code at all.

Each result shortcut cycles matching planes in X, Y, then Z order. Selecting a
plane loads its slice files, selects the configured colourbar and bounds, clips
at the plane's actual coordinate, selects the matching axis view, and applies a
fitted zoom. The final step turns the workflow off and restores the camera and
clipping state that existed before the workflow started.

The default result mappings are:

| Workflow | Slice label | Colourbar |
| --- | --- | --- |
| Visibility | `VIS_C` | `Visibility` |
| Temperature | `temp` | `Temperature` |
| Velocity | `vel` | `Velocity` |
| Pressure | `pres` | `Pressure` |

The visibility default, `VIS_C`, is matched as a family rather than an exact
string: FDS reports the soot visibility quantity as bare `VIS_C` in most cases,
but as `VIS_C` followed by a simulation-specific extinction-coefficient/soot-
yield suffix (for example `VIS_C0.9H0.1`) when the case sets non-default
visibility constants. The default matches either form. Any other
`RESULTWORKFLOW` label (temp/vel/pres, or a custom override) still requires an
exact match, so this only applies to the visibility default.

Mappings can be overridden with `RESULTWORKFLOW` records in the global or
case-specific INI. A case-specific record takes precedence.

### Adding a new shortcut

All fork shortcuts are dispatched from one place: `HandleResultWorkflowShortcut`
in `Source/smokeview/result_workflow.c`, called from `Keyboard()` in
`Source/smokeview/callbacks.c` *before* Smokeview's own upstream keyboard
switch. Returning `1` consumes the keypress; returning `0` falls through to
upstream handling. `Ctrl+<letter>` arrives as the raw ASCII control code
(1-26), which the function folds back to a lowercase letter before the
`switch`, and `Shift` reverses `direction` for the cycling shortcuts.

**Before picking a letter, check both lists it might collide with:**

- This fork's own bindings (the `switch(lower_key)` in
  `HandleResultWorkflowShortcut`): currently `x y z i l t v p m u`.
- Upstream's own `Ctrl+<letter>` bindings in `callbacks.c`'s main keyboard
  switch: currently `b c C D e g h k m s t w`. Search for
  `case '<letter>':` there, since some (like `k`) test
  `keystate == GLUT_ACTIVE_CTRL` inline rather than through a nested
  `case GLUT_ACTIVE_CTRL:` — a plain grep for `GLUT_ACTIVE_CTRL` will miss
  those.

Because the fork's handler runs first and returns `1` unconditionally when a
letter matches, a fork binding **silently shadows** any upstream `Ctrl+<letter>`
action for that same key, with no warning. This already happens for `m`:
the fork's `FlipWorkflowClipSide` (`Ctrl+M`) and upstream's mesh-highlight
cycling (`callbacks.c`, `case 'm':`, `GLUT_ACTIVE_CTRL` branch) claim the same
key, and the fork's binding always wins. Avoid repeating this by mistake for a
new shortcut — reusing a letter deliberately (as here) is fine, but it should
be a conscious choice, not an accident.

Also avoid `d` and `f`: these are Smokeview's own sticky-Ctrl/sticky-Alt keys
(`callbacks.c:1865`/`1921`), so binding them directly would interact oddly
with that mechanism. Remember the Ctrl+I/TAB collision described above when
choosing a letter likely to be intercepted by a window manager or
remote-desktop client — pick a backup binding up front for anything similarly
exposed, rather than waiting for a report from a remote session.

**To add a new cycling result-review workflow** (a fifth quantity alongside
visibility/temperature/velocity/pressure):

1. Add a value to `enum workflow_type` and bump `NRESULT_WORKFLOWS`.
2. Add a matching entry to each of `workflows[]`, `default_slice_labels[]`,
   `default_colorbar_labels[]`, `default_fixed_mins[]`, and
   `default_fixed_maxs[]`.
3. Add `case '<letter>':` to `HandleResultWorkflowShortcut`'s switch, calling
   `SelectWorkflowPlane(WORKFLOW_<NAME>, apply_clip_view, direction)`.
4. If the quantity should ship with fixed company-default bounds, add a
   `C_SLICE`/`V2_SLICE` record to `Build/for_bundle/smokeview.ini` — see the
   `VIS_C` entries for the format.

**To add a standalone shortcut** unrelated to the cycling workflows, add a
`case '<letter>':` directly to `HandleResultWorkflowShortcut`'s switch,
returning `1` when handled. Only do this for a genuinely new fork-specific
action — never to override an existing upstream Smokeview shortcut, since (per
above) that shadowing happens silently.

**After adding any shortcut:**

- Update the shortcut table above and the matching table in
  `Utilities/Scripts/README.md`, and add it to the acceptance-test checklist
  below.
- Rebuild and test manually with a GLUI dialog window focused, not just the
  main graphics window — this is exactly how the Ctrl+I/TAB collision was
  missed originally — and with Caps Lock both on and off, since the vendored
  GLUT folds Caps Lock into the Shift modifier (see the acceptance-test note
  below), which silently reverses cycling direction or disables a shortcut
  that explicitly rejects Shift.

## Repository Management

The internal repository is:

```text
git@github.com:AshtonDigital/smv.git
```

Changes may be committed directly to the internal release branch without a
pull request if that is the team's agreed process. Keep commits focused and do
not commit generated files from `cbuild/` or packaged release archives.

Before starting release work:

```bash
git status --short --branch
git pull --ff-only
```

Use annotated tags for distributed versions. The tag must match the version
reported by `smokeview -version` and printed in the installer filename:

```bash
git tag -a ashton-smv-v6.11.2-af1 -m "Ashton Smokeview 6.11.2-af1"
git push origin ashton-smv-v6.11.2-af1
```

Only tag a commit after its release package has passed the acceptance tests.

### Pre-release test builds

While a release line is still being iterated on and has not yet been tagged,
set `ASHTON_RELEASE` to that release name with an `-rcN` suffix, for example
`af1-rc1`, `af1-rc2`, and so on for each distributed test build. This keeps
successive test builds distinguishable (in the `-version` banner, the
installer filename, and the embedded checksum) without implying a numbered
release (`af2`) has begun. `ASHTON_RELEASE` is a free-form string, so no other
build or packaging script needs to change to support this.

Once a build passes acceptance testing, drop the `-rcN` suffix (`af1-rc3`
becomes `af1`), rebuild and repackage so the final artefact's embedded version
matches exactly, and only then create the annotated tag. Do not tag an `-rcN`
build. The next release line after a tagged version increments the numbered
suffix as before (`af1` to `af2`, not `af1.1`).

## Configuration Files

Smokeview reads its global configuration from `smokeview.ini` in the detected
Smokeview root directory. For the portable internal package, the executable,
`smokeview.ini`, and `objects.svo` must be placed in the same top-level
directory.

The approved company-default configuration is maintained at:

```text
/home/tomcox/SharedFolder/VMLinux/smokeview.ini
```

`Build/for_bundle/smokeview.ini` is the version-controlled release snapshot of
that file and is packaged on both platforms. The company default is a complete
saved Smokeview configuration, not just a colourbar definition file. Review
changes to it for:

- the standard Smokeview defaults required by the team;
- the five approved company `GCOLORBAR` definitions;
- the approved `V2_SLICE` bounds;
- any required `RESULTWORKFLOW` overrides.

Only ship case-specific camera, input-file, clipping, or display state when the
team has explicitly approved those settings as part of the company default.

## Development Build

Use the persistent ignored build directory for local testing:

```bash
cmake -S . -B cbuild/review \
  -DCMAKE_BUILD_TYPE=Release \
  -DVENDORED_UI_LIBS=ON \
  -DVENDORED_LIBS=OFF

cmake --build cbuild/review --target smokeview -j4
```

For current development testing, place the required resources beside the
executable:

```bash
cp /home/tomcox/SharedFolder/VMLinux/smokeview.ini cbuild/review/smokeview.ini
cp Build/for_bundle/objects.svo cbuild/review/objects.svo
```

Run a representative case with:

```bash
./cbuild/review/smokeview /absolute/path/to/case.smv
```

Do not test by running Smokeview without a case file.

## Release Build

Create a clean release build with the vendored GLUT library linked statically.
This prevents the package from referring to a library inside the developer's
checkout.

For normal releases, use the platform packaging scripts from the repository
root. Linux produces a self-extracting `.sh` installer and Windows produces a
WiX `.msi` installer.

```bash
./scripts/package_release_linux.sh
```

From an x64 Visual Studio Developer PowerShell on Windows, after extracting
the [official portable static ImageMagick archive](https://imagemagick.org/download/):

```powershell
.\scripts\package_release_windows.ps1 -ImageMagickDir "C:\path\to\extracted\ImageMagick"
```

### Build both installers on one Windows workstation

Install and start [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
in **Linux containers** mode. The Windows host needs Visual Studio 2022 C++
build tools, CMake, WiX Toolset 3, Python 3.10+ with Tk and PyInstaller, and
the extracted portable ImageMagick folder described below. Docker builds the
Linux binary in Ubuntu 22.04; Visual Studio and WiX build the MSI on Windows.
Both builds use the same checkout, with separate CMake build directories.

Run this from the repository root in an x64 Visual Studio Developer PowerShell:

```powershell
py -3 -m pip install pyinstaller
.\scripts\package_release_all.ps1 -ImageMagickDir "C:\path\to\extracted\ImageMagick"
```

The script builds and checks both `dist/ashton-smokeview-v<version>-windows-x64.msi`
and `dist/ashton-smokeview-v<version>-linux-x64.sh`, including their `.sha256`
files. It checks that the Linux binary's glibc requirement does not exceed
Ubuntu 22.04's 2.35. The first Docker image build downloads the Ubuntu build
dependencies; later builds reuse the image. The Linux installer still needs to
be tested on a separate Linux machine and the MSI on a separate Windows
machine before distribution.

All three scripts use `Build/for_bundle/smokeview.ini`, the committed snapshot
of the company default. The individual platform scripts accept `--config` or
`-ConfigFile` to test an explicitly selected alternative configuration.

The platform scripts put their installer and a SHA-256 checksum in `dist/`.
They accept `--help`/`Get-Help`-style parameter discovery and can package an existing build
with `--skip-build`/`-SkipBuild`. The Windows package uses the static MSVC
runtime so that installing the Visual C++ Redistributable is not a prerequisite.
Creating the Windows installer also requires WiX Toolset 3 (`heat.exe`,
`candle.exe`, and `light.exe`). The MSI installs for all users under
`%ProgramFiles%\Ashton Digital\Smokeview` and requests administrator elevation;
its numeric Windows Installer
version uses the upstream version, while the full Ashton version appears in
the product name, filename, and packaged `VERSION` file.

The Windows packaging machine also needs Python 3.10+ with PyInstaller
(`py -3 -m pip install pyinstaller`) and an extracted, official ImageMagick
portable Q16 x64 static archive. Pass the folder containing `magick.exe` with
`-ImageMagickDir`. PyInstaller embeds Python and Tk in
the two capture executables; the MSI copies the portable ImageMagick tree
beside them. Installed Windows users do not need separate Python or
ImageMagick installations. The packaged `DEPENDENCIES.txt` records the build
interpreter, PyInstaller version, ImageMagick version and executable checksum.

The camera-and-flame capture icon is authored in
`Utilities/Scripts/capture_logo.svg`; the UI
and Linux desktop launcher use `capture_logo.png`, while the Windows capture
executable embeds `capture_logo.ico`.

The release version combines the upstream Smokeview version with the Ashton
fork release, for example `6.11.2-af1`. Increment `ASHTON_RELEASE` in the root
`CMakeLists.txt` (`af2`, `af3`, and so on) before creating the next release.
The packaging scripts derive the version automatically and reject an installer
whose package version does not match the revision embedded in its executable.

Both installers include the capture engine beside the Smokeview executable.
This keeps the utility matched to the custom build and lets it discover the
installed executable without a `--smokeview` argument. Linux users need Python
3.10 or newer and, unless they use `--no-crop`, ImageMagick. On Ubuntu/Debian,
install it with:

```bash
sudo apt-get install imagemagick
```

The Linux capture window also needs Tkinter (`python3-tk` on Ubuntu/Debian).

On Windows, the installer adds **Capture result slices** to the Start menu and
the `.smv` context menu, and installs `smvhelp.txt` beside `smokeview.exe`.
The window can select a case or search a folder recursively, choose result
quantities and capture times, and set an output folder. It uses a capture logo
and defaults to dark mode. The advanced slice-position control scans selected
cases and passes axis/coordinate selections to Smokeview so only requested
planes are rendered. On Linux, the installer
adds the same window to the desktop menu as `smv-cap-ui` and
installs the `af-smv` and `smv-cap` commands and registers **Capture result
slices** as an `.smv` application under **Open With**. These actions start a
separate automated Smokeview process; an existing interactive window can
remain open.

The Linux installer also installs `smvhelp`, which prints a summary of the
added shortcuts and `smv-cap` options for engineers unfamiliar with the fork —
see `Utilities/Scripts/smv_help.sh` for its source and
`Utilities/Scripts/README.md` for the same content in documentation form.

### Building on the correct Linux version

`scripts/cut_release.sh <ASHTON_RELEASE>` automates everything in this
section: it updates `ASHTON_RELEASE` in `CMakeLists.txt`, runs the Docker/
Ubuntu 22.04 build described below, packages the installer, verifies the
glibc floor, and reports the result — without committing anything. Omit the
argument to be prompted for it interactively. Pass `--skip-build` to
repackage an existing build (only meaningful when `ASHTON_RELEASE` hasn't
changed, since the version is compiled into the binary). The manual steps
below explain what it's doing and remain the reference for troubleshooting.

glibc is backward-compatible but not forward-compatible: a binary built on a
newer Linux distribution requires that distribution's glibc or newer, and fails
on an older one with an error like:

```text
smokeview: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
```

**Always build the release binary on the oldest Linux version you need to
support, never on a newer development machine.** For example, a workstation
running Ubuntu 26.04 (glibc 2.43) cannot produce a binary that runs on a
machine running Ubuntu 22.04 "jammy" (glibc 2.35) — building on jammy itself
(or older) produces a binary that runs on jammy *and* on every newer release.

If the development machine itself runs a newer Ubuntu release than your oldest
supported target, build inside a container matching the target instead of on
the host:

```bash
sudo docker run --rm -it -v "$PWD":/src -w /src ubuntu:22.04 bash
```

(`sudo` is required for a snap-installed Docker, which does not create a
regular `docker` group.) Inside the container:

```bash
apt-get update
apt-get install -y build-essential cmake git \
  freeglut3-dev libx11-dev libxmu-dev libxi-dev libglew-dev libgd-dev libjson-c-dev
```

Ubuntu 22.04's apt `cmake` is 3.22, but this project requires 3.24 or newer
(`CMakeLists.txt:2`). Get a current one with pip instead of apt:

```bash
apt-get install -y python3-pip
pip3 install --upgrade cmake
hash -r
cmake --version
```

Then build and package as normal (see the Release Build steps below); because
`/src` is a bind mount of the repository, `dist/` appears on the host as soon
as packaging finishes, with no extra copy step. Verify the glibc floor before
distributing:

```bash
objdump -T cbuild/release-linux/smokeview | grep GLIBC_ | sed 's/.*GLIBC_//' | sort -uV | tail -1
```

That version must not exceed the oldest supported target's glibc version
(2.35 for Ubuntu 22.04).

The manual commands below document the underlying Linux process and remain
useful for troubleshooting.

```bash
rm -rf cbuild/release-linux

cmake -S . -B cbuild/release-linux \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DVENDORED_UI_LIBS=ON \
  -DVENDORED_LIBS=OFF

cmake --build cbuild/release-linux --target smokeview -j4
```

Inspect the resulting binary before packaging:

```bash
ldd cbuild/release-linux/smokeview
readelf -d cbuild/release-linux/smokeview | grep -E 'RPATH|RUNPATH' || true
```

The output must not contain paths under a developer's home directory or source
checkout. The Linux build will still depend on common system OpenGL, X11, image,
and C/C++ runtime libraries — see "Building on the correct Linux version" above
for why the build host matters, not just the runtime libraries. Test the
package on every supported Linux image.

## Package Layout

The Linux and Windows installers contain equivalent application resources.
The Linux payload has this layout:

```text
ashton-smokeview-v6.11.2-af1-linux-x64/
|-- smokeview
|-- capture_result_slices.py
|-- capture_slices_ui.pyw
|-- smv_planes.py
|-- capture_logo.png
|-- smv_help.sh
|-- smokeview.ini
|-- objects.svo
|-- colorbars/
|-- textures/
|-- README.txt
`-- VERSION
```

This versioned directory name is only the embedded tarball layout and the
installer filename — it identifies which build you're looking at before
installing it. The Linux installer unpacks this payload into a **fixed,
unversioned** directory on disk (`/opt/ashton-smokeview`, or
`$HOME/.local/opt/ashton-smokeview` per-user), the same way most simple
`/opt`-style Linux applications handle upgrades (compare `/opt/google/chrome`,
never `/opt/google/chrome-v128`): an upgrade replaces that directory's
contents in place rather than leaving the previous version's directory behind
as dead weight. The actual installed version is still recorded inside it
(`VERSION`, and `af-smv -version`), just not in the directory name. The
installer also sweeps up any leftover directory from the old
`ashton-smokeview-v<version>` scheme the first time it runs after this change.

The Windows payload uses `smokeview.exe` and also includes
`capture_result_slices.exe` and `capture_result_slices.cmd`, which run the
capture engine with bundled Python, `capture_slices_ui.exe`, which opens the
capture window with bundled Tk, and a private `imagemagick/` directory for
cropping. The source scripts remain beside these executables. `smvhelp.txt`
summarises the result shortcuts and capture
options. `VERSION` contains the release version, Git commit,
build date, platform and compiler. `README.txt` contains the launch and capture
commands, dependency notes, configuration location and support information.

The packaging scripts assemble these payloads automatically. The equivalent
manual Linux staging commands are useful only for troubleshooting:

```bash
version=6.11.2-af1
package="dist/ashton-smokeview-v${version}-linux-x64"

rm -rf "$package"
mkdir -p "$package"
install -m 0755 cbuild/release-linux/smokeview "$package/smokeview"
install -m 0755 Utilities/Scripts/capture_result_slices.py \
  "$package/capture_result_slices.py"
install -m 0644 Build/for_bundle/smokeview.ini "$package/smokeview.ini"
install -m 0644 Build/for_bundle/objects.svo "$package/objects.svo"
cp -R Build/for_bundle/colorbars "$package/colorbars"
cp -R Build/for_bundle/textures "$package/textures"
```

For troubleshooting, create the payload archive directly with:

```bash
tar -C dist -czf "${package}.tar.gz" "$(basename "$package")"
```

The release script performs this staging automatically, embeds the compressed
payload after its installer shell code, and checksums the resulting `.sh` file.

## Acceptance Testing

Use one representative case that contains all required scalar quantities and
X, Y, and Z slice planes. Record the case name and test result with the release.

Verify all of the following before distributing a release:

- Smokeview starts from the installed package without access to the source tree.
- Startup output reports the package directory as `Root directory`.
- Startup output reports the packaged `smokeview.ini` and `objects.svo`.
- Existing important shortcuts still work: `O`, `Alt+V`, `Alt+B`, `Alt+C`,
  `Space`, `1` through `9`, and existing mouse modifiers.
- `Ctrl+X`, `Ctrl+Y`, and `Ctrl+Z` cycle the expected standard views.
- `Ctrl+I`, `Ctrl+T`, `Ctrl+V`, and `Ctrl+P` select the correct scalar quantity.
  Test `Ctrl+I` specifically **with a GLUI dialog window focused**, not just
  the main graphics window — Ctrl+I shares its key code with TAB, which GLUI
  previously intercepted for dialog focus-cycling regardless of the Ctrl
  modifier. `Ctrl+L` selects visibility identically, as a backup binding that
  does not share a key code with any other key.
- With Caps Lock on, `Ctrl+X`, `Ctrl+Y`, `Ctrl+Z`, and `Ctrl+U` do nothing (the
  vendored GLUT folds Caps Lock into the Shift modifier), and `Ctrl+I`/`Ctrl+L`/
  `Ctrl+T`/`Ctrl+V`/`Ctrl+P` cycle backwards instead of forwards. This is
  expected; confirm it does not surprise testers rather than treating it as a
  regression.
- Each result workflow cycles every expected X, Y, and Z plane in order.
- Each selected slice receives the correct colourbar and numeric bounds.
- Clipping uses the selected slice's actual coordinate.
- X and Y slices use the expected side view; Z slices use the top-down view.
- The fitted zoom shows the complete domain and normal zoom controls remain usable.
- Advancing to `off` restores the previous camera and clipping state.
- `Ctrl+U` unloads all data and restores the pre-workflow camera and clipping.
- The installer passes testing on a second machine that has no source checkout.
- The published `.sha256` file validates the installer.
- The installed capture utility reports its bundled Python, Smokeview and
  ImageMagick dependencies clearly before rendering on Windows; the Linux
  package reports system dependencies.
- The capture utility renders, crops and renames all configured result slices.
- Capture can run in a separate automated process while an interactive
  Smokeview window remains open.
- On Windows, double-clicking an `.smv` file opens Ashton Smokeview and the
  **Capture result slices** File Explorer context action opens the window with
  that case selected. The Start menu entry opens the same window with no case.
- The capture window finds all `.smv` files recursively in a selected folder,
  skips unchecked result types, separates captures from multiple requested
  times, and writes beside each case or under a chosen output folder.
- On Linux, `af-smv`, `smv-cap`, `smv-cap-ui` and `smvhelp` are available, an `.smv` file
  opens in Ashton Smokeview by default, and **Open With > Capture result
  slices** works in the desktop file manager.
- On a shared Linux machine installed with `--system`, `af-smv`, `smv-cap` and
  `smvhelp` resolve and run for a **second, non-installing user account**, not
  just the account that ran the installer, and that second user also gets the
  `.smv` **Open With > Capture result slices** entry.

## Publishing Internally

Publish both the installer and its `.sha256` file using one controlled location:

- a release attached to the internal Ashton GitHub repository; or
- a versioned folder in the company SharedFolder; or
- the company's managed internal software repository.

Do not distribute an unversioned installer over an existing release. Keep old
installers available so a team can roll back to the preceding known-good version.

Copy the generated `dist/ashton-smokeview-v<version>-linux-x64.sh` and its
`.sha256` file to the Linux machine. No compiler or WiX tools are needed there.
On Ubuntu/Debian, install any missing runtime packages once for either install
mode (adjust package names for other distributions):

```bash
sudo apt-get install libglew2.2 libgd3 libgl1 libglu1-mesa libxmu6 libx11-6 \
  libxext6 libxt6 imagemagick python3 python3-tk
```

Linux recipients installing only for themselves should make the downloaded
installer executable and run it:

```bash
chmod +x ashton-smokeview-v6.11.2-af2-rc6-linux-x64.sh
./ashton-smokeview-v6.11.2-af2-rc6-linux-x64.sh
```

That installs under `$HOME/.local/opt/ashton-smokeview`, with the
`af-smv`/`smv-cap`/`smv-cap-ui`/`smvhelp`
commands symlinked into `$HOME/.local/bin` and the `.smv` file association set
only for that user.

### Installing for every user on a shared machine

On a shared machine where several people need to run Smokeview and cannot use
sudo themselves, one administrator installs it once for everybody with
`--system`:

```bash
chmod +x ashton-smokeview-v6.11.2-af2-rc6-linux-x64.sh
sudo ./ashton-smokeview-v6.11.2-af2-rc6-linux-x64.sh --system
```

`--system` requires root and installs into `/opt/ashton-smokeview`, symlinks
`af-smv`, `smv-cap`, `smv-cap-ui`, `smvhelp` and a generic `smokeview` into
`/usr/local/bin` (on every user's `PATH` by default), and registers the `.smv`
file association and desktop
entries under `/usr/share` rather than any one user's home directory. It also
sets the
system-wide default `.smv` application directly, since `xdg-mime default` only
ever writes the invoking (root) user's own configuration and cannot set a
machine-wide default on its own. **Do not** run the installer as root without
`--system` — that installs a copy usable only by the root account, under
`/root`, which is invisible and useless to everyone else; the installer prints
a warning if you do this.

One consequence of a root-owned, shared `/opt` install: users cannot save
Smokeview settings back into the packaged `smokeview.ini`, since it is not
writable by them. This has not come up as a problem in practice, since the
approved company default is meant to be used as shipped, but it is worth
knowing if a user reports that "Save Settings" silently fails.

Windows recipients run the `.msi` installer normally. The Linux installer
cannot be used natively on Windows. The combined build command produces both
artifacts on one workstation, but each still needs its own acceptance-test pass.

## Remaining Release Work

The following items still require a team decision or release-specific action:

- approve any additional shortcut behaviour;
- select and retain a representative regression-test case;
- decide the supported Linux distributions and minimum library versions;
- decide whether a separate velocity-vector workflow is required;
- write release notes for each distributed Ashton version;
- perform clean-machine acceptance testing on both platforms;
- select the final commit, build both installers, test them, then create the
  matching annotated tag.

Update this document whenever the shortcut contract, configuration format,
supported platforms, packaging layout, or release process changes.
