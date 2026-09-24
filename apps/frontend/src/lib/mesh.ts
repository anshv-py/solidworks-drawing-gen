import * as THREE from "three";
import type { PreviewMesh } from "./api";

export const MATERIAL_DEFAULT = 0;
export const MATERIAL_HIGHLIGHT = 1;

/**
 * Build a BufferGeometry with one draw group per B-Rep face so faces can be
 * highlighted by switching the group's material index. STL meshes have no groups.
 */
export function buildGeometry(mesh: PreviewMesh, highlighted: Set<string> = new Set()): THREE.BufferGeometry {
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
  geom.setIndex(mesh.indices);
  if (mesh.groups.length === 0) {
    geom.addGroup(0, mesh.indices.length, MATERIAL_DEFAULT);
  } else {
    for (const g of mesh.groups) {
      geom.addGroup(g.start, g.count, highlighted.has(g.face_id) ? MATERIAL_HIGHLIGHT : MATERIAL_DEFAULT);
    }
  }
  geom.computeVertexNormals();
  geom.computeBoundingBox();
  geom.computeBoundingSphere();
  return geom;
}

export function applyHighlight(geom: THREE.BufferGeometry, mesh: PreviewMesh, highlighted: Set<string>): void {
  mesh.groups.forEach((g, i) => {
    const group = geom.groups[i];
    if (group) group.materialIndex = highlighted.has(g.face_id) ? MATERIAL_HIGHLIGHT : MATERIAL_DEFAULT;
  });
}

/** Edge polylines -> LineSegments pairs. */
export function buildEdges(mesh: PreviewMesh): THREE.BufferGeometry {
  const pts: number[] = [];
  for (const e of mesh.edges) {
    for (let i = 0; i + 5 < e.points.length; i += 3) {
      pts.push(...e.points.slice(i, i + 6));
    }
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return geom;
}

/** Isometric camera direction (equal angles to X, Y, Z; Z up). */
export const ISO_DIRECTION = new THREE.Vector3(1, -1, 1).normalize();
