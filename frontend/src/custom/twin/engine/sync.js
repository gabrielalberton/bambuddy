// Estimador de posição: relatórios da A1 (sem XYZ nativo) + G-code => tempo de programa T (60 FPS, sem teletransporte).
//
// Âncoras (da mais forte para a mais fraca):
//   1. mc_print_line_number  -> linha do G-code em execução (A1 fw 01.09.00.00: vem SEMPRE "0" => nunca usada; só se algum dia vier >0 e
//      concordar com o M73, validada em tempo real e descartada se divergir). Na prática: dead reckoning entre M73/camada (~1 min).
//   2. (mc_percent, mc_remaining_time) -> linha `M73 P R` que acabou de passar
//   3. layer_num             -> linha `M991` da camada
// Modelo: T avança a (spd_mag/100)*calib seg de programa por seg real; calib é aprendido entre âncoras. Cada âncora gera
// uma correção absorvida suavemente (tau). Pausa congela; esperas (aquecimento, AMS) só terminam por evidência
// (temperatura, estágio) ou próxima âncora; antes da próxima âncora M73 ainda não vista o avanço desacelera.

const LAT = 1.0;           // s: atraso típico entre a A1 executar e nós recebermos. A A1 publica deltas em ticks fixos de ~2,06 s
                           // (atraso médio ~1,0 s, até 2+ s); backend+SSE somam < 1 ms. (Medido na impressão real de 2026-11-12.)
const RUNNING = new Set(['RUNNING', 'PREPARE']);

export class Tracker {
  constructor(prog, opts = {}) {
    this.p = prog;
    this.o = { lat: LAT, calib0: 1.01, tau: 0.5, maxCatch: 10, wLine: 1, wM73: 0.9, ...opts };
    // M73 observáveis: só onde (P,R) muda
    this.m73 = [];
    let pp = null, pr = null;
    for (const e of prog.m73) {
      if (e.p !== pp || e.r !== pr) this.m73.push(e);
      pp = e.p; pr = e.r;
    }
    this.layerEv = prog.layers;
    this.reset();
  }

  reset() {
    this.T = 0; this.locked = false; this.mode = 'idle';
    this.calib = this.o.calib0; this.speed = 1; this.scale = 0; this.corr = 0; this.tLast = null;
    this.m73i = -1; this.lastP = null; this.lastR = null; this.lastLayer = 0; this.lastLine = 0;
    this.lineT = null; this.lineTAt = 0; this.lineOk = 0; this.lineBad = 0; this.lineHist = []; this.lineTrusted = false; this.hasLine = false;
    this.lastA = null; this.unloadAt = null; this.prevAms = null; this.holdSt = new Map(); this.waiting = false; this.s = {}; this.nAnch = 0; this.finished = false;
    this.diag = { anchors: 0, snaps: 0 };
  }

  vel() { return this.speed * this.calib * this.scale; }

  // ---- entrada de estado ----
  feed(s, now, age = 0, extra = {}) {
    this.s = s;
    const gs = s.gcode_state;
    const mag = s.spd_mag ? s.spd_mag / 100 : (({ 1: .5, 2: 1, 3: 1.24, 4: 1.66 })[s.spd_lvl] || 1);
    if (this.tLast !== null) this.update(now);
    if (mag !== this.speed) this.speed = mag;
    if (gs === 'FINISH') {
      this.mode = 'finished';
      if (!this.locked) {                          // página aberta com a impressão já concluída: mostra a peça pronta, cabeçote estacionado
        this.T = this.p.total; this.corr = 0; this.locked = true; this.scale = 0; this.tLast = now; this.finished = true;
        return;
      }
      if (!this.finished) { this.finished = true; this.corr = this.p.total - this.T; }
      return;
    }
    this.finished = false;
    if (gs === 'PAUSE' || gs === 'FAILED') { this.mode = 'paused'; if (!this.locked) this.joinFromState(s, now, age, [], extra); return; }
    if (!RUNNING.has(gs)) { this.mode = 'idle'; return; }
    this.mode = 'running';
    const anchors = this.extractAnchors(s, now, age);
    if (!this.locked) {
      this.joinFromState(s, now, age, anchors, extra);
      return;
    }
    for (const a of anchors) this.applyAnchor(a, now, age);
    this.trackStage(s, now);
  }

  extractAnchors(s, now, age) {
    const out = [];
    const p = this.p;
    let usedLine = false;
    if (!this.lineBad && s.mc_print_line_number != null) {
      const L = Number(s.mc_print_line_number);
      if (L > 0) {
        this.hasLine = true;
        if (L !== this.lastLine) {
          this.lastLine = L;
          const T = p.lineToT(L);
          this.lineT = T; this.lineTAt = now;
          if (this.locked && Math.abs(T - (this.T + this.corr)) > 120) {
            // salto implausível em relação ao estimador (número de linha lixo/outra contagem): não usa e conta como falha
            this.noteLine(false);
          } else if (this.lineTrusted || this.lineOk + this.lineBad < 3) {
            out.push({ T, w: this.o.wLine, kind: 'line' });
            usedLine = this.lineTrusted;
          }
        }
      }
    }
    const P = s.mc_percent, R = s.mc_remaining_time;
    if (P != null && R != null && (P !== this.lastP || R !== this.lastR)) {
      this.lastP = P; this.lastR = R;
      const j = this.findM73(P, R);
      if (j >= 0) {
        this.m73i = j;
        const ev = this.m73[j];
        // validação do número de linha contra o M73 (um espelha o outro)
        if (this.lineT !== null && this.hasLine) {
          let est = this.lineT + (now - this.lineTAt) * this.vel();
          const hh = this.p.holdAt(this.lineT);            // parado numa espera: a linha não avança
          if (hh) est = Math.min(est, hh.t1);
          this.noteLine(Math.abs(est - ev.t) < 60);
        }
        if (!usedLine) out.push({ T: ev.t, w: this.o.wM73, kind: 'm73' });
      }
    }
    if (s.layer_num && s.layer_num !== this.lastLayer) {
      this.lastLayer = s.layer_num;
      const ev = this.layerEv.find((l) => l.n === s.layer_num);
      if (ev && !out.length) out.push({ T: ev.t, w: 0.5, kind: 'layer' });
    }
    return out;
  }

  // Confiança no número de linha por janela deslizante (últimas 6 verificações contra o M73/estimador).
  noteLine(ok) {
    if (this.lineBad >= 99) return;
    if (ok) this.lineOk++; else this.lineBad++;
    const h = this.lineHist; h.push(ok); if (h.length > 6) h.shift();
    const bad = h.filter((v) => !v).length;
    this.lineTrusted = this.lineOk >= 2 && bad <= 1;
    if (bad >= 3 || (h.length >= 4 && this.lineOk < 2 && bad >= 2)) { this.lineBad = 99; this.lineTrusted = false; this.diag.lineDistrust = true; }
  }

  findM73(P, R, hint = null) {
    const m = this.m73;
    const eq = (e) => Math.floor(e.p) === P && e.r === R;
    for (let j = this.m73i + 1; j < Math.min(m.length, this.m73i + 80); j++) if (eq(m[j])) return j;
    let best = -1, bd = 1e18;
    const ref = hint ?? this.T;
    for (let j = 0; j < m.length; j++) if (eq(m[j])) { const d = Math.abs(m[j].t - ref); if (d < bd) { bd = d; best = j; } }
    return best;
  }

  joinFromState(s, now, age, anchors = [], extra = {}) {
    const p = this.p;
    let T = null, Tm = null;
    const la = anchors.find((a) => a.kind === 'line');
    if (s.mc_percent != null && s.mc_remaining_time != null && (s.mc_percent > 0 || s.mc_remaining_time > 0 || (s.layer_num || 0) > 0)) {
      // procura todos os (P,R) iguais; desempata pela camada
      const m = this.m73;
      let cands = [];
      for (let j = 0; j < m.length; j++) if (Math.floor(m[j].p) === s.mc_percent && m[j].r === s.mc_remaining_time) cands.push(j);
      if (cands.length > 1 && s.layer_num) {
        const ls = this.layerEv.find((l) => l.n === s.layer_num);
        if (ls) cands.sort((a, b) => Math.abs(m[a].t - ls.t) - Math.abs(m[b].t - ls.t));
      }
      if (cands.length) {
        const j = cands[0];
        this.m73i = j;
        const ev = m[j], nx = m[j + 1];
        Tm = j === 0 ? ev.t : ev.t + (nx ? (nx.t - ev.t) * 0.5 : 5);
        // o backend informa há quantos segundos o (P,R) mudou pela última vez: âncora de tempo precisa para entrar no meio do job
        if (extra.sincePR != null && extra.sincePR >= 0 && extra.sincePR < 240) {
          const v = this.speed * this.calib;
          Tm = ev.t + extra.sincePR * v;
          if (nx) Tm = Math.min(Tm, nx.t - 0.5);
          this.diag.joinSincePR = extra.sincePR;
        }
        this.lastP = s.mc_percent; this.lastR = s.mc_remaining_time;
      }
    }
    if (la && this.lineBad < 4) {
      const Tl = la.T + (this.o.lat + age) * this.speed * this.calib;
      let ok = true;
      if (Tm !== null) ok = Math.abs(Tl - Tm) < 90;                       // linha x M73 devem concordar
      else if (s.layer_num) {                                               // sem M73: a linha deve cair na camada reportada
        const i = this.layerEv.findIndex((l) => l.n === s.layer_num);
        if (i >= 0) ok = Tl >= this.layerEv[i].t - 30 && (i + 1 >= this.layerEv.length || Tl <= this.layerEv[i + 1].t + 30);
      }
      if (ok) T = Tl; else { this.lineBad = 99; this.lineTrusted = false; this.diag.lineDistrust = true; }
    }
    if (T === null) T = Tm;
    if (T === null && s.layer_num) {
      const ev = this.layerEv.find((l) => l.n === s.layer_num);
      if (ev) T = ev.t + 2;
    }
    if (T === null) T = 0;
    this.T = T; this.corr = 0; this.locked = true; this.scale = (this.mode === 'running') ? 1 : 0;
    this.tLast = now; this.lastA = null; this.nAnch++;
    if (s.layer_num) this.lastLayer = s.layer_num;
    if (la) this.lastLine = Number(s.mc_print_line_number);
    this.diag.joinT = T;
  }

  holdBetween(T1, T2) {
    for (const h of this.p.holds) if (h.t0 < T2 && h.t1 > T1) return true;
    return false;
  }

  applyAnchor(a, now, age) {
    this.diag.anchors++;
    const v = this.speed * this.calib;
    const Tobs = a.T + (this.o.lat + age) * v;
    const cur = this.T + this.corr;
    // aprendizado do fator de velocidade entre âncoras fortes
    if (a.kind !== 'layer') {
      if (this.lastA && now - this.lastA.now >= 10) {
        if (!this.holdBetween(this.lastA.T, a.T) && this.mode === 'running' && !this.lastA.paused) {
          const meas = (Tobs - this.lastA.T) / (now - this.lastA.now);
          const ratio = meas / this.speed;
          if (ratio > 0.3 && ratio < 3) this.calib = Math.min(2, Math.max(0.4, this.calib + 0.25 * (ratio - this.calib)));
        }
        this.lastA = { T: Tobs, now, paused: false };
      } else if (!this.lastA) this.lastA = { T: Tobs, now, paused: false };
    }
    const err = Tobs - cur;
    if (Math.abs(err) > 150) { this.T = Tobs; this.corr = 0; this.diag.snaps++; return; }
    // não corrija "para trás" mais que 2 s dentro de uma espera estacionária
    this.corr += err * a.w;
  }

  trackStage(s, now) {
    const h = this.p.holdAt(this.T);
    if (h) {
      let st = this.holdSt.get(h);
      if (!st) { st = { enter: now, seen: false }; this.holdSt.set(h, st); }
      if (s.stg_cur === 4) st.seen = true;
    }
    // Troca de filamento no AMS (impressão real): ams_status 258/259 -> 260 -> 261 (+tray_now=255, recolhido) -> 262 -> tray_now=<novo>
    // (carregado) -> 258 -> 263 (purga) -> 768 (M621 concluído). stg_cur NÃO muda durante a impressão.
    const tn = s.ams && s.ams.tray_now != null ? Number(s.ams.tray_now) : null;
    if (tn === 255) this.unloadAt = now;
    const as = s.ams_status != null ? Number(s.ams_status) : null;
    if (as === 259 && this.prevAms !== 259 && this.mode === 'running') {
      // início real de uma troca: alinha o relógio ao início do hold 'ams' mais próximo à frente (até 40 s)
      const T = this.T + this.corr;
      const nh = this.p.holds.find((x) => x.s === 'ams' && x.t0 > T - 3 && x.t0 < T + 40);
      if (nh && T < nh.t0 + 6) { this.corr = nh.t0 + 2 + this.o.lat * this.speed - T; this.diag.amsAlign = (this.diag.amsAlign || 0) + 1; }
    }
    if (as === 768 && this.prevAms !== null && this.prevAms !== 768 && this.mode === 'running') {
      // fim real da troca (M621 concluído): âncora no M621 mais próximo do relógio atual
      const T = this.T + this.corr;
      let best = null;
      for (const w of this.p.swaps) if (w.c === 'M621' && Math.abs(w.t - T) < 80 && (!best || Math.abs(w.t - T) < Math.abs(best.t - T))) best = w;
      if (best) { this.applyAnchor({ T: best.t, w: 0.9, kind: 'm621' }, now, 0); this.diag.m621 = (this.diag.m621 || 0) + 1; }
    }
    this.prevAms = as;
    if (this.holdSt.size > 64) this.holdSt.clear();
  }

  released(h, now) {
    const s = this.s;
    const st = this.holdSt.get(h) || { enter: now, seen: false };
    switch (h.s) {
      case 'heat_n': {
        const t = s.nozzle_temper;
        if (t == null) return null;
        // espera de "resfriar" enquanto o alvo reportado ainda é maior (ex.: M109 S25 H140 no início): sem evidência, segue o tempo nominal
        if (h.dir < 0 && s.nozzle_target_temper != null && s.nozzle_target_temper > h.a + 10) return null;
        if (now - st.enter > 6 * (h.t1 - h.t0) + 60) return true;                // teto de segurança
        return h.dir >= 0 ? t >= h.a - 3 : t <= h.a + 4;
      }
      case 'heat_b': {
        const t = s.bed_temper;
        if (t == null) return null;
        if (h.dir < 0 && s.bed_target_temper != null && s.bed_target_temper > h.a + 10) return null;
        if (now - st.enter > 6 * (h.t1 - h.t0) + 60) return true;
        return h.dir >= 0 ? t >= h.a - 2 : t <= h.a + 3;
      }
      case 'ams': {
        if (st.seen && s.stg_cur !== 4) return true;                       // pré-aquecimento (stg_cur 4)
        const tn = s.ams && s.ams.tray_now != null ? Number(s.ams.tray_now) : null;
        if (tn !== null && tn === h.a && this.unloadAt != null && this.unloadAt >= st.enter - 90 && now - this.unloadAt < 120) return true;   // carregou o novo
        return now - st.enter > 90;
      }
      default:
        return null; // sem evidência: deixa correr no tempo nominal
    }
  }

  // ---- a cada frame ----
  update(now) {
    if (this.tLast === null) { this.tLast = now; return this.T; }
    const dt = Math.min(Math.max(now - this.tLast, 0), 0.25);
    this.tLast = now;
    if (!this.locked) return this.T;
    const target = this.mode === 'running' ? 1 : 0;
    this.scale += (target - this.scale) * (1 - Math.exp(-dt / 0.25));
    if (Math.abs(this.scale - target) < 0.002) this.scale = target;
    let v = this.vel();
    // desacelera ao chegar na próxima âncora M73 ainda não vista (sem linha confiável)
    if (!this.lineTrusted && this.mode === 'running') {
      const nx = this.m73[this.m73i + 1];
      if (nx && this.T > nx.t - 1.0) v *= Math.max(0.04, Math.min(1, (nx.t + 1.2 - this.T) / 2.2));
    }
    this.T += v * dt;
    if (this.corr !== 0) {
      let step = this.corr * (1 - Math.exp(-dt / this.o.tau));
      // correção por velocidade limitada (alcança sem arrastar e sem salto): ±0,25x + 0,5x por segundo de erro, até maxCatch
      const lim = (this.mode === 'finished' ? 60 : Math.min(this.o.maxCatch, 0.25 + 0.5 * Math.abs(this.corr))) * dt;
      if (Math.abs(step) > lim) step = Math.sign(step) * lim;
      this.T += step; this.corr -= step;
      if (Math.abs(this.corr) < 1e-3) this.corr = 0;
    }
    this.T = Math.min(Math.max(this.T, 0), this.p.total);
    // esperas
    this.waiting = false;
    const h = this.p.holdAt(this.T);
    if (h && this.mode === 'running') {
      const rel = this.released(h, now);
      if (rel === true) this.T = h.t1;
      else if (rel === false) { this.waiting = true; if (this.T > h.t1 - 0.03) this.T = h.t1 - 0.03; }
    }
    return this.T;
  }
}
