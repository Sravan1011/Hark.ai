#!/usr/bin/env bash
# Assemble the website into site/dist (Vercel runs this; see vercel.json).
# The installer is served from the same domain, so the page's install command
# (curl -fsSL https://<domain>/install.sh | bash) always matches where it's hosted.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$root/site/dist"
rm -rf "$out"
mkdir -p "$out/screenshots"
cp -r "$root/site/public/." "$out/"
cp "$root/install.sh" "$out/install.sh"
cp "$root/docs/screenshots/"*.png "$out/screenshots/"
echo "Built $(find "$out" -type f | wc -l) files into $out"
