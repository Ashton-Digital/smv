# Ashton Smokeview 6.11.2-af2

**Release status:** candidate until the Linux and Windows installers pass the
acceptance checks in [ASHTON_INTERNAL_RELEASE.md](ASHTON_INTERNAL_RELEASE.md).
The only previously published Ashton release is `6.11.2-af1`.

## Changes since af1

- Added a compact PySide6 **Capture result slices** window for a single `.smv`
  case or a recursive folder job. It supports result types, multiple capture
  times, optional output location, cropping, overwrite, and cancellation.
- Added per-case X/Y/Z slice controls and extra clip views with independent
  slice and clip coordinates and Min/Max view direction. Jobs can be saved and
  reloaded as JSON. Folder jobs can apply one case's advanced settings to all
  cases and then adjust individual cases.
- Added an **Open captures** action. A successful capture with one output
  folder opens it automatically; multi-output jobs offer a folder chooser.
- A chosen output folder receives PNGs directly. Case and time identifiers in
  filenames keep batch captures separate without creating nested folders.
- Added a per-machine Windows MSI with the capture UI, bundled Python and
  ImageMagick, Start menu and desktop shortcuts, `.smv` integration, and help.
- Added a Linux installer with the same capture UI, desktop integration,
  command launchers, and help. It is built in Ubuntu 22.04 for compatibility
  with that release and newer distributions.
- Both installers include the company `smokeview.ini` with five custom
  colourbars and the CSV colourbar directory beside Smokeview.

## Deployment notes

Windows users need the x64 MSI and administrator installation rights. Linux
users need a graphical desktop, Python 3.10 or newer for the capture engine,
and ImageMagick for automatic cropping. See the release guide for commands,
additional Linux runtime libraries, and system-wide installation steps.

The Windows MSI uses `6.11.2` as its numeric Windows Installer version for
all Ashton revisions based on Smokeview 6.11.2. Test replacement of any
pre-release installation before deployment. A VMware SVGA 3D failure can
fall back to software rendering on either platform and slow Smokeview.

## Acceptance before publication

- Build both installers from the same clean `release/6.11.2-af2` commit and
  verify each `.sha256` file and packaged `VERSION` record.
- Install and exercise the MSI on a clean Windows machine, including the
  desktop shortcut, custom colourbars, and a real capture.
- Install and exercise the Linux package on a clean target machine, including
  the desktop entry, custom colourbars, and a real capture.
- Exercise a representative case with X, Y and Z planes, multiple times,
  clip offsets, folder mode, output-folder opening, and cancellation.
- Create and push the annotated `ashton-smv-v6.11.2-af2` tag only after these
  checks pass.
