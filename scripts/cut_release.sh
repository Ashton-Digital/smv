#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Cut an Ashton Smokeview Linux release: update ASHTON_RELEASE, build inside an
Ubuntu 22.04 container (matching the oldest supported target's glibc, so the
resulting binary also runs on newer systems -- see
Build/ASHTON_INTERNAL_RELEASE.md, "Building on the correct Linux version"),
and package the installer.

Usage:
  scripts/cut_release.sh [ASHTON_RELEASE] [options]

Arguments:
  ASHTON_RELEASE     New release suffix, e.g. af2 or af2-rc1. Prompted for
                     interactively if omitted and this is an interactive
                     terminal; required otherwise.

Options:
  --skip-build       Repackage the existing cbuild/release-linux build
                     instead of rebuilding (still updates ASHTON_RELEASE and
                     re-verifies the embedded revision matches).
  -h, --help         Show this help

This does not commit, tag, or push anything -- it only updates
CMakeLists.txt and produces dist/ashton-smokeview-v<version>-linux-x64.sh.
Review and commit CMakeLists.txt yourself once you're happy with the result.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cmakelists="$repo_root/CMakeLists.txt"

new_release=""
skip_build=0

while (($# > 0)); do
  case "$1" in
    --skip-build)
      skip_build=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      fail "unknown option: $1"
      ;;
    *)
      [[ -z "$new_release" ]] || fail "unexpected extra argument: $1"
      new_release="$1"
      shift
      ;;
  esac
done

[[ -f "$cmakelists" ]] || fail "CMakeLists.txt not found at $cmakelists"
current_release="$(sed -nE 's/^set\(ASHTON_RELEASE "([^"]+)"\).*/\1/p' "$cmakelists")"
[[ -n "$current_release" ]] || fail "could not find ASHTON_RELEASE in $cmakelists"

if [[ -z "$new_release" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "New ASHTON_RELEASE [currently $current_release]: " new_release
  fi
  [[ -n "$new_release" ]] || fail "a new ASHTON_RELEASE value is required (pass it as an argument in a non-interactive session)"
fi

[[ "$new_release" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] || fail "invalid release name: $new_release"

echo "ASHTON_RELEASE: $current_release -> $new_release"
sed -i "s/^set(ASHTON_RELEASE \"${current_release}\")/set(ASHTON_RELEASE \"${new_release}\")/" "$cmakelists"

if command -v docker >/dev/null 2>&1; then
  docker_cmd=(docker)
else
  fail "docker not found on PATH"
fi
# A snap-installed Docker has no regular 'docker' group, so its socket needs sudo.
if ! "${docker_cmd[@]}" info >/dev/null 2>&1; then
  docker_cmd=(sudo docker)
fi

build_step=""
if ((skip_build == 0)); then
  build_step='
rm -rf cbuild/release-linux
cmake -S . -B cbuild/release-linux \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DVENDORED_UI_LIBS=ON \
  -DVENDORED_LIBS=OFF
cmake --build cbuild/release-linux --target smokeview -j"$(nproc)"
'
fi

builder_image="ashton-smokeview-linux-builder:ubuntu-22.04"
echo "Preparing cached Ubuntu 22.04 builder..."
"${docker_cmd[@]}" build --platform linux/amd64 \
  --file "$script_dir/Dockerfile.release-linux" --tag "$builder_image" "$script_dir"

echo "Packaging inside Ubuntu 22.04..."
"${docker_cmd[@]}" run --rm --platform linux/amd64 -v "$repo_root":/src -w /src "$builder_image" bash -c "
set -Eeuo pipefail
git config --global --add safe.directory /src
python3 -c 'import PySide6.QtWidgets, PyInstaller'
export PATH=/usr/local/bin:\$PATH
hash -r
${build_step}
./scripts/package_release_linux.sh --skip-build
chown -R $(id -u):$(id -g) /src/cbuild /src/dist
"

version="$(sed -nE 's/.*project\(smv .*VERSION ([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' "$cmakelists" | head -n 1)-${new_release}"
installer="$repo_root/dist/ashton-smokeview-v${version}-linux-x64.sh"

if [[ -x "$repo_root/cbuild/release-linux/smokeview" ]] && command -v objdump >/dev/null 2>&1; then
  glibc_floor="$(objdump -T "$repo_root/cbuild/release-linux/smokeview" 2>/dev/null | grep -oE 'GLIBC_[0-9]+(\.[0-9]+)+' | cut -d_ -f2 | sort -uV | tail -1)"
  [[ -n "$glibc_floor" ]] || fail "could not determine the Linux glibc floor"
  [[ "$(printf '%s\n' "$glibc_floor" 2.35 | sort -V | tail -1)" == 2.35 ]] || \
    fail "Linux glibc floor $glibc_floor exceeds Ubuntu 22.04's 2.35"
  echo "glibc floor: $glibc_floor (compatible with Ubuntu 22.04's 2.35)"
fi

echo
if [[ -f "$installer" ]]; then
  echo "Built: $installer"
  echo "Checksum: $(cat "${installer}.sha256" 2>/dev/null || echo '(missing)')"
else
  echo "Warning: expected installer not found at $installer" >&2
fi
echo
if [[ "$current_release" == "$new_release" ]]; then
  echo "Release version in CMakeLists.txt was already $new_release."
else
  echo "Release version changed in CMakeLists.txt. Review and commit that change."
fi
echo "Install and test the package on a target Linux machine before distribution."
