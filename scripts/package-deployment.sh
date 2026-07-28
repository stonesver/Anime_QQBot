#!/bin/sh
set -eu

usage() {
  printf 'usage: %s OUTPUT.tar.gz\n' "$0" >&2
  exit 64
}

output="${1:-}"
[ -n "$output" ] || usage
[ "$#" -eq 1 ] || usage
case "$output" in
  *.tar.gz) ;;
  *) printf 'output must end with .tar.gz: %s\n' "$output" >&2; exit 64 ;;
esac

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd -P)"
project_dir="$(CDPATH= cd "$script_dir/.." && pwd -P)"
output_dir="$(dirname "$output")"
output_name="$(basename "$output")"
mkdir -p "$output_dir"
output_dir="$(CDPATH= cd "$output_dir" && pwd -P)"
output="$output_dir/$output_name"

staging="$(mktemp -d "${TMPDIR:-/tmp}/anime-qqbot-package.XXXXXX")"
partial="$(mktemp "$output.tmp.XXXXXX")"
cleanup() {
  rm -rf "$staging"
  rm -f "$partial"
}
trap cleanup EXIT HUP INT TERM

bundle="$staging/anime-qqbot"
mkdir -p "$bundle/scripts"

cp "$project_dir/compose.yaml" "$bundle/compose.yaml"
cp "$project_dir/compose.server-2g.yaml" "$bundle/compose.server-2g.yaml"
cp "$project_dir/.env.example" "$bundle/.env.example"
for name in deploy-acr.sh napcat-entrypoint.sh backup-postgres.sh restore-postgres.sh; do
  cp "$project_dir/scripts/$name" "$bundle/scripts/$name"
done

COPYFILE_DISABLE=1
export COPYFILE_DISABLE
tar -C "$staging" -czf "$partial" anime-qqbot
mv "$partial" "$output"

if command -v shasum >/dev/null 2>&1; then
  digest="$(shasum -a 256 "$output" | awk '{print $1}')"
else
  digest="$(sha256sum "$output" | awk '{print $1}')"
fi

printf 'deployment package: %s\n' "$output"
printf 'SHA-256: %s\n' "$digest"
