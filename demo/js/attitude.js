// Demo attitude convention and its self-check.
// Display axes (three.js, right-handed): X = bow, Y = up, Z = starboard.
// + roll  = starboard side down  (rotation about +X)
// + pitch = bow up               (rotation about +Z)
// Euler order "YZX": roll is applied first, then pitch (yaw is not shown).
// This is a display convention; the MPU6050 mounting signs are not bench-verified.
import * as THREE from "three";

const DEG = Math.PI / 180;

export function applyAttitude(object3d, rollDeg, pitchDeg) {
  object3d.rotation.set(rollDeg * DEG, 0, pitchDeg * DEG, "YZX");
  object3d.updateMatrixWorld(true);
}

/**
 * Checks the real attitude group: a pitch-only sample must raise the bow and leave the
 * sides level; a roll-only sample must lower the starboard side and leave the bow level.
 * Points are in the group's local frame (mm from the pivot). Restores the rotation.
 */
export function orientationCheck(group) {
  const saved = group.rotation.clone();
  const bow = new THREE.Vector3(100, 0, 0), stbd = new THREE.Vector3(0, 0, 60);
  const port = new THREE.Vector3(0, 0, -60);
  const world = p => {
    const parentInverse = group.parent ? group.parent.matrixWorld.clone().invert() : new THREE.Matrix4();
    // In the parent frame, relative to the pivot (the group's own position).
    return group.localToWorld(p.clone()).applyMatrix4(parentInverse).sub(group.position);
  };
  const results = [];
  const rise = 100 * Math.sin(5 * DEG), drop = 60 * Math.sin(5 * DEG);

  applyAttitude(group, 0, 5);
  let b = world(bow), s = world(stbd), p = world(port);
  results.push({ name: `Pitch-only +5°: bow rises ${b.y.toFixed(2)} mm (expected +${rise.toFixed(2)})`,
                 pass: Math.abs(b.y - rise) < 0.01 });
  results.push({ name: `Pitch-only +5°: sides stay level (stbd ${s.y.toFixed(2)}, port ${p.y.toFixed(2)} mm)`,
                 pass: Math.abs(s.y) < 0.01 && Math.abs(p.y) < 0.01 });

  applyAttitude(group, 5, 0);
  b = world(bow); s = world(stbd); p = world(port);
  results.push({ name: `Roll-only +5°: starboard side ${s.y.toFixed(2)} mm, port side +${p.y.toFixed(2)} mm (expected −${drop.toFixed(2)} / +${drop.toFixed(2)})`,
                 pass: Math.abs(s.y + drop) < 0.01 && Math.abs(p.y - drop) < 0.01 });
  results.push({ name: `Roll-only +5°: bow stays level (${b.y.toFixed(2)} mm)`, pass: Math.abs(b.y) < 0.01 });

  group.rotation.copy(saved);
  group.updateMatrixWorld(true);
  return results;
}
