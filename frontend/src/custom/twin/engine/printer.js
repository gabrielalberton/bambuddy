// Modelo procedural da Bambu Lab A1 (sem assets da Bambu): base, pilares com Z, viga X, cabeçote, mesa em Y.
// Unidades: mm. Eixos do three (Y para cima): X da impressora = x; Z da impressora = y; Y da impressora = -z (a mesa anda em z).
// Origem do mundo = CENTRO DA PLACA (área de impressão 256x256, topo da PEI em y=0), com a mesa em Y=128. O grupo `bed` tem a origem
// no centro da placa: um ponto (bx,by) da mesa está em (bx-128, 0, 128-by) no referencial local da mesa; a mesa anda em z
// (bed.position.z = Ycmd-128). A ponta do bico fica fixa em z=0: (X-128, Z, 0). Em X=128, Y=128 o bico está sobre o centro da placa.
import * as THREE from 'three';

const M = (o) => new THREE.MeshStandardMaterial(o);

function rrect(w, h, r) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}
// caixa com cantos arredondados (extrusão em z) centrada na origem
function rbox(w, h, d, r = 3, b = 1.2) {
  const g = new THREE.ExtrudeGeometry(rrect(w - 2 * b, h - 2 * b, Math.max(r - b, 0.2)), { depth: d - 2 * b, bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 2, curveSegments: 5 });
  g.translate(0, 0, -(d - 2 * b) / 2);
  return g;
}
function mesh(g, m, parent, x = 0, y = 0, z = 0, cast = true) {
  const o = new THREE.Mesh(g, m);
  o.position.set(x, y, z);
  o.castShadow = cast; o.receiveShadow = true;
  parent.add(o);
  return o;
}

function pei() {
  if (typeof document === 'undefined') return null;   // testes em Node (sem GPU/DOM)
  const c = document.createElement('canvas');
  c.width = c.height = 512;
  const g = c.getContext('2d');
  g.fillStyle = '#808080'; g.fillRect(0, 0, 512, 512);
  const im = g.getImageData(0, 0, 512, 512);
  for (let i = 0; i < im.data.length; i += 4) {
    const v = 128 + (Math.random() - 0.5) * 70;
    im.data[i] = im.data[i + 1] = im.data[i + 2] = v;
  }
  g.putImageData(im, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(10, 10);
  t.anisotropy = 4;
  return t;
}

const ROD_STEP = 37.4;   // mm: altura da face inferior da barra X acima da ponta, no STEP
const ROD_DROP = 10.4;   // mm: 37,4 (STEP) -> 27 (medido na A1 real, 26-28 mm)
export class A1Model {
  constructor() {
    this.root = new THREE.Group();
    const graphite = M({ color: 0x3b4048, roughness: 0.5, metalness: 0.2 });
    const dark = M({ color: 0x22252b, roughness: 0.65, metalness: 0.1 });
    const light = M({ color: 0xc9ccd2, roughness: 0.45, metalness: 0.2 });
    const alu = M({ color: 0xb9bdc6, roughness: 0.32, metalness: 0.9 });
    const brass = M({ color: 0xc8963e, roughness: 0.3, metalness: 1.0, emissive: 0xff5a14, emissiveIntensity: 0 });
    const rubber = M({ color: 0x0c0d0f, roughness: 0.9, metalness: 0 });
    this.mats = { graphite, dark, light, alu, brass, rubber };

    // ---- fixos: base + dois pilares de Z com travessa no topo (pórtico, como na A1 real: ver Bambu Lab A1_cover.png do Bambu Studio) ----
    // Medidas externas da especificação da Bambu (385 L x 410 P x 430 A); forma e posições dos pilares aproximadas (visual).
    // Dados oficiais do perfil do Bambu Studio: área 256x256, altura 256, extruder_clearance_height_to_rod=25 mm (bico -> haste inferior do X),
    // extruder_clearance_max_radius=73 mm.
    const fixed = new THREE.Group(); this.root.add(fixed);
    const baseX = 0;                                     // base centrada no mundo (a mesa 256 mm fica dentro)
    mesh(rbox(385, 34, 330, 10), graphite, fixed, baseX, -53, 8);
    mesh(rbox(335, 8, 292, 6), dark, fixed, baseX, -34, 8);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) mesh(new THREE.CylinderGeometry(9, 10, 8, 20), rubber, fixed, baseX + sx * 160, -74, 8 + sz * 130);
    for (const sx of [-1, 1]) mesh(new THREE.BoxGeometry(10, 8, 300), alu, fixed, sx * 104, -26, 8);   // trilhos Y
    const topY = 330;                                    // topo dos pilares (a viga chega a Z=256 + ~65 mm)
    const pillarH = topY + 36;
    this.pillars = [];
    const pillarX = 160, pillarZ = -95;                  // pilares atrás do plano do bico; a mesa passa entre eles (face interna em |x|=138)
    for (const sx of [-1, 1]) {
      const p = new THREE.Group(); p.position.set(sx * pillarX, 0, pillarZ); fixed.add(p);
      mesh(rbox(44, pillarH, 64, 6), light, p, 0, -36 + pillarH / 2, 0);
      mesh(rbox(36, 8, 56, 4), graphite, p, 0, topY + 2, 0);
      mesh(new THREE.CylinderGeometry(3.2, 3.2, pillarH - 24, 16), alu, p, 0, -36 + pillarH / 2, 33, false);   // fusos de Z (frente do pilar)
      this.pillars.push(p);
    }
    mesh(rbox(2 * pillarX - 40, 18, 40, 5), light, fixed, 0, topY + 2, pillarZ);           // travessa superior

    // ---- mesa (Y) ----
    this.bed = new THREE.Group(); this.root.add(this.bed);
    const bw = 256;
    mesh(rbox(278, 14, 278, 7), graphite, this.bed, 0, -13, 0);
    mesh(rbox(268, 4, 268, 5), dark, this.bed, 0, -4.6, 0);
    const tex = pei();
    const peiMat = M({ color: 0x6f5a34, roughness: 0.7, metalness: 0.3, roughnessMap: tex, bumpMap: tex, bumpScale: 0.6 });
    const sheet = mesh(new THREE.BoxGeometry(bw, 1.6, bw), peiMat, this.bed, 0, -0.8, 0);
    this.pei = sheet;
    sheet.castShadow = false;
    // moldura frontal clara
    mesh(rbox(120, 6, 8, 2), light, this.bed, 0, -9, 131);
    this.bedGroupOffsetZ = 0;
    // área útil de impressão (256x256 que o Bambu Studio permite): leve tom diferente do resto da PEI. Origem do `bed` = centro da placa.
    this.area = new THREE.Mesh(new THREE.PlaneGeometry(256, 256).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: 0x4fa3c7, transparent: true, opacity: 0.13, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
    this.area.position.set(0, 0.04, 0); this.area.renderOrder = 0.5; this.area.name = 'area_util'; this.bed.add(this.area);

    // ---- conjunto Z: viga + carro ----
    this.gantry = new THREE.Group(); this.root.add(this.gantry);        // y = Z (ponta do bico)
    const beamY = 48;                                                   // haste inferior a 25 mm da ponta (oficial), superior a ~43 mm
    mesh(rbox(400, 34, 40, 6), graphite, this.gantry, -22, beamY, -40);   // viga atrás do cabeçote, nas frentes dos pilares
    this.rodLow = mesh(new THREE.CylinderGeometry(3, 3, 380, 16).rotateZ(Math.PI / 2), alu, this.gantry, -12, 28, -18.5, false);   // haste inferior: base a 25 mm da ponta (oficial)
    mesh(new THREE.CylinderGeometry(3, 3, 380, 16).rotateZ(Math.PI / 2), alu, this.gantry, -12, 46, -18.5, false);
    this.sleeves = [];
    for (const sx of [-1, 1]) this.sleeves.push(mesh(rbox(44, 50, 38, 6), dark, this.gantry, sx * pillarX, beamY, -61));   // carros nos pilares
    mesh(rbox(8, 30, 36, 3), light, this.gantry, 178, beamY, -40);    // tampa da ponta da viga

    // ---- cabeçote (X): origem = ponta do bico ----
    this.head = new THREE.Group(); this.gantry.add(this.head);
    const H = this.head;
    this.headMats = [];
    const glass = (c, o = {}) => { const m = M({ color: c, roughness: 0.5, metalness: 0.15, transparent: true, ...o }); this.headMats.push(m); return m; };
    // bico
    const tip = new THREE.Mesh(new THREE.ConeGeometry(3.2, 6, 24, 1, true).rotateX(Math.PI), brass); tip.position.set(0, 3, 0); tip.castShadow = true; H.add(tip);
    mesh(new THREE.CylinderGeometry(3.4, 3.4, 6, 6), brass, H, 0, 9, 0);
    // sock de silicone + bloco
    mesh(rbox(17, 20, 22, 4), glass(0x2b2018, { roughness: 0.85 }), H, 0, 22, 0);
    // heatbreak + dissipador
    mesh(new THREE.CylinderGeometry(3.6, 3.6, 8, 16), alu, H, 0, 36, 0);
    for (let i = 0; i < 9; i++) mesh(new THREE.CylinderGeometry(12, 12, 1.3, 28), alu, H, 0, 42 + i * 2.7, 0, false);
    // dutos do ventilador de peça (arco em volta do bico)
    mesh(new THREE.TorusGeometry(13, 3, 8, 24, Math.PI * 1.45).rotateX(Math.PI / 2).rotateY(Math.PI * 0.8), glass(0xd5d8de, { roughness: 0.35 }), H, 0, 15, 0);
    // carcaça traseira
    mesh(rbox(62, 92, 30, 6), glass(0x2b2e34), H, 0, 56, -22);
    mesh(rbox(54, 24, 6, 3), glass(0x16181b), H, 0, 40, -5.5);
    // ventilador de peça (lado) + aletas girando
    this.fan = new THREE.Group(); this.fan.position.set(0, 48, -7.5); H.add(this.fan);
    mesh(new THREE.TorusGeometry(15, 1.6, 8, 28), alu, this.fan, 0, 0, 0, false);
    this.fanBlades = new THREE.Group(); this.fan.add(this.fanBlades);
    for (let i = 0; i < 7; i++) {
      const b = mesh(new THREE.BoxGeometry(12, 4.5, 0.8), dark, this.fanBlades, 0, 0, 0, false);
      b.position.set(Math.cos(i * 0.8976) * 7, Math.sin(i * 0.8976) * 7, 0); b.rotation.z = i * 0.8976 + 0.5;
    }
    mesh(new THREE.CylinderGeometry(4, 4, 2, 16).rotateX(Math.PI / 2), alu, this.fan, 0, 0, 0.5, false);
    // placa/etiqueta
    mesh(rbox(40, 14, 3, 2), glass(0xc9ccd2), H, 0, 80, -5.5);
    // patins na viga
    mesh(rbox(66, 30, 12, 4), graphite, H, 0, beamY, -26 + 6);
    this.headTransparentTarget = 1;
    this.headOpacity = 1;

    // ---- filamento depositado (brilho do bico) ----
    this.glow = new THREE.PointLight(0xff7a2a, 0, 70, 2); this.glow.position.set(0, 3, 5); H.add(this.glow);

    this.pos = { x: 40, y: 180, z: 90 };
    this.setPose(40, 180, 90);
  }

  // Modelo real (GLB do STEP "Bambulab A1 printer - Default", feito por `cad step export`; ver docs/tools/digital-twin.md).
  // Nós do assembly: NAUO1 base, NAUO2 trilho, NAUO3 tela, NAUO6 pórtico/pilares (fixos); NAUO4 mesa aquecida + NAUO5 PEI (Y);
  // NAUO7 eixo X + carros de Z (Z); NAUO8 cabeçote (X). Coordenadas medidas no STEP (mm, referencial do GLB): a ponta do bico na pose
  // "Default" está em (x=-2,23; y=8,20; z=-157,73) com "cima" = -z, frente = +y, direita = +x; topo da PEI em z=-83,80; a área de
  // impressão (256x256) é centrada na chapa quadrada (258x258) em x=0, y=0 (borda frontal em y=+128). Pose Default = X 125,77, Y 119,8, Z 73,93.
  // Mapa CAD -> mundo: (x, y, z) -> (x, -z, y) (rotação própria), com a origem de cada grupo como no procedural.
  attachCAD(scene) {
    const names = { fixed: ['NAUO1', 'NAUO2', 'NAUO3', 'NAUO6'], bed: ['NAUO4', 'NAUO5'], gantry: ['NAUO7'], head: ['NAUO8'] };
    const find = (n) => { let r = null; scene.traverse((o) => { if (!r && o.name === n) r = o; }); return r; };
    scene.updateMatrixWorld(true);
    const rot = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1);   // (x,y,z) -> (x,-z,y)
    const S = new THREE.Matrix4().makeScale(1000, 1000, 1000);                                 // GLB em metros
    const mk = (tx, ty, tz) => new THREE.Matrix4().makeTranslation(tx, ty, tz).multiply(rot).multiply(S);
    const T = {
      fixed: mk(0, -83.8, -8.2),
      bed: mk(0, -83.8, 0),
      gantry: mk(0, -157.73 - ROD_DROP, -8.2),   // barra X mais baixa: o Gabriel mediu 27 mm (ponta -> face inferior), o STEP tem 37,4
      head: mk(2.23, -157.73, -8.2),
    };
    const parents = { fixed: this.root, bed: this.bed, gantry: this.gantry, head: this.head };
    const made = {};
    for (const g of Object.keys(names)) {
      const grp = new THREE.Group(); grp.matrixAutoUpdate = false; grp.matrix.copy(T[g]); grp.name = 'a1_' + g;
      for (const n of names[g]) {
        const src = find(n); if (!src) throw new Error('STEP sem o nó ' + n);
        const c = src.clone(true); c.matrixAutoUpdate = false; c.matrix.copy(src.matrixWorld);
        c.traverse((o) => { if (o.isMesh) { o.castShadow = g !== 'bed'; o.receiveShadow = true; o.material = o.material.clone(); o.material.side = THREE.FrontSide; const c0 = o.material.color; if (Math.max(c0.r, c0.g, c0.b) > 0.6) c0.multiplyScalar(0.74); o.material.roughness = 0.55; } });
        if (n === 'NAUO5') { this.pei = c; }
        if (n === 'NAUO7') { this.rodLow = c; }
        grp.add(c);
      }
      made[g] = grp;
    }
    // esconde o procedural e monta o modelo real
    for (const grp of [this.root.children[0], ...this.bed.children.filter((c) => c !== this.area), ...this.gantry.children.filter((c) => c !== this.head)]) grp.visible = false;
    for (const c of this.head.children) if (!c.isLight) c.visible = false;
    for (const g of Object.keys(made)) parents[g].add(made[g]);
    this.headMats = [];
    // Hotend mais curto: a barra X desceu ROD_DROP (acima) e o corpo do cabeçote acompanha a barra; só a parte abaixo do fundo do corpo
    // (altura h < ROD_STEP acima da ponta) é comprimida para que a ponta continue em h=0 (referência do twin) e a haste fique a 27 mm.
    made.head.updateMatrixWorld(true);
    made.head.traverse((o) => {
      if (!o.isMesh) return;
      const M = o.matrixWorld.clone(), Mi = M.clone().invert(), v = new THREE.Vector3();
      const g = o.geometry.clone(), pa = g.attributes.position;
      for (let i = 0; i < pa.count; i++) {
        v.fromBufferAttribute(pa, i).applyMatrix4(M);
        const h = v.y;
        v.y = h <= ROD_STEP ? h * (ROD_STEP - ROD_DROP) / ROD_STEP : h - ROD_DROP;
        v.applyMatrix4(Mi); pa.setXYZ(i, v.x, v.y, v.z);
      }
      pa.needsUpdate = true; g.computeBoundingBox(); g.computeBoundingSphere(); o.geometry = g;
    });
    made.head.traverse((o) => { if (o.isMesh) { o.material.transparent = true; this.headMats.push(o.material); } });
    this.glb = true; this.cad = true;
    this.setPose(this.pos.x, this.pos.y, this.pos.z);
  }

  // Posição em coordenadas da impressora (mm): X, Y (mesa), Z
  setPose(X, Y, Z) {
    this.pos.x = X; this.pos.y = Y; this.pos.z = Z;
    this.head.position.x = X - 128;
    this.gantry.position.y = Z;
    this.bed.position.set(0, 0, Y - 128);
  }

  // Estado visual: temperatura do bico (brilho), ventoinha de peça, translucidez durante a impressão
  setLook({ nozzleTemp = 25, fan = 0, printing = false, unreliable = false }, dt) {
    const glow = Math.max(0, Math.min(1, (nozzleTemp - 160) / 70));
    this.mats.brass.emissiveIntensity += (glow * 0.9 - this.mats.brass.emissiveIntensity) * Math.min(1, dt * 3);
    this.glow.intensity = this.mats.brass.emissiveIntensity * 40;
    this.fanBlades.rotation.z -= dt * fan * 38;
    const target = printing ? 0.5 : 1;
    this.headOpacity += (target - this.headOpacity) * Math.min(1, dt * 2.2);
    for (const m of this.headMats) {
      m.opacity = this.headOpacity;
      m.depthWrite = this.headOpacity > 0.97;
      m.transparent = this.headOpacity < 0.999;
    }
    this._ghost(unreliable, dt);
  }

  // Posição não confiável (home_flag&7 != 7): cabeçote + viga X quase transparentes e avermelhados.
  // Materiais clonados por malha na primeira vez (podem ser compartilhados com a parte fixa).
  _ghost(on, dt) {
    this.ghost = this.ghost ?? 0;
    const target = on ? 1 : 0;
    if (this.ghost === 0 && target === 0) return;
    if (!this._ghostList) {
      this._ghostList = [];
      const swap = new Map();
      this.gantry.traverse((o) => {
        if (!o.isMesh || o.name === 'area_util') return;
        const old = o.material, mat = old.clone();
        swap.set(old, mat); o.material = mat;
        o.userData.ghostBase = { color: mat.color?.clone(), emissive: mat.emissive?.clone(), opacity: mat.opacity, transparent: mat.transparent, depthWrite: mat.depthWrite, isHead: this.headMats.includes(old) };
        this._ghostList.push(o);
      });
      this.headMats = this.headMats.map((m) => swap.get(m) ?? m);
    }
    this.ghost += (target - this.ghost) * Math.min(1, dt * 4);
    if (Math.abs(this.ghost - target) < 0.004) this.ghost = target;
    const g = this.ghost, red = this._red ?? (this._red = new THREE.Color(0xff3b30));
    for (const o of this._ghostList) {
      const b = o.userData.ghostBase, m = o.material;
      const base = b.isHead ? this.headOpacity : b.opacity;   // cabeçote: opacidade já ajustada (translúcido ao imprimir)
      if (b.color && m.color) m.color.copy(b.color).lerp(red, 0.75 * g);
      if (m.emissive && b.emissive) m.emissive.copy(b.emissive).lerp(red, 0.35 * g);
      m.opacity = base * (1 - g) + 0.10 * g;
      m.transparent = g > 0 || (b.isHead ? this.headOpacity < 0.999 : b.transparent);
      m.depthWrite = g > 0.001 ? false : (b.isHead ? this.headOpacity > 0.97 : b.depthWrite);
      m.needsUpdate = true;
    }
  }
}

