#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Build Smokeview and create a self-extracting Linux installer.

Usage:
  scripts/package_release_linux.sh [options]

Options:
  --version VERSION     Package version (default: version from CMakeLists.txt)
  --config FILE         Release smokeview.ini (default: Build/for_bundle/smokeview.ini)
  --build-dir DIR       CMake build directory (default: cbuild/release-linux)
  --output-dir DIR      Package output directory (default: dist)
  --skip-build          Package an existing release build
  -h, --help            Show this help

Relative paths are resolved from the repository root.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

version=""
config_file="Build/for_bundle/smokeview.ini"
build_dir="cbuild/release-linux"
output_dir="dist"
skip_build=0

while (($# > 0)); do
  case "$1" in
    --version)
      (($# >= 2)) || fail "--version requires a value"
      version="$2"
      shift 2
      ;;
    --config)
      (($# >= 2)) || fail "--config requires a value"
      config_file="$2"
      shift 2
      ;;
    --build-dir)
      (($# >= 2)) || fail "--build-dir requires a value"
      build_dir="$2"
      shift 2
      ;;
    --output-dir)
      (($# >= 2)) || fail "--output-dir requires a value"
      output_dir="$2"
      shift 2
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || fail "this script must be run on Linux"

absolute_from_root() {
  local path="$1"
  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s/%s\n' "$repo_root" "$path"
  fi
}

config_file="$(absolute_from_root "$config_file")"
build_dir="$(absolute_from_root "$build_dir")"
output_dir="$(absolute_from_root "$output_dir")"

if [[ -z "$version" ]]; then
  upstream_version="$(sed -nE 's/.*project\(smv .*VERSION ([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' "$repo_root/CMakeLists.txt" | head -n 1)"
  ashton_release="$(sed -nE 's/.*set\(ASHTON_RELEASE "([^"]+)"\).*/\1/p' "$repo_root/CMakeLists.txt" | head -n 1)"
  [[ -n "$upstream_version" ]] || fail "could not determine the upstream Smokeview version from CMakeLists.txt"
  [[ -n "$ashton_release" ]] || fail "could not determine the Ashton release from CMakeLists.txt"
  version="${upstream_version}-${ashton_release}"
fi
version="${version#v}"
[[ "$version" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] || fail "invalid version: $version"

[[ -f "$config_file" ]] || fail "configuration file not found: $config_file"
[[ -f "$repo_root/Build/for_bundle/.smokeview_bin" ]] || fail ".smokeview_bin is missing"
[[ -f "$repo_root/Build/for_bundle/objects.svo" ]] || fail "objects.svo is missing"
[[ -f "$repo_root/Utilities/Scripts/capture_result_slices.py" ]] || fail "capture_result_slices.py is missing"
[[ -f "$repo_root/Utilities/Scripts/capture_slices_ui.pyw" ]] || fail "capture_slices_ui.pyw is missing"
[[ -f "$repo_root/Utilities/Scripts/smv_planes.py" ]] || fail "smv_planes.py is missing"
[[ -f "$repo_root/Utilities/Scripts/capture_logo.png" ]] || fail "capture_logo.png is missing"
[[ -f "$repo_root/Utilities/Scripts/smv_help.sh" ]] || fail "smv_help.sh is missing"
[[ -d "$repo_root/Build/for_bundle/colorbars" ]] || fail "colorbars directory is missing"
[[ -d "$repo_root/Build/for_bundle/textures" ]] || fail "textures directory is missing"

if ((skip_build == 0)); then
  cmake -S "$repo_root" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DVENDORED_UI_LIBS=ON \
    -DVENDORED_LIBS=OFF
  cmake --build "$build_dir" --target smokeview --parallel
fi

binary="$build_dir/smokeview"
[[ -x "$binary" ]] || fail "release executable not found: $binary"

binary_version="$("$binary" -version 2>&1 | sed -nE 's/^Revision[[:space:]]*:[[:space:]]*//p' | head -n 1)"
[[ -n "$binary_version" ]] || fail "could not read the revision from the release executable"
if [[ "$binary_version" != "$version" ]]; then
  fail "package version $version does not match executable revision $binary_version; rebuild after updating ASHTON_RELEASE in CMakeLists.txt"
fi

if ldd "$binary" | grep -q 'not found'; then
  ldd "$binary" >&2
  fail "the release executable has unresolved shared-library dependencies"
fi

if command -v readelf >/dev/null 2>&1; then
  runtime_paths="$(readelf -d "$binary" 2>/dev/null | grep -E 'RPATH|RUNPATH' || true)"
  if [[ "$runtime_paths" == *"$repo_root"* ]]; then
    echo "$runtime_paths" >&2
    fail "the release executable contains a runtime path into the source checkout"
  fi
fi

case "$(uname -m)" in
  x86_64) architecture="x64" ;;
  aarch64|arm64) architecture="arm64" ;;
  *) architecture="$(uname -m)" ;;
esac

package_name="ashton-smokeview-v${version}-linux-${architecture}"
mkdir -p "$output_dir"
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/smv-package.XXXXXX")"
trap 'rm -rf -- "$stage_root"' EXIT
package_dir="$stage_root/$package_name"
mkdir -p "$package_dir"

install -m 0755 "$binary" "$package_dir/smokeview"
install -m 0755 "$repo_root/Utilities/Scripts/capture_result_slices.py" "$package_dir/capture_result_slices.py"
install -m 0755 "$repo_root/Utilities/Scripts/capture_slices_ui.pyw" "$package_dir/capture_slices_ui.pyw"
install -m 0644 "$repo_root/Utilities/Scripts/smv_planes.py" "$package_dir/smv_planes.py"
install -m 0644 "$repo_root/Utilities/Scripts/capture_logo.png" "$package_dir/capture_logo.png"
install -m 0755 "$repo_root/Utilities/Scripts/smv_help.sh" "$package_dir/smv_help.sh"
install -m 0644 "$config_file" "$package_dir/smokeview.ini"
install -m 0644 "$repo_root/Build/for_bundle/.smokeview_bin" "$package_dir/.smokeview_bin"
install -m 0644 "$repo_root/Build/for_bundle/objects.svo" "$package_dir/objects.svo"
cp -R "$repo_root/Build/for_bundle/colorbars" "$package_dir/colorbars"
cp -R "$repo_root/Build/for_bundle/textures" "$package_dir/textures"

commit="$(git -C "$repo_root" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
dirty="no"
if [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
  dirty="yes"
fi
compiler="$(sed -nE 's/^CMAKE_C_COMPILER(:FILEPATH|:STRING)?=//p' "$build_dir/CMakeCache.txt" | head -n 1)"
compiler="${compiler:-unknown}"

cat > "$package_dir/VERSION" <<EOF
Version: v${version}
Git commit: ${commit}
Git working tree dirty: ${dirty}
Build date: $(date -u +'%Y-%m-%dT%H:%M:%SZ')
Platform: Linux ${architecture}
Compiler: ${compiler}
EOF

cat > "$package_dir/README.txt" <<'EOF'
Ashton Smokeview
================

Keep this directory together. Run Smokeview with an absolute path to a case:

  ./smokeview /absolute/path/to/case.smv

Capture every configured result-review slice with:

  ./capture_result_slices.py /absolute/path/to/case.smv --overwrite

Open the capture window with:

  ./capture_slices_ui.pyw

The window opens in dark mode. Its advanced slice-position control scans a
case or folder and can limit captures to positions such as Y=3 or Y=5.

After installation, the equivalent commands are:

  af-smv /absolute/path/to/case.smv
  smv-cap /absolute/path/to/case.smv
  smv-cap-ui

Run smvhelp for a summary of the added shortcuts and smv-cap options.

Desktop users can right-click an .smv file and choose
Open With > Capture result slices.

The packaged smokeview.ini and objects.svo files are loaded from this directory.
The capture utility requires Python 3.10 or newer and, unless --no-crop is used,
ImageMagick (either the "magick" or the "convert" command). On Ubuntu/Debian,
install it with:

  sudo apt-get install imagemagick

The capture window also needs Tkinter (python3-tk on Ubuntu/Debian).

It launches a separate automated Smokeview process, so an interactive Smokeview
window may remain open while capture runs.
Contact the Ashton Digital internal support channel for help with this build.
EOF

payload_path="$stage_root/$package_name.tar.gz"
installer_path="$output_dir/$package_name.sh"
checksum_path="$installer_path.sha256"
tar -C "$stage_root" -czf "$payload_path" "$package_name"

cat > "$installer_path" <<EOF
#!/usr/bin/env bash

set -Eeuo pipefail

package_name='$package_name'
version='$version'
EOF

cat >> "$installer_path" <<'EOF'

usage() {
  cat <<USAGE
Install Ashton Smokeview ${version} for Linux.

Usage:
  ./$(basename "$0") [options]

Options:
  --target DIR       Installation directory
                     (default: $HOME/.local/opt/ashton-smokeview, or
                     /opt/ashton-smokeview with --system)
  --system           Install for all users: /opt, /usr/local/bin and
                     /usr/share instead of the per-user \$HOME defaults.
                     Requires root. Implies --yes.
  --extract FILE     Extract the embedded tar.gz without installing
  --yes              Accept the default installation directory
  -h, --help         Show this help
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

# A permissive umask so a root --system install leaves the package readable
# and traversable by every user, regardless of the invoking shell's umask.
umask 022

# The install directory is fixed and unversioned (like /opt/google/chrome,
# not /opt/google/chrome-v128), so an upgrade overwrites it in place instead
# of leaving the previous version's directory as permanent dead weight. The
# actual installed version is still recorded inside it (VERSION, and
# `-version`'s output), just not in the directory name. package_name (the
# installer filename and embedded tarball layout) stays fully versioned.
install_dir_name="ashton-smokeview"

target=""
extract_file=""
accept_default=0
system_install=0

while (($# > 0)); do
  case "$1" in
    --target)
      (($# >= 2)) || fail "--target requires a directory"
      target="$2"
      shift 2
      ;;
    --system)
      system_install=1
      accept_default=1
      shift
      ;;
    --extract)
      (($# >= 2)) || fail "--extract requires a filename"
      extract_file="$2"
      shift 2
      ;;
    --yes)
      accept_default=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

payload_line="$(awk '/^__SMV_PAYLOAD_FOLLOWS__$/ { print NR + 1; exit }' "$0")"
[[ -n "$payload_line" ]] || fail "embedded archive marker not found"

if [[ -n "$extract_file" ]]; then
  if [[ -e "$extract_file" ]]; then
    fail "refusing to overwrite existing file: $extract_file"
  fi
  tail -n +"$payload_line" "$0" > "$extract_file"
  echo "Extracted $extract_file"
  exit 0
fi

if ((system_install == 1)) && [[ "$EUID" -ne 0 ]]; then
  fail "--system requires root; re-run with sudo"
fi
if ((system_install == 0)) && [[ "$EUID" -eq 0 ]]; then
  echo "Warning: running as root without --system installs only for the root" >&2
  echo "account (under /root), which other users cannot use. Pass --system to" >&2
  echo "install for all users under /opt, /usr/local/bin and /usr/share instead." >&2
fi

if ((system_install == 1)); then
  default_target="/opt/$install_dir_name"
  link_dir="/usr/local/bin"
  data_home="/usr/share"
  config_home="/root/.config"
else
  default_target="$HOME/.local/opt/$install_dir_name"
  link_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
  data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
  config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
fi

if [[ -z "$target" ]]; then
  target="$default_target"
  if ((accept_default == 0)); then
    if [[ -t 0 ]]; then
      echo "Ashton Smokeview v${version}"
      echo
      read -r -p "Installation directory [$default_target]: " answer
      target="${answer:-$default_target}"
    else
      echo "Non-interactive session: using default installation directory $default_target"
    fi
  fi
fi

if [[ -e "$target" && ! -d "$target" ]]; then
  fail "installation target exists and is not a directory: $target"
fi

# A pre-existing target is only ever replaced if it looks like one of our own
# prior installs (carries the .smokeview_bin marker every payload ships) or
# is empty; otherwise refuse rather than silently overwrite unrelated data.
replacing_existing=0
if [[ -e "$target" ]]; then
  if [[ -f "$target/.smokeview_bin" ]]; then
    replacing_existing=1
  elif [[ -n "$(ls -A "$target" 2>/dev/null)" ]]; then
    fail "installation target already exists and does not look like a prior Ashton Smokeview install (missing .smokeview_bin): $target"
  fi
fi

# The install directory used to embed the version (ashton-smokeview-v<ver>),
# so upgrading left the previous version's directory behind, orphaned, next
# to the new one. Sweep up any such sibling now that the directory is fixed.
# Only ever remove one that carries our own marker file.
target_parent="$(dirname "$target")"
for old_dir in "$target_parent"/ashton-smokeview-v*; do
  [[ -d "$old_dir" ]] || continue
  [[ -f "$old_dir/.smokeview_bin" ]] || continue
  echo "Removing superseded install: $old_dir"
  rm -rf -- "$old_dir"
done

success=0
temporary_dir=""
staging_dir="${target}.installing.$$"
target_owned=0

cleanup() {
  rm -rf -- "$temporary_dir"
  rm -rf -- "$staging_dir"
  if ((success == 0 && target_owned == 1)); then
    rm -rf -- "$target"
  fi
}
trap cleanup EXIT INT TERM

temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/ashton-smokeview-install.XXXXXX")"
tail -n +"$payload_line" "$0" | tar -xz -C "$temporary_dir"

# Assemble the new install fully in a staging directory next to $target
# before touching anything, then swap it into place with mv -- a single
# rename syscall on the same filesystem, as close to atomic as a plain shell
# script can manage. This keeps the window where neither version is usable
# down to that one step, rather than the whole copy, so an interrupted
# upgrade can't as easily leave nothing installed at all.
rm -rf -- "$staging_dir"
mkdir -p "$staging_dir"
cp -R "$temporary_dir/$package_name/." "$staging_dir/"
chmod 0755 "$staging_dir/smokeview"
chmod 0755 "$staging_dir/capture_result_slices.py"
chmod 0755 "$staging_dir/capture_slices_ui.pyw"
chmod 0755 "$staging_dir/smv_help.sh"
chmod -R a+rX "$staging_dir"

if ((replacing_existing == 1)); then
  rm -rf -- "$target"
fi
target_owned=1
mv -- "$staging_dir" "$target"

mkdir -p "$link_dir"
rm -f "$link_dir/ashton-smokeview" "$link_dir/ashton-capture-slices" "$link_dir/afm-smv"
ln -sfn "$target/smokeview" "$link_dir/af-smv"
ln -sfn "$target/capture_result_slices.py" "$link_dir/smv-cap"
ln -sfn "$target/capture_slices_ui.pyw" "$link_dir/smv-cap-ui"
ln -sfn "$target/smv_help.sh" "$link_dir/smvhelp"

generic_launcher="$link_dir/smokeview"
if [[ ! -e "$generic_launcher" && ! -L "$generic_launcher" ]]; then
  ln -s "$target/smokeview" "$generic_launcher"
elif [[ -L "$generic_launcher" && "$(readlink "$generic_launcher")" == *"/ashton-smokeview"* ]]; then
  # Matches both the current fixed install directory and the old
  # ashton-smokeview-v<version> scheme, so upgrading from an install made
  # before this change still replaces the launcher instead of leaving it
  # pointed at a directory that was just removed above.
  ln -sfn "$target/smokeview" "$generic_launcher"
else
  echo "Existing launcher was not replaced: $generic_launcher"
fi

applications_dir="$data_home/applications"
mime_dir="$data_home/mime"
mkdir -p "$applications_dir" "$mime_dir/packages" "$config_home"

# Remove stale files from earlier installs that used the old command and
# desktop-entry names, so they don't linger and keep claiming the MIME type.
rm -f "$applications_dir/ashton-smokeview.desktop" "$applications_dir/ashton-capture-slices.desktop" "$applications_dir/afm-smv.desktop"
rm -f "$mime_dir/packages/ashton-smokeview.xml" "$mime_dir/packages/afm-smv.xml"

cat > "$mime_dir/packages/af-smv.xml" <<'MIME_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-ashton-smokeview">
    <comment>Smokeview case</comment>
    <glob pattern="*.smv"/>
  </mime-type>
</mime-info>
MIME_EOF

cat > "$applications_dir/af-smv.desktop" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Ashton Smokeview
Comment=Open a Smokeview case
Exec="$link_dir/af-smv" %f
Icon=applications-graphics
Terminal=false
MimeType=application/x-ashton-smokeview;
DESKTOP_EOF

cat > "$applications_dir/smv-cap.desktop" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Capture result slices
Comment=Capture configured result-review slices with Ashton Smokeview
Exec="$link_dir/smv-cap" %f --overwrite
Icon=camera-photo
Terminal=true
NoDisplay=true
MimeType=application/x-ashton-smokeview;
DESKTOP_EOF

cat > "$applications_dir/smv-cap-ui.desktop" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Capture result slices
Comment=Select Smokeview cases, slice types and capture times
Exec="$link_dir/smv-cap-ui"
Icon=$target/capture_logo.png
Terminal=false
Categories=Graphics;Science;
DESKTOP_EOF

chmod 0644 "$mime_dir/packages/af-smv.xml" "$applications_dir/af-smv.desktop" "$applications_dir/smv-cap.desktop" "$applications_dir/smv-cap-ui.desktop"

if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database "$mime_dir" >/dev/null 2>&1 || echo "Warning: could not update the MIME database."
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir" >/dev/null 2>&1 || echo "Warning: could not update the desktop application database."
fi

if ((system_install == 1)); then
  # xdg-mime default only ever writes the invoking user's own mimeapps.list
  # (root's, under sudo), so it cannot set a machine-wide default. Write the
  # system mimeapps.list stanza directly instead.
  mimeapps_file="$applications_dir/mimeapps.list"
  touch "$mimeapps_file"
  if grep -q '^\[Default Applications\]' "$mimeapps_file" 2>/dev/null; then
    if grep -q '^application/x-ashton-smokeview=' "$mimeapps_file"; then
      sed -i 's#^application/x-ashton-smokeview=.*#application/x-ashton-smokeview=af-smv.desktop#' "$mimeapps_file"
    else
      sed -i '/^\[Default Applications\]/a application/x-ashton-smokeview=af-smv.desktop' "$mimeapps_file"
    fi
  else
    { echo; echo "[Default Applications]"; echo "application/x-ashton-smokeview=af-smv.desktop"; } >> "$mimeapps_file"
  fi
  chmod 0644 "$mimeapps_file"
elif command -v xdg-mime >/dev/null 2>&1; then
  xdg-mime default af-smv.desktop application/x-ashton-smokeview >/dev/null 2>&1 || \
    echo "Warning: could not set Ashton Smokeview as the default .smv application."
fi

echo
echo "Installed Ashton Smokeview in $target"
echo "Smokeview launcher: $link_dir/af-smv"
echo "Capture launcher: $link_dir/smv-cap"
echo "Capture window: $link_dir/smv-cap-ui"
echo "Help launcher: $link_dir/smvhelp"
echo "Run now: $link_dir/af-smv"
echo "To capture: $link_dir/smv-cap /path/to/case.smv"
echo "For help: $link_dir/smvhelp"
echo "Desktop integration: right-click an .smv file and choose Open With -> Capture result slices."
if ((system_install == 1)); then
  echo "Each user selects Ashton Smokeview as their default .smv opener the first"
  echo "time they use Open With, or it is now already the system default shown above."
fi
echo "If 'smokeview' still runs an older copy, run 'type -a smokeview'."
echo "Remove any old alias, or run 'hash -r' if the old path was cached."
if [[ ":$PATH:" != *":$link_dir:"* ]]; then
  echo "Add $link_dir to PATH, or run $target/smokeview directly."
fi
success=1
exit 0

__SMV_PAYLOAD_FOLLOWS__
EOF

cat "$payload_path" >> "$installer_path"
chmod 0755 "$installer_path"
(
  cd "$output_dir"
  sha256sum "$(basename "$installer_path")" > "$(basename "$checksum_path")"
)

echo "Created $installer_path"
echo "Created $checksum_path"
