#!/usr/bin/env bash
# CI-only Noto CJK bundle; consumers never access apt repositories.
set -euo pipefail
trap 'echo "::error::Noto CJK bundle failed at line $LINENO (mode ${1:-unset})" >&2' ERR
bundle="${GITHUB_WORKSPACE:-$PWD}/.ci-cache/noto-cjk"
version='1:20230817+repack1-3'
verify_bundle() {
  test "$(cat "$bundle/package-version.txt")" = "$version"
  (cd "$bundle" && sha256sum --check SHA256SUMS)
  test -s "$bundle/fonts/NotoSansCJK-Regular.ttc"
  test -s "$bundle/copyright"
}
case "${1:-}" in
  prepare)
    stage=$(mktemp -d "${RUNNER_TEMP:-/tmp}/noto-cjk.XXXXXX")
    sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 update -qq
    (
      cd "$stage"
      apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 download "fonts-noto-cjk=$version"
      dpkg-deb --extract ./*.deb unpacked
    )
    mkdir -p "$bundle/fonts"
    cp -a "$stage/unpacked/usr/share/fonts/opentype/noto/." "$bundle/fonts/"
    cp "$stage/unpacked/usr/share/doc/fonts-noto-cjk/copyright" "$bundle/copyright"
    printf '%s\n' "$version" > "$bundle/package-version.txt"
    (cd "$bundle" && find fonts -type f -name '*.ttc' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    verify_bundle
    ;;
  install)
    verify_bundle
    font_dir="$HOME/.local/share/fonts/aixunlian-noto-cjk"
    mkdir -p "$font_dir"
    cp -a "$bundle/fonts/." "$font_dir/"
    fc-cache -f "$font_dir"
    matched=$(fc-match --format '%{family} | %{file}\n' 'Noto Sans CJK SC:lang=zh-cn')
    printf '%s\n' "$matched"
    grep -Fq 'Noto Sans CJK SC' <<< "$matched" || { echo '::error::Noto CJK SC is not available to fontconfig/Chrome'; exit 1; }
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
      printf '### Noto CJK font verification\nPackage: `%s`\n\nMatched: `%s`\n' "$version" "$matched" >> "$GITHUB_STEP_SUMMARY"
    fi
    ;;
  *) echo 'Usage: browser-fonts.sh prepare|install' >&2; exit 2 ;;
esac
