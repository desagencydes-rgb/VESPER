# VESPER V0 — Hardware, Network & Device Fabric
Version 1.0

## 1. Principle
Hardware is a capability substrate, not VESPER's identity.

## 2. Node classes
Core compute: desktop-class machine for heavier local inference, training, builds and storage.
Mobile/core companion: MacBook Neo or successor for mobility, interaction, lightweight local inference and development.
Mobile endpoints: J3/iPhone where authorized.
Sensor nodes: cameras, microphones and future sensors.
Presence nodes: projector, glass/spatial display, desktop display, phone and future interactive surfaces.

## 3. Device contract
Stable ID, trust state, capabilities, compute profile, health, battery/thermal state where available, location/space, sensors, actuators, network identity and software version.

## 4. Lifecycle
DISCOVERED → ENROLLED → TRUSTED → ONLINE → DEGRADED → OFFLINE → REVOKED

Visibility on a LAN does not imply trust.

## 5. Network
Use a private secure VESPER network/overlay or equivalent segmentation.
Traffic classes: control, events, media, model, management and telemetry.
Media must not starve control traffic.

## 6. Identity
Every node has a cryptographic identity. Mutual authentication where practical. Authorization is capability-based.

## 7. Discovery
Discovery finds candidates. Enrollment establishes trust.

## 8. Remote commands
Commands carry origin, actor, capability, target, expiry, idempotency key and audit correlation.

## 9. Perception routing
Route observations according to privacy, proximity, quality, latency, compute and task requirements. Record evidence origin.

## 10. Presence routing
Select endpoints by visibility, privacy, urgency, modality, proximity and health. Migrate when a surface fails.

## 11. MacBook Neo
A first-class VESPER node, not the single brain. Good roles: local fallback inference, user interaction, development, task continuity, local perception and coordination. Heavy ML/training routes to stronger compute.

## 12. Desktop
Primary heavy-compute candidate for larger models, training, GPU inference, builds and simulation.

## 13. Node loss
Node failure must not erase identity, task state or memory references. Reroute or checkpoint.

## 14. Compromise
isolate → preserve evidence → revoke/rotate credentials → recover from known-good state.

## 15. Hardware-in-loop gate
Discovery, enrollment, capability, reconnect, latency, security, resource/thermal and migration tests.
