import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { getAuthToken } from '../../api/client';
import type { CatalogSourceId } from './types';

/** Decodificador Draco copiado de three/examples/jsm/libs/draco/gltf (servido de public/custom/draco). */
const DRACO_PATH = '/custom/draco/';

async function fetchPlate(source: CatalogSourceId, modelId: string, fileId: string, plate: number, signal: AbortSignal) {
  const token = getAuthToken();
  const resp = await fetch(`/api/v1/custom/models/${source}/${modelId}/preview/${fileId}?plate=${plate}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!resp.ok) throw new Error(resp.status === 404 ? 'Sem prévia 3D para este perfil.' : `Falha ao carregar a prévia (${resp.status}).`);
  return { buffer: await resp.arrayBuffer(), plates: Number(resp.headers.get('X-Plate-Count')) || 1 };
}

/**
 * Prévia 3D sem baixar o 3MF: o GLB leve (Draco) que o próprio MakerWorld usa no visualizador do site, uma placa por
 * vez. Tela cheia no celular; arrastar gira, pinça dá zoom.
 */
export function GlbPreviewModal({
  source,
  modelId,
  fileId,
  title,
  onClose,
}: {
  source: CatalogSourceId;
  modelId: string;
  fileId: string;
  title: string;
  onClose: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [plate, setPlate] = useState(1);
  const [plates, setPlates] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 2, 1.5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-1.5, 0.5, -1);
    scene.add(fill);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const resize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();

    const draco = new DRACOLoader().setDecoderPath(DRACO_PATH);
    const loader = new GLTFLoader().setDRACOLoader(draco);
    fetchPlate(source, modelId, fileId, plate, ctrl.signal)
      .then(({ buffer, plates: count }) => {
        setPlates(count);
        return new Promise<THREE.Group>((ok, err) => loader.parse(buffer, '', (g) => ok(g.scene), err));
      })
      .then((model) => {
        if (ctrl.signal.aborted) return;
        model.traverse((o) => {
          const mesh = o as THREE.Mesh;
          if (mesh.isMesh) {
            const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
            mats.forEach((m) => {
              const std = m as THREE.MeshStandardMaterial;
              std.side = THREE.DoubleSide;
              if (std.metalness !== undefined) std.metalness = Math.min(std.metalness, 0.1);
              if (std.roughness !== undefined) std.roughness = Math.max(std.roughness, 0.6);
            });
          }
        });
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const radius = Math.max(size.length() / 2, 1e-4);
        const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
        camera.near = dist / 100;
        camera.far = dist * 100;
        camera.position.copy(center).add(new THREE.Vector3(0.6, 0.55, 1).normalize().multiplyScalar(dist));
        camera.updateProjectionMatrix();
        controls.target.copy(center);
        controls.update();
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Falha ao carregar a prévia.');
        setLoading(false);
      });

    return () => {
      ctrl.abort();
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      draco.dispose();
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry.dispose();
          (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((m) => m.dispose());
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [source, modelId, fileId, plate]);

  return createPortal(
    <div className="fixed inset-0 z-[100] flex flex-col bg-bambu-dark" role="dialog" aria-modal="true" aria-label={title}>
      <div className="flex items-center gap-2 border-b border-bambu-dark-tertiary px-3 py-2" style={{ paddingTop: 'calc(0.5rem + env(safe-area-inset-top))' }}>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-white">{title}</p>
        <button type="button" onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-lg text-bambu-gray hover:text-white" aria-label="Fechar">
          <X className="h-5 w-5" />
        </button>
      </div>
      {plates > 1 && (
        <div className="flex gap-2 overflow-x-auto px-3 py-2">
          {Array.from({ length: plates }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setPlate(n)}
              className={`min-h-9 shrink-0 rounded-full border px-3 text-xs ${n === plate ? 'border-bambu-green bg-bambu-green/20 text-bambu-green' : 'border-bambu-dark-tertiary text-bambu-gray'}`}
            >
              Placa {n}
            </button>
          ))}
        </div>
      )}
      <div ref={hostRef} className="relative min-h-0 flex-1 touch-none">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="h-8 w-8 text-bambu-green motion-safe:animate-spin" aria-label="Carregando" />
          </div>
        )}
        {error && <p className="absolute inset-x-4 top-1/2 text-center text-sm text-red-400">{error}</p>}
      </div>
    </div>,
    document.body,
  );
}
