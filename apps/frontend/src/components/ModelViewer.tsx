import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PreviewMesh } from "../lib/api";
import { ISO_DIRECTION, applyHighlight, buildEdges, buildGeometry } from "../lib/mesh";

interface Props {
  mesh: PreviewMesh;
  highlighted: Set<string>;
}

/** Three.js preview. Z-up (CAD convention), isometric default camera, per-face highlighting. */
export default function ModelViewer({ mesh, highlighted }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const geomRef = useRef<THREE.BufferGeometry | null>(null);
  const renderRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(0xf8fafc);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    scene.add(sun);

    const geom = buildGeometry(mesh, highlighted);
    geomRef.current = geom;
    const materials = [
      new THREE.MeshStandardMaterial({ color: 0x9aa7b8, metalness: 0.1, roughness: 0.6, side: THREE.DoubleSide,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
      new THREE.MeshStandardMaterial({ color: 0xf97316, metalness: 0.1, roughness: 0.5, side: THREE.DoubleSide,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
    ];
    scene.add(new THREE.Mesh(geom, materials));
    const edgeGeom = buildEdges(mesh);
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x1e293b });
    scene.add(new THREE.LineSegments(edgeGeom, edgeMat));

    const sphere = geom.boundingSphere ?? new THREE.Sphere(new THREE.Vector3(), 1);
    const camera = new THREE.PerspectiveCamera(30, 1, sphere.radius / 100, sphere.radius * 100);
    camera.up.set(0, 0, 1);
    const distance = sphere.radius / Math.sin(THREE.MathUtils.degToRad(15)) * 1.1;
    camera.position.copy(sphere.center).addScaledVector(ISO_DIRECTION, distance);
    camera.lookAt(sphere.center);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(sphere.center);
    controls.update();

    const render = () => {
      sun.position.copy(camera.position);
      renderer.render(scene, camera);
    };
    renderRef.current = render;
    controls.addEventListener("change", render);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    return () => {
      observer.disconnect();
      controls.dispose();
      geom.dispose();
      edgeGeom.dispose();
      materials.forEach((m) => m.dispose());
      edgeMat.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      geomRef.current = null;
      renderRef.current = null;
    };
    // the scene is rebuilt only when the mesh changes; highlighting is applied below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mesh]);

  useEffect(() => {
    if (geomRef.current) {
      applyHighlight(geomRef.current, mesh, highlighted);
      renderRef.current?.();
    }
  }, [mesh, highlighted]);

  return (
    <div className="relative h-full w-full">
      <div ref={host} className="h-full w-full" data-testid="model-viewer" />
      <span className="pointer-events-none absolute bottom-2 left-2 text-xs text-slate-400">
        Z up · isometric · drag to orbit, scroll to zoom
      </span>
    </div>
  );
}
