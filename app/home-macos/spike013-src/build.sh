#!/bin/sh
# SPIKE-013 needs FaceRenderer.swift compiled in beside it, and Swift only
# permits top-level code in a file called main.swift -- which is why this lives
# in its own directory instead of next to the single-file probes.
set -e
cd "$(dirname "$0")"
swiftc -O -swift-version 5 main.swift ../../island-macos/FaceRenderer.swift -o ../spike013
echo "built: app/home-macos/spike013"
