#!/bin/sh
set -e
cd "$(dirname "$0")"
swiftc -O -swift-version 5 main.swift ../../island-macos/FaceRenderer.swift -o ../face_ground
echo "built: app/home-macos/face_ground"
