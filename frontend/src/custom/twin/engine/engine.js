// Gêmeo digital da A1 dentro do Bambuddy: só o canvas. Porte de `3d-printing/twin/web/js/main.js` para um módulo
// montável/desmontável (sem globais): estado via SSE (`eventsUrl()`), G-code do job via `jobUrl(id)`, modelo real
// opcional via `modelUrl()` (404 = procedural). Pensado primeiro para o PWA no celular: pixelRatio limitado e
// adaptativo, loop de render pausado com a aba/PWA em segundo plano (visibilitychange) ou fora da tela, SSE
// fechado em segundo plano e reaberto (com token novo) ao voltar.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { A1Model } from './printer.js';
import { PrintedObject } from './object.js';
import { decodeJob } from './program.js';
import { Tracker } from './sync.js';

const REST = { x: 40, y: 170, z: 90 };

/**
 * @param {HTMLElement} container elemento que recebe o canvas (ocupa 100% dele)
 * @param {{ eventsUrl: () => string, jobUrl: (id: string) => string, modelUrl?: (() => string) | null,
 *           tuning?: { lead?: number, lat?: number, tau?: number, autoFocus?: boolean }, debug?: boolean, procedural?: boolean }} opts
 */
// O GLB da A1 (~2,8 MB) vem com o token de stream na URL, que muda a cada sessão: o cache HTTP nunca acertava e o modelo
// era baixado de novo a cada abertura. Guarda o arquivo no Cache Storage (chave sem o token) e na memória da página.
const MODEL_CACHE = 'custom-twin-model-v1';
const memModel = new Map();
function modelCacheKey(url) {
  const u = new URL(url, location.href);
  u.searchParams.delete('token');
  return u.toString();
}
async function loadModelBuffer(url, signal) {
  const key = modelCacheKey(url);
  if (memModel.has(key)) return memModel.get(key);
  let store = null;
  try { store = 'caches' in window ? await caches.open(MODEL_CACHE) : null; } catch { store = null; }
  try {
    const hit = store && await store.match(key);
    if (hit) { const buf = await hit.arrayBuffer(); memModel.set(key, buf); return buf; }
  } catch { /* cache indisponível: baixa */ }
  const r = await fetch(url, { signal, credentials: 'same-origin' });
  if (!r.ok) return null;
  const buf = await r.arrayBuffer();
  memModel.set(key, buf);
  try { await store?.put(key, new Response(buf.slice(0), { headers: { 'Content-Type': 'model/gltf-binary' } })); } catch { /* cota/privado: segue sem cache */ }
  return buf;
}

export function createTwin(container, opts) {
  const DEBUG = !!opts.debug;
  const LEAD = Math.max(-5, Math.min(5, Number(opts.tuning?.lead) || 0));
  const TRK_URL = {};
  for (const k of ['lat', 'tau']) if (Number.isFinite(opts.tuning?.[k])) TRK_URL[k] = opts.tuning[k];
  const isMobile = matchMedia('(pointer:coarse)').matches || Math.min(screen.width, screen.height) < 700;
  // Nitidez: até 2x (telas de celular têm ~3x) e nunca abaixo de 1,25x (abaixo disso fica visivelmente pixelizado).
  const DPR = window.devicePixelRatio || 1;
  const PR_MAX = Math.min(DPR, 2);
  const PR_MIN = Math.min(DPR, 1.25);
  let disposed = false;
  let lastAdapt = performance.now();

  const canvas = document.createElement('canvas');
  // Começa invisível e aparece (fade) só quando o modelo definitivo está montado: sem "piscar" o procedural antes do real.
  canvas.style.cssText = 'position:absolute;inset:0;display:block;width:100%;height:100%;touch-action:none;outline:none;cursor:default;opacity:0;transition:opacity 180ms ease-out';
  canvas.setAttribute('aria-hidden', 'true');
  container.appendChild(canvas);

  // ---------- renderer / cena ----------
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', alpha: false });
  let pr = PR_MAX;
  renderer.setPixelRatio(pr);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.82;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x171a21);
  scene.fog = new THREE.Fog(0x171a21, 1300, 3600);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  scene.environment = envTex;
  scene.environmentIntensity = 0.7;

  const key = new THREE.DirectionalLight(0xfff2e0, 2.4);
  key.position.set(330, 620, 420);
  key.castShadow = true;
  key.shadow.mapSize.set(isMobile ? 1024 : 2048, isMobile ? 1024 : 2048);
  const sc = key.shadow.camera;
  sc.left = -330; sc.right = 330; sc.top = 380; sc.bottom = -330; sc.near = 100; sc.far = 1600;
  key.shadow.bias = -0.0006; key.shadow.normalBias = 0.6; key.shadow.radius = 5;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x9ab8ff, 1.6);
  rim.position.set(-420, 260, -380);
  scene.add(rim);

  // chão: disco com gradiente + sombra suave
  {
    const c = document.createElement('canvas'); c.width = c.height = 512;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(256, 256, 20, 256, 256, 256);
    grd.addColorStop(0, '#363b46'); grd.addColorStop(0.5, '#222630'); grd.addColorStop(1, '#171a21');
    g.fillStyle = grd; g.fillRect(0, 0, 512, 512);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const floor = new THREE.Mesh(new THREE.CircleGeometry(7000, 64).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0 }));
    floor.position.y = -78; floor.receiveShadow = true; scene.add(floor);
  }

  const stats = { fps: 0, frames: 0, model: 'procedural', paused: false, sse: 'connecting' };
  const model = new A1Model();
  // Modelo real da A1 (GLB opcional no volume de dados do Bambuddy; licença desconhecida, nunca versionado). Sem ele: procedural.
  const abort = new AbortController();
  let revealed = false;
  const reveal = () => {
    if (revealed || disposed) return;
    revealed = true;
    lastAdapt = performance.now();   // sem adaptar a resolução pelos primeiros quadros (compilação de shaders)
    requestAnimationFrame(() => { canvas.style.opacity = '1'; });
  };
  if (opts.modelUrl && !opts.procedural) {
    // Sem resposta em 6 s (rede ruim), mostra o procedural; o real ainda entra quando chegar.
    const fallback = setTimeout(reveal, 6000);
    (async () => {
      try {
        const buf = await loadModelBuffer(opts.modelUrl(), abort.signal);
        if (!buf || disposed) return;
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
        const gltf = await new Promise((ok, err) => new GLTFLoader().parse(buf, '', ok, err));
        if (disposed) { disposeTree(gltf.scene); return; }
        model.attachCAD(gltf.scene);
        stats.model = 'step'; view.fit = 1.0; view.ty = 125;
      } catch (e) { if (DEBUG) console.warn('modelo STEP indisponível; procedural', e); }
      finally { clearTimeout(fallback); reveal(); }
    })();
  } else {
    reveal();
  }
  scene.add(model.root);
  const object = new PrintedObject([]);
  model.bed.add(object.group);
  object.group.position.set(-128, 0, 128);   // geometria do objeto vem em (X, Z, -Y) do G-code; a mesa tem origem no centro da placa

  // ---------- câmera frontal com deriva sutil ----------
  const camera = new THREE.PerspectiveCamera(32, 1, 20, 5000);
  const view = { az: 0, el: 0.45, dist: 900, tx: -5, ty: 120, tz: -10, dAz: 0, dEl: 0, zoom: 0.72, fit: 1, f: 0, fx: 0, fy: 0, fz: 0, lastInput: -1e9 };
  let W = 0, H = 0;
  function frame() {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    if (w === W && h === H) return;
    W = w; H = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const t2 = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    view.dist = Math.max(450 / t2, 415 / (t2 * camera.aspect));       // vista frontal: enquadra ~450 mm de altura / 415 mm de largura (a A1 de pilar a pilar)
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(() => frame());
  ro.observe(container);
  frame();

  // ponteiro: arrastar gira, roda/pinça dá zoom; sem nenhuma dica visual
  const pts = new Map();
  let lx = 0, ly = 0, pinch = 0;
  const onDown = (e) => { canvas.setPointerCapture(e.pointerId); pts.set(e.pointerId, e); lx = e.clientX; ly = e.clientY; };
  const onUp = (e) => { pts.delete(e.pointerId); pinch = 0; };
  const onMove = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, e);
    view.lastInput = performance.now();
    if (pts.size >= 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (pinch) view.zoom = Math.min(2.2, Math.max(0.45, view.zoom * (pinch / d)));
      pinch = d;
      return;
    }
    view.dAz -= (e.clientX - lx) * 0.006; view.dEl += (e.clientY - ly) * 0.004;
    view.dEl = Math.min(0.55, Math.max(-0.35, view.dEl));
    lx = e.clientX; ly = e.clientY;
  };
  const onWheel = (e) => { e.preventDefault(); view.zoom = Math.min(2.2, Math.max(0.45, view.zoom * Math.exp(e.deltaY * 0.001))); view.lastInput = performance.now(); };
  const onCtx = (e) => e.preventDefault();
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('contextmenu', onCtx);

  function updateCamera(tNow) {
    const idle = (performance.now() - view.lastInput) > 6000;
    if (idle) { view.dAz *= 0.995; view.dEl *= 0.995; }        // volta devagar ao enquadramento padrão
    const drift = 0, driftE = 0;
    const az = view.az + view.dAz + drift, el = Math.min(1.2, Math.max(0.05, view.el + view.dEl + driftE));
    // com um job ativo, a câmera se aproxima suavemente do objeto (centro/tamanho vindos do G-code)
    let fx = 0, fy = 0, fz = 0, ff = 0;
    if (opts.tuning?.autoFocus && S.bbox && S.prog && object.fade > 0.5) {
      const [x0, y0, x1, y1] = S.bbox;
      const size = Math.max(x1 - x0, y1 - y0, S.zmax || 0, 40);
      fx = (x0 + x1) / 2 - 128; fz = -(y0 + y1) / 2; fy = Math.min(S.zmax || 0, 120) / 2 + 20;
      ff = Math.min(1, Math.max(0.25, 1 - size / 330)) * 0.75;
    }
    view.f += ((ff) - view.f) * 0.02;
    view.fx += (fx - view.fx) * 0.03; view.fy += (fy - view.fy) * 0.03; view.fz += (fz - view.fz) * 0.03;
    const tx = view.tx + (view.fx - view.tx) * view.f, ty = view.ty + (view.fy - view.ty) * view.f, tz = view.tz + (view.fz - view.tz) * view.f;
    const d = view.dist * view.zoom * view.fit * (1 - 0.30 * view.f);
    camera.position.set(tx + d * Math.sin(az) * Math.cos(el), ty + d * Math.sin(el), tz + d * Math.cos(az) * Math.cos(el));
    camera.lookAt(tx, ty, tz);
  }

  // ---------- estado ----------
  const S = {
    msg: null, s: {}, job: { status: 'none' }, jobId: '', prog: null, tracker: null, workerBusy: false,
    pose: { ...REST }, trays: [], lastMsgPerf: -1e9, bbox: null, zmax: 0, geom: null, buildT0: 0,
  };
  const worker = new Worker(new URL('./geom-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = (ev) => {
    S.workerBusy = false;
    const r = ev.data;
    if (disposed) return;
    if (r.error) { if (DEBUG) console.error('worker', r.error); return; }
    object.build(r);
    S.geom = { tris: r.tris, verts: r.verts, lod: r.lod, strands: r.nStrands };
    S.bbox = r.bbox; S.zmax = r.zmax; S.geom.build_ms = Math.round(performance.now() - S.buildT0);
    applyPalette();
  };

  function trayColor(i) {
    const t = S.trays.find((x) => Number(x.id) === i);
    const c = t && t.tray_color;
    if (c && /^[0-9a-fA-F]{6,8}$/.test(c) && c.slice(0, 6).toLowerCase() !== '000000') return '#' + c.slice(0, 6);
    return null;
  }
  function applyPalette() {
    if (!S.prog) return;
    const base = S.prog.colors || [];
    const cols = [];
    for (let i = 0; i < 16; i++) cols[i] = trayColor(i) || base[i] || null;
    object.setPalette(cols);
  }

  async function loadJob(id) {
    S.jobId = id;
    try {
      const r = await fetch(opts.jobUrl(id), { signal: abort.signal, credentials: 'same-origin' });
      if (!r.ok) throw new Error(String(r.status));
      const prog = decodeJob(await r.arrayBuffer());
      if (disposed || S.jobId !== id) return;
      S.prog = prog; S.tracker = new Tracker(prog, { ...TRK_URL, ...(DEBUG && window.__trkOpts ? window.__trkOpts : {}) });
      if (S.s && S.s.gcode_state) {
        const now = performance.now() / 1000, m = S.msg || {};
        // since_pr foi calculado no envio: soma o tempo decorrido desde a chegada da mensagem (o job demora)
        S.tracker.feed(S.s, now, m.age || 0, { sincePR: m.since_pr != null ? m.since_pr + (now - S.lastMsgPerf) : null });
      }
      applyPalette();
      S.workerBusy = true; S.buildT0 = performance.now();
      const maxTris = isMobile ? 900000 : 2200000;
      worker.postMessage({ xyz: prog.xyz.slice(), t: prog.t.slice(), kind: prog.kind.slice(), attr: prog.attr.slice(), attrs: prog.attrs, features: prog.features, budget: { maxTris } });
    } catch (e) {
      if (S.jobId === id) S.jobId = '';             // tenta de novo no próximo snapshot
      if (DEBUG && !disposed) console.warn('job', e);
    }
  }

  function onMessage(msg) {
    const nowPerf = performance.now() / 1000;
    S.lastMsgPerf = nowPerf;
    S.msg = msg; S.s = msg.s || {}; S.job = msg.job || { status: 'none' };
    S.trays = (S.s.ams && S.s.ams.trays) || [];
    const age = msg.age || 0;
    if (S.job.status === 'ready' && S.job.id && S.job.id !== S.jobId) loadJob(S.job.id);
    if (S.job.status === 'none' && S.prog) { S.prog = null; S.tracker = null; S.jobId = ''; }
    if (S.tracker) S.tracker.feed(S.s, nowPerf, age, { sincePR: msg.since_pr });
    if (S.prog) applyPalette();
  }

  // ---------- SSE (fechado em segundo plano; reaberto com URL nova, que traz o token de stream atual) ----------
  let es = null, retryTimer = 0, retryDelay = 1500;
  function connect() {
    if (disposed || es) return;
    clearTimeout(retryTimer);
    stats.sse = 'connecting';
    const src = new EventSource(opts.eventsUrl());
    es = src;
    src.onopen = () => { retryDelay = 1500; stats.sse = 'open'; };
    src.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch { /* ignora */ } };
    src.onerror = () => {
      // erro transitório: o EventSource reconecta sozinho. Fechado (ex.: 401 com token vencido): reabre com URL nova.
      if (src.readyState === EventSource.CLOSED && es === src) {
        es = null; stats.sse = 'closed';
        if (!document.hidden) retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30000);
      }
    };
  }
  function disconnect() {
    clearTimeout(retryTimer);
    if (es) { es.close(); es = null; }
    stats.sse = 'closed';
  }

  // ---------- loop (pausado em segundo plano / fora da tela) ----------
  let lastT = performance.now();
  const tmp = {};
  let fpsAcc = 0, fpsN = 0;
  function tick() {
    const nowP = performance.now();
    const dt = Math.min((nowP - lastT) / 1000, 0.1);
    lastT = nowP;
    const nowS = nowP / 1000;
    const stale = nowS - S.lastMsgPerf > 15;
    let target = REST, printing = false, showObj = false, T = 0, kind = 0;
    const tr = S.tracker;
    if (tr && !stale) {
      T = tr.update(nowS);
      if (tr.locked) {
        S.prog.posAt(Math.min(S.prog.total, Math.max(0, T + LEAD * tr.scale)), tmp);
        // limites físicos da A1 (curso do G-code: X -48..267, Y 0..262.5, Z 0..256): nunca desenha fora
        target = { x: Math.min(270, Math.max(-50, tmp.x)), y: Math.min(264, Math.max(-2, tmp.y)), z: Math.min(260, Math.max(0, tmp.z)) };
        kind = tmp.kind;
        const gs = S.s.gcode_state;
        printing = (gs === 'RUNNING') && T >= (S.prog.layerStart[0]?.t ?? 0) - 1 && T < S.prog.total - 2;
        showObj = true;
      }
    } else if (tr) { T = tr.T; showObj = true; target = S.pose; }
    // placa liberada no Bambuddy depois do fim (plate_wait false fora de RUNNING/PREPARE/PAUSE): a peça saiu da mesa
    if (showObj && S.msg && S.msg.plate_wait === false && !['RUNNING', 'PREPARE', 'PAUSE'].includes(S.s.gcode_state)) showObj = false;
    // suavização curtíssima da pose (esconde correções do estimador)
    const k = 1 - Math.exp(-dt / (tr && tr.locked ? 0.035 : 0.6));
    S.pose.x += (target.x - S.pose.x) * k; S.pose.y += (target.y - S.pose.y) * k; S.pose.z += (target.z - S.pose.z) * k;
    model.setPose(S.pose.x, S.pose.y, S.pose.z);
    model.setLook({ nozzleTemp: S.s.nozzle_temper ?? 25, fan: (S.s.cooling_fan_speed ?? 0) / 15 + (kind === 1 ? 0.25 : 0), printing,
      unreliable: typeof S.s.home_flag === 'number' && (S.s.home_flag & 7) !== 7 }, dt);
    object.update(T, dt, showObj && S.prog != null, printing ? 1 : 0);
    updateCamera(nowS);
    renderer.render(scene, camera);
    // adaptação de qualidade: até 2x, desce em passos de 0,25 até PR_MIN (1,25x) só com FPS baixo de verdade
    fpsAcc += dt; fpsN++;
    if (fpsAcc > 2) {
      const fps = fpsN / fpsAcc; stats.fps = fps; fpsAcc = 0; fpsN = 0;
      if (performance.now() - lastAdapt > 3000) {
        if (fps < 24 && pr > PR_MIN) { pr = Math.max(PR_MIN, pr - 0.25); renderer.setPixelRatio(pr); W = H = 0; frame(); lastAdapt = performance.now(); }
        else if (fps > 56 && pr < PR_MAX) { pr = Math.min(pr + 0.25, PR_MAX); renderer.setPixelRatio(pr); W = H = 0; frame(); lastAdapt = performance.now(); }
      }
    }
    stats.frames++;
  }

  let onScreen = true;
  function updateRunning() {
    const run = !disposed && !document.hidden && onScreen;
    stats.paused = !run;
    if (run) { lastT = performance.now(); renderer.setAnimationLoop(tick); } else renderer.setAnimationLoop(null);
  }
  const onVisibility = () => {
    if (document.hidden) disconnect(); else connect();
    updateRunning();
  };
  document.addEventListener('visibilitychange', onVisibility);
  const io = new IntersectionObserver((entries) => {
    onScreen = entries.some((e) => e.isIntersecting);
    updateRunning();
  });
  io.observe(container);
  if (!document.hidden) connect();
  updateRunning();

  const api = {
    stats,
    dispose() {
      if (disposed) return;
      disposed = true;
      renderer.setAnimationLoop(null);
      abort.abort();
      disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      io.disconnect();
      ro.disconnect();
      worker.terminate();
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('contextmenu', onCtx);
      object.dispose();
      disposeTree(scene);
      envTex.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
      if (DEBUG && window.__twin === api.debug) delete window.__twin;
    },
    debug: null,
  };

  // gancho de teste (só com debug): não cria nenhum elemento visível
  if (DEBUG) {
    api.debug = {
      THREE, model, object, S, camera, view, stats,
      feed: (msg) => onMessage(msg),
      stop: () => renderer.setAnimationLoop(null),
      step: (n = 1, T) => { if (T != null) api.debug.forceT(T); for (let i = 0; i < n; i++) { lastT = performance.now() - 50; tick(); } },
      forceT: (T) => { if (S.tracker) { S.tracker.T = T; S.tracker.corr = 0; S.tracker.locked = true; S.tracker.mode = 'running'; S.tracker.scale = 1; } },
      ready: () => object.ready,
      geom: () => S.geom,
      info: () => ({ ...renderer.info.render, geometries: renderer.info.memory.geometries }),
    };
    window.__twin = api.debug;
  }
  return api;
}

function disposeTree(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of mats) {
      for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
      m.dispose();
    }
  });
}
