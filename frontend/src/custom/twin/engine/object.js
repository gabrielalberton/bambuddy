// Objeto impresso: já impresso = opaco na cor do filamento; o que falta = fantasma quase invisível.
// Um BufferGeometry (atributos compartilhados) vira 3 draws: impresso (opaco), pré-passe de profundidade do fantasma
// (só a superfície mais próxima contribui) e fantasma (alpha baixíssimo). `uNow` (tempo de programa) recorta por pixel.
import * as THREE from 'three';

const NPAL = 16;
const HOT_S = 3.0; // s de programa com brilho na ponta da linha

function patch(shader, mode, uniforms) {
  Object.assign(shader.uniforms, uniforms);
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nattribute float aT;\nattribute float aF;\nvarying float vT;\nvarying float vF;')
    .replace('#include <begin_vertex>', '#include <begin_vertex>\nvT = aT; vF = aF;');
  let frag = shader.fragmentShader.replace('#include <common>', `#include <common>
uniform float uNow;
uniform vec3 uPal[${NPAL}];
uniform float uGhostA;
uniform float uHot;
varying float vT;
varying float vF;`);
  if (mode === 'printed') {
    frag = frag.replace('vec4 diffuseColor = vec4( diffuse, opacity );', 'if (vT > uNow) discard;\nvec4 diffuseColor = vec4( uPal[int(vF + 0.5)], opacity );');
    // linha recém-extrudada (últimos HOT_S s de programa): brilho quente que esfria, para ver o filete sendo depositado
    frag = frag.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
float hot = uHot * clamp(1.0 - (uNow - vT) / ${HOT_S.toFixed(1)}, 0.0, 1.0);
totalEmissiveRadiance += vec3(1.0, 0.42, 0.12) * hot * hot * 1.6;`);
  } else if (mode === 'ghost') {
    frag = frag.replace('vec4 diffuseColor = vec4( diffuse, opacity );', 'if (vT <= uNow) discard;\nvec4 diffuseColor = vec4( mix(uPal[int(vF + 0.5)], vec3(0.55, 0.62, 0.72), 0.55), uGhostA );');
  }
  shader.fragmentShader = frag;
}

export class PrintedObject {
  constructor(palette) {
    this.group = new THREE.Group();
    this.uNow = { value: 0 };
    this.uPal = { value: Array.from({ length: NPAL }, () => new THREE.Color(0xdddddd)) };
    this.uGhostA = { value: 0.045 };
    this.uHot = { value: 0 };
    this.ready = false;
    this.fade = 0;
    this.setPalette(palette || []);
    this.drawn = { p: -1, g: -1 };
  }

  setPalette(cols) {
    for (let i = 0; i < NPAL; i++) {
      const c = cols[i];
      if (c) this.uPal.value[i].set(c);
    }
  }

  // r = resposta do worker
  build(r) {
    this.dispose();
    const mk = () => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(r.pos, 3));
      g.setAttribute('normal', new THREE.BufferAttribute(r.nor, 3, true));
      g.setAttribute('aT', new THREE.BufferAttribute(r.aT, 1));
      g.setAttribute('aF', new THREE.BufferAttribute(r.aF, 1));
      g.setIndex(new THREE.BufferAttribute(r.idx, 1));
      g.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 60, -128), 400);
      return g;
    };
    this.r = r;
    this.gP = mk();
    this.gG = mk();
    const u = { uNow: this.uNow, uPal: this.uPal, uGhostA: this.uGhostA, uHot: this.uHot };
    const printedMat = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.02, side: THREE.DoubleSide });
    printedMat.onBeforeCompile = (s) => patch(s, 'printed', u);
    printedMat.customProgramCacheKey = () => 'printed';
    // transparent:true -> fila transparente (renderOrder 1, depois do cabeçote translúcido): o depth do futuro só vale para o fantasma e não
    // esconde mais partes translúcidas do cabeçote que ficam dentro do volume da peça.
    const preMat = new THREE.MeshBasicMaterial({ transparent: true, colorWrite: false, depthWrite: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    preMat.onBeforeCompile = (s) => {
      Object.assign(s.uniforms, u);
      s.vertexShader = s.vertexShader.replace('#include <common>', '#include <common>\nattribute float aT;\nvarying float vT;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvT = aT;');
      s.fragmentShader = s.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uNow;\nvarying float vT;').replace('void main() {', 'void main() {\nif (vT <= uNow) discard;');
    };
    preMat.customProgramCacheKey = () => 'pre';
    const ghostMat = new THREE.MeshStandardMaterial({ roughness: 0.6, metalness: 0, transparent: true, depthWrite: false, side: THREE.DoubleSide, depthFunc: THREE.LessEqualDepth });
    ghostMat.onBeforeCompile = (s) => patch(s, 'ghost', u);
    ghostMat.customProgramCacheKey = () => 'ghost';
    this.printed = new THREE.Mesh(this.gP, printedMat);
    this.pre = new THREE.Mesh(this.gG, preMat);
    this.ghost = new THREE.Mesh(this.gG, ghostMat);
    for (const m of [this.printed, this.pre, this.ghost]) { m.frustumCulled = false; this.group.add(m); }
    this.printed.renderOrder = 0; this.pre.renderOrder = 1; this.ghost.renderOrder = 2;
    this.ghost.visible = this.pre.visible = true;
    this.ready = true;
    this.drawn = { p: -1, g: -1 };
  }

  // maior i tal que arr[i] <= v (-1 se nenhum)
  static ub(arr, n, v) {
    let lo = 0, hi = n - 1, k = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (arr[mid] <= v) { k = mid; lo = mid + 1; } else hi = mid - 1; }
    return k;
  }

  // hot = 0..1: brilho da ponta (só imprimindo; parado/terminado a peça fica na cor do filamento)
  update(T, dt, show = true, hot = 0) {
    if (!this.ready) return;
    this.uHot.value += (hot - this.uHot.value) * Math.min(1, dt * 2);
    this.uNow.value = T;
    const r = this.r;
    const n = r.nStrands;
    // impresso: strands com início <= T ; fantasma: strands cujo fim >= T
    const kp = PrintedObject.ub(r.sT0, n, T) + 1;           // nº de strands com t0 <= T
    const kg = PrintedObject.ub(r.sT1, n, T - 1e-4) + 1;    // 1º strand com t1 >= T
    const pEnd = r.sIdx[Math.min(kp, n)];
    const gStart = r.sIdx[Math.min(kg, n)];
    if (pEnd !== this.drawn.p) { this.gP.setDrawRange(0, pEnd); this.drawn.p = pEnd; }
    if (gStart !== this.drawn.g) { this.gG.setDrawRange(gStart, r.sIdx[n] - gStart); this.drawn.g = gStart; }
    this.printed.visible = pEnd > 0;
    this.pre.visible = this.ghost.visible = gStart < r.sIdx[n];
    this.fade += ((show ? 1 : 0) - this.fade) * Math.min(1, dt * 3);
    this.group.visible = this.fade > 0.01;
    this.uGhostA.value = 0.045 * Math.min(1, this.fade);
  }

  dispose() {
    for (const m of [this.printed, this.pre, this.ghost]) if (m) { this.group.remove(m); }
    for (const g of [this.gP, this.gG]) g && g.dispose();
    this.printed = this.pre = this.ghost = this.gP = this.gG = null;
    this.ready = false;
  }
}
