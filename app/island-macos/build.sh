#!/bin/sh
# The island. No package manager, no dependencies -- swiftc and the system SDK.
# Run from the repo root: the mark is loaded relative to the working directory.
set -e
cd "$(dirname "$0")"
# face.bin is derived, not authored: regenerate it from the owner's reference
# rather than committing 600 KB of it. Same principle as modes.json.
if [ ! -f face.bin ]; then
  (cd ../.. && python3 docs/design/source/face_cloud.py)
fi
swiftc -O -swift-version 5 main.swift FaceRenderer.swift Behaviour.swift -o island
echo "built: $(pwd)/island"
echo
echo "usage, from the REPO ROOT:"
echo "  python3 tools/island_snapshot.py --measure   # produce the projection"
echo "  ./app/island-macos/island                    # shoulders, hover to expand"
echo "  ./app/island-macos/island --demo             # cycle the mark's states"
echo "  ./app/island-macos/island --expand           # start expanded, for inspection"
echo "  ./app/island-macos/island --seconds 900      # auto-quit, so a spike cannot stick"
