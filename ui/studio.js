/* 自定义特效壁纸 · 工坊（预览 / 调参 / 保存 / 应用）
   预览用 Canvas 复刻引擎里的粒子算法，参数走后端写 JSON，引擎按 --scene 播放。 */
(function () {
  'use strict';

  const q = (s) => document.querySelector(s);

  const KINDS = [
    { k: 'rain', label: '雨丝', angle: true,
      def: { count: 200, size: 1, speed: 1, alpha: 0.55, color: '#a8c8ff', angle: 12 } },
    { k: 'snow', label: '飘雪',
      def: { count: 140, size: 1, speed: 0.9, alpha: 0.85, color: '#ffffff' } },
    { k: 'petal', label: '花瓣',
      def: { count: 60, size: 1, speed: 1, alpha: 0.9, color: '#ffc0d4' } },
    { k: 'firefly', label: '萤火虫',
      def: { count: 40, size: 1, speed: 1, alpha: 0.95, color: '#ffe08a' } },
    { k: 'bubble', label: '气泡',
      def: { count: 50, size: 1, speed: 1, alpha: 0.55, color: '#d9f4ff' } },
    { k: 'ember', label: '火星',
      def: { count: 60, size: 1, speed: 1, alpha: 0.9, color: '#ff9a4d' } },
    { k: 'star', label: '星光',
      def: { count: 80, size: 1, speed: 1, alpha: 0.9, color: '#ffffff' } },
    { k: 'leaf', label: '落叶',
      def: { count: 40, size: 1, speed: 1, alpha: 0.95, color: '#e0a556' } },
    { k: 'aurora', label: '极光',
      def: { count: 90, size: 1.6, speed: 0.6, alpha: 0.22, color: '#5cf0c8' } },
    { k: 'bokeh', label: '光斑',
      def: { count: 26, size: 1.8, speed: 0.35, alpha: 0.3, color: '#ffd9a0' } },
    { k: 'warp', label: '星空穿越',
      def: { count: 150, size: 1, speed: 1, alpha: 0.85, color: '#cfe3ff' } },
    { k: 'meteor', label: '流星', angle: true,
      def: { count: 14, size: 1, speed: 1, alpha: 0.95, color: '#ffffff', angle: 32 } }
  ];
  const POS = [['lt', '左上'], ['ct', '中上'], ['rt', '右上'],
               ['lc', '左中'], ['cc', '居中'], ['rc', '右中'],
               ['lb', '左下'], ['cb', '中下'], ['rb', '右下']];

  function DEF() {
    const fx = {};
    KINDS.forEach((K) => { fx[K.k] = Object.assign({ on: false }, K.def); });
    fx.rain.on = true;                 // 新场景默认带一层雨，进来就能看到效果
    return {
      id: '', name: '我的特效壁纸',
      bg: { type: 'color', src: '', name: '', color: '#0b1020', color2: '#243b6b', motion_speed: 1 },
      fx,
      glow: { on: false, size: 360, alpha: 0.35, color: '#ffd27a' },
      ripple: { on: true, size: 520, alpha: 0.55, color: '#ffffff' },
      clock: { on: false, pos: 'lt', size: 56, color: '#ffffff', alpha: 0.92, seconds: false, only_time: false },
      text: { on: false, value: '', pos: 'lb', size: 26, color: '#ffffff', alpha: 0.9 }
    };
  }

  let ST = DEF();
  let LIB = [];
  let SCENES = [];
  let RUN = { running: false, name: '' };
  let active = false;

  /* ---------------------------------------------------------- 预览引擎 */
  const PV = {
    cvs: null, ctx: null, W: 1280, H: 720, sc: 1, dpr: 1,
    parts: {}, sig: {}, t: 0, last: 0, raf: 0,
    ripples: [], mx: -999, my: -999, spr: {}
  };

  const hex2rgb = (h) => {
    h = String(h || '#ffffff').replace('#', '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = parseInt(h || 'ffffff', 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const rgba = (c, a) => { const [r, g, b] = hex2rgb(c); return `rgba(${r},${g},${b},${a})`; };
  const rnd = (a, b) => a + Math.random() * (b - a);

  function spriteDot(color, power, size) {
    const key = 'd' + color + power + size;
    if (PV.spr[key]) return PV.spr[key];
    const S = size || 128, c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    const [r, gg, b] = hex2rgb(color);
    for (let i = 0; i <= 10; i++) {
      const t = i / 10;
      grd.addColorStop(t, `rgba(${r},${gg},${b},${Math.pow(1 - t, power).toFixed(3)})`);
    }
    g.fillStyle = grd;
    g.fillRect(0, 0, S, S);
    PV.spr[key] = c;
    return c;
  }

  function spriteSpark(color) {
    const key = 's' + color;
    if (PV.spr[key]) return PV.spr[key];
    const S = 64, c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    g.translate(S / 2, S / 2);
    g.fillStyle = rgba(color, 0.95);
    for (let i = 0; i < 4; i++) {
      g.save(); g.rotate((Math.PI / 2) * i);
      g.beginPath();
      g.moveTo(0, -S / 2); g.lineTo(1.6, 0); g.lineTo(0, S / 2); g.lineTo(-1.6, 0);
      g.closePath(); g.fill();
      g.restore();
    }
    const grd = g.createRadialGradient(0, 0, 0, 0, 0, 7);
    grd.addColorStop(0, rgba(color, 1));
    grd.addColorStop(1, rgba(color, 0));
    g.fillStyle = grd;
    g.beginPath(); g.arc(0, 0, 7, 0, 7); g.fill();
    PV.spr[key] = c;
    return c;
  }

  function spriteStreak(color) {
    const key = 'r' + color;
    if (PV.spr[key]) return PV.spr[key];
    const W = 24, H = 160, c = document.createElement('canvas');
    c.width = W; c.height = H;
    const g = c.getContext('2d');
    const [r, gg, b] = hex2rgb(color);
    const grd = g.createLinearGradient(0, 0, 0, H);
    grd.addColorStop(0, `rgba(${r},${gg},${b},0)`);
    grd.addColorStop(0.4, `rgba(${r},${gg},${b},0.9)`);
    grd.addColorStop(0.78, `rgba(${r},${gg},${b},0.55)`);
    grd.addColorStop(1, `rgba(${r},${gg},${b},0)`);
    g.fillStyle = grd;
    try { g.filter = 'blur(1.4px)'; } catch (e) {}
    g.fillRect(W / 2 - 1.4, 0, 2.8, H);
    PV.spr[key] = c;
    return c;
  }

  function spritePetal(color, slim) {
    const key = 'p' + color + (slim ? 's' : '');
    if (PV.spr[key]) return PV.spr[key];
    const S = 64, c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(S / 2, S / 2, 1, S / 2, S / 2, S / 2);
    grd.addColorStop(0, rgba(color, 1));
    grd.addColorStop(0.75, rgba(color, 0.92));
    grd.addColorStop(1, rgba(color, 0));
    g.fillStyle = grd;
    g.beginPath();
    g.ellipse(S / 2, S / 2, S * 0.46, S * (slim ? 0.16 : 0.24), 0, 0, 7);
    g.fill();
    PV.spr[key] = c;
    return c;
  }

  function spawn(K, s, p, first) {
    const W = PV.W, H = PV.H, k = K.k;
    p.ph = Math.random() * 6.283;
    p.dir = Math.random() * 6.283;
    p.spin = rnd(-2, 2);
    if (k === 'rain') {
      p.x = rnd(-0.06 * W, W * 1.06);
      p.y = first ? rnd(-H, H) : rnd(-H * 0.4, -20);
      const v = rnd(0.75, 1.35);
      p.vy = v; p.vx = v * Math.tan((+s.angle || 12) * Math.PI / 180);
      p.s = rnd(0.7, 1.5);
    } else if (k === 'snow' || k === 'petal' || k === 'leaf') {
      p.x = rnd(-0.03 * W, W * 1.03);
      p.y = first ? rnd(0, H) : -30;
      p.vy = rnd(0.18, 0.42);
      p.vx = 0;
      p.s = rnd(0.6, 1.5);
    } else if (k === 'firefly') {
      p.x = rnd(0, W); p.y = first ? rnd(0, H) : rnd(0, H);
      p.vx = rnd(-14, 14); p.vy = rnd(-14, 14); p.s = rnd(0.6, 1.5);
    } else if (k === 'ember') {
      p.x = rnd(0, W); p.y = first ? rnd(0, H) : H + 20;
      p.vx = rnd(-8, 8); p.vy = rnd(-26, -10); p.s = rnd(0.6, 1.5);
    } else if (k === 'bubble') {
      p.x = rnd(0, W); p.y = first ? rnd(0, H) : H + 20;
      p.vx = rnd(-6, 6); p.vy = rnd(-90, -40); p.s = rnd(0.5, 1.4);
    } else if (k === 'star') {
      p.x = rnd(0, W); p.y = rnd(0, H);
      p.vx = p.vy = 0; p.s = rnd(0.35, 1.1); p.spin = rnd(0.4, 2);
    } else if (k === 'aurora') {
      p.x = rnd(-0.2 * W, W * 1.2); p.b = rnd(H * 0.1, H * 0.68); p.y = p.b;
      p.s = rnd(0.7, 1.7); p.spin = rnd(0.22, 0.78);
      p.vx = rnd(8, 30) * (Math.random() < 0.5 ? -1 : 1); p.vy = 0;
    } else if (k === 'bokeh') {
      p.x = rnd(-40, W + 40); p.y = first ? rnd(0, H) : H + 70;
      p.vy = rnd(-30, -8); p.vx = rnd(-12, 12); p.s = rnd(0.5, 1.9);
    } else if (k === 'warp') {
      p.a = Math.random() * 6.283;
      p.r = first ? rnd(0, Math.max(W, H) * 0.55) : rnd(0, 24);
      p.s = rnd(0.6, 1.6); p.vx = p.vy = 0;
    } else if (k === 'meteor') {
      p.x = rnd(-0.4 * W, W * 0.85);
      p.y = first ? rnd(-H * 0.6, H) : rnd(-H * 0.5, -40);
      const v = rnd(0.55, 1.15);
      p.vy = v; p.vx = v * Math.tan((+s.angle || 32) * Math.PI / 180);
      p.s = rnd(0.7, 1.6);
    }
  }

  function spawnAll() {
    PV.parts = {}; PV.sig = {};
    fxList().forEach(({ K, s }) => {
      const arr = [];
      const n = Math.max(0, Math.min(400, +s.count || 0));
      for (let i = 0; i < n; i++) { const p = {}; spawn(K, s, p, true); arr.push(p); }
      PV.parts[K.k] = arr;
      PV.sig[K.k] = sigOf(s, K);
    });
  }

  const sigOf = (s, K) => [s.count, s.size, s.speed, s.alpha, s.color, s.angle].join('|');

  function fxList() {
    const out = [];
    KINDS.forEach((K) => { const s = ST.fx[K.k]; if (s && s.on && +s.count > 0) out.push({ K, s }); });
    return out;
  }

  function syncParts() {
    const live = {};
    fxList().forEach(({ K, s }) => {
      live[K.k] = 1;
      const sig = sigOf(s, K);
      if (PV.sig[K.k] !== sig) {
        PV.sig[K.k] = sig;
        const arr = [];
        const n = Math.max(0, Math.min(400, +s.count || 0));
        for (let i = 0; i < n; i++) { const p = {}; spawn(K, s, p, true); arr.push(p); }
        PV.parts[K.k] = arr;
      }
    });
    Object.keys(PV.parts).forEach((k) => { if (!live[k]) { delete PV.parts[k]; delete PV.sig[k]; } });
  }

  function step(dt) {
    const W = PV.W, H = PV.H, sc = PV.sc;
    fxList().forEach(({ K, s }) => {
      const arr = PV.parts[K.k]; if (!arr) return;
      const sp = +s.speed || 1, k = K.k;
      for (let i = 0; i < arr.length; i++) {
        const p = arr[i];
        if (k === 'rain') {
          p.x += p.vx * 1500 * sp * dt; p.y += p.vy * 1500 * sp * dt;
          if (p.y > H + 60 || p.x > W + 160 || p.x < -160) spawn(K, s, p, false);
        } else if (k === 'snow' || k === 'petal' || k === 'leaf') {
          p.ph += dt * (k === 'snow' ? 1.6 : 1.1) * sp;
          p.x += Math.sin(p.ph) * (k === 'snow' ? 26 : 44) * sp * dt;
          p.y += p.vy * 160 * sp * dt;
          if (k !== 'snow') p.dir += p.spin * dt;
          if (p.y > H + 40 || p.x < -60 || p.x > W + 60) spawn(K, s, p, false);
        } else if (k === 'firefly') {
          p.ph += dt * 1.3 * sp;
          p.x += (p.vx + Math.sin(p.ph * 0.7) * 30) * sp * dt;
          p.y += (p.vy + Math.cos(p.ph * 0.9) * 26) * sp * dt;
          if (p.x < -20) p.x = W + 20; else if (p.x > W + 20) p.x = -20;
          if (p.y < -20) p.y = H + 20; else if (p.y > H + 20) p.y = -20;
        } else if (k === 'ember') {
          p.ph += dt * 2.4 * sp;
          p.x += (p.vx + Math.sin(p.ph) * 16) * sp * dt;
          p.y += p.vy * sp * dt;
          if (p.y < -30) spawn(K, s, p, false);
        } else if (k === 'bubble') {
          p.ph += dt * 1.4 * sp;
          p.x += (p.vx + Math.sin(p.ph) * 12) * sp * dt;
          p.y += p.vy * sp * dt;
          if (p.y < -40) spawn(K, s, p, false);
        } else if (k === 'star') {
          p.ph += dt * p.spin * sp;
        } else if (k === 'aurora') {
          p.ph += dt * p.spin * sp;
          p.x += p.vx * sp * dt;
          p.y = p.b + Math.sin(p.ph) * H * 0.05;
          if (p.x < -W * 0.35) p.x = W * 1.35; else if (p.x > W * 1.35) p.x = -W * 0.35;
        } else if (k === 'bokeh') {
          p.ph += dt * 0.65 * sp;
          p.x += (p.vx + Math.sin(p.ph) * 16) * sp * dt;
          p.y += p.vy * sp * dt;
          if (p.y < -100) spawn(K, s, p, false);
        } else if (k === 'warp') {
          p.r += (40 + p.r * 1.2) * sp * dt;
          if (p.r > Math.hypot(W, H) * 0.64) {
            p.a = Math.random() * 6.283; p.r = rnd(0, 24); p.s = rnd(0.6, 1.6);
          }
        } else if (k === 'meteor') {
          p.x += p.vx * 900 * sp * dt; p.y += p.vy * 900 * sp * dt;
          if (p.y > H + 200 || p.x > W + 400) spawn(K, s, p, false);
        }
      }
    });
  }

  function draw(g) {
    const sc = PV.sc;
    fxList().forEach(({ K, s }) => {
      const arr = PV.parts[K.k]; if (!arr) return;
      const k = K.k, A = +s.alpha, sizeF = +s.size || 1, col = s.color;
      if (k === 'rain') {
        const spr = spriteStreak(col);
        const w = 9 * sizeF * sc * 2, h = 74 * sizeF * sc;
        const rot = -(+(s.angle) || 12) * Math.PI / 180;
        for (const p of arr) {
          g.save(); g.translate(p.x, p.y); g.rotate(rot);
          g.globalAlpha = A * 0.75 * Math.min(1.2, p.s);
          g.drawImage(spr, -w / 2, -h / 2, w, h);
          g.restore();
        }
      } else if (k === 'snow') {
        const spr = spriteDot(col, 1.8, 96);
        for (const p of arr) {
          const d = 26 * p.s * sizeF * sc;
          g.globalAlpha = A * (0.55 + 0.45 * Math.sin(p.ph) ** 2);
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'petal' || k === 'leaf') {
        const spr = spritePetal(col, k === 'leaf');
        for (const p of arr) {
          const d = 34 * p.s * sizeF * sc;
          g.save(); g.translate(p.x, p.y); g.rotate(p.dir);
          g.globalAlpha = A;
          g.drawImage(spr, -d / 2, -d / 2, d, d * 0.9);
          g.restore();
        }
      } else if (k === 'firefly') {
        const spr = spriteSpark(col);
        for (const p of arr) {
          const d = 30 * p.s * sizeF * sc;
          g.globalAlpha = A * (0.25 + 0.75 * (0.5 + 0.5 * Math.sin(p.ph * 1.7)) ** 1.5);
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'ember') {
        const spr = spriteDot(col, 2.2, 64);
        for (const p of arr) {
          const d = 16 * p.s * sizeF * sc;
          g.globalAlpha = A * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(p.ph * 2.6)));
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'bubble') {
        const spr = spriteDot(col, 1.8, 96);
        for (const p of arr) {
          const d = 30 * p.s * sizeF * sc;
          g.globalAlpha = Math.max(0.05, A * (0.45 + 0.35 * Math.sin(p.ph)));
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'star') {
        const spr = spriteSpark(col);
        for (const p of arr) {
          const d = 16 * p.s * sizeF * sc;
          g.globalAlpha = A * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(p.ph)) ** 2);
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'aurora') {
        const spr = spriteDot(col, 3, 160);
        for (const p of arr) {
          const d = 360 * p.s * sizeF * sc, dw = d * 0.42, dh = d * 1.5;
          g.globalAlpha = Math.max(0.02, A * Math.max(0, 0.45 + 0.55 * Math.sin(p.ph * 0.8)) ** 1.2);
          g.drawImage(spr, p.x - dw / 2, p.y - dh / 2, dw, dh);
        }
      } else if (k === 'bokeh') {
        const spr = spriteDot(col, 3, 160);
        for (const p of arr) {
          const d = 150 * p.s * sizeF * sc;
          g.globalAlpha = Math.max(0.02, A * (0.55 + 0.45 * Math.sin(p.ph * 1.4)));
          g.drawImage(spr, p.x - d / 2, p.y - d / 2, d, d);
        }
      } else if (k === 'warp') {
        const spr = spriteDot(col, 2, 64);
        for (const p of arr) {
          const ca = Math.cos(p.a), sa = Math.sin(p.a) * 0.78;
          const cx = W * 0.5, cy = H * 0.5;
          const a0 = A * Math.min(1, p.r / 110);
          for (let j = 0; j < 6; j++) {
            const f = j / 6, rr = p.r - f * (6 + p.r * 0.075);
            if (rr <= 0) break;
            const d = Math.max(2, (7 + p.r * 0.038) * p.s * sizeF * sc * (1 - f * 0.25));
            g.globalAlpha = a0 * (1 - f * 0.42);
            g.drawImage(spr, cx + ca * rr - d / 2, cy + sa * rr - d / 2, d, d);
          }
        }
      } else if (k === 'meteor') {
        const spr = spriteStreak(col);
        for (const p of arr) {
          const w = 24 * 1.1 * p.s * sizeF * sc, h = 160 * 2.6 * p.s * sizeF * sc;
          g.globalAlpha = A * 0.62;
          g.drawImage(spr, p.x - w / 2, p.y - h / 2, w, h);
          const d = 22 * p.s * sizeF * sc;
          g.globalAlpha = A;
          g.drawImage(spriteSpark(col), p.x - d / 2, p.y - d / 2, d, d);
        }
      }
    });
    g.globalAlpha = 1;
  }

  function drawOverlay(g, t) {
    const sc = PV.sc;
    // 涟漪
    for (let i = PV.ripples.length - 1; i >= 0; i--) {
      const r = PV.ripples[i];
      r.t += 1 / 60;
      if (r.t > 1.35) { PV.ripples.splice(i, 1); continue; }
      const kk = r.t / 1.35;
      const rad = (60 + (ST.ripple.size - 60) * Math.pow(kk, 0.55)) / 2 * sc;
      g.globalAlpha = ST.ripple.alpha * Math.pow(1 - kk, 1.6);
      g.strokeStyle = ST.ripple.color;
      g.lineWidth = Math.max(1, 3 * sc * (1 - kk) + 0.6);
      g.beginPath(); g.arc(r.x, r.y, rad, 0, 7); g.stroke();
    }
    g.globalAlpha = 1;

    // 鼠标光晕
    if (ST.glow.on && PV.mx > -900) {
      const d = ST.glow.size * sc * (1 + 0.04 * Math.sin(t * 1.6));
      const spr = spriteDot(ST.glow.color, 3, 192);
      g.globalAlpha = ST.glow.alpha;
      g.drawImage(spr, PV.mx - d / 2, PV.my - d / 2, d, d);
      g.globalAlpha = 1;
    }

    // 时钟 / 文字
    const now = new Date();
    if (ST.clock.on) {
      const p = String(Math.floor(ST.clock.size * sc)) + 'px';
      const pad = 0.9 * ST.clock.size * sc;
      const l1 = String(now.getHours()).padStart(2, '0') + ':' +
        String(now.getMinutes()).padStart(2, '0') +
        (ST.clock.seconds ? ':' + String(now.getSeconds()).padStart(2, '0') : '');
      const wd = '日一二三四五六'[now.getDay()];
      const l2 = (now.getMonth() + 1) + '月' + now.getDate() + '日 周' + wd;
      const lines = ST.clock.only_time ? [l1] : [l1, l2];
      drawText(g, lines, p, ST.clock.color, ST.clock.alpha, ST.clock.pos, pad, sc);
    }
    if (ST.text.on && ST.text.value.trim()) {
      const p = String(Math.floor(ST.text.size * sc)) + 'px';
      const pad = 0.9 * ST.text.size * sc;
      drawText(g, ST.text.value.split('\n').slice(0, 4), p, ST.text.color,
        ST.text.alpha, ST.text.pos, pad, sc);
    }
  }

  function drawText(g, lines, font, color, alpha, pos, pad, sc) {
    g.save();
    g.font = '600 ' + font + ' "Microsoft YaHei", system-ui, sans-serif';
    g.textBaseline = 'top';
    const lh = parseInt(font, 10) * 1.34;
    let x = pad, align = 'left';
    if (pos[0] === 'c') { x = PV.W / 2; align = 'center'; }
    else if (pos[0] === 'r') { x = PV.W - pad; align = 'right'; }
    g.textAlign = align;
    let y = pad;
    if (pos[1] === 'c') y = (PV.H - lh * lines.length) / 2;
    else if (pos[1] === 'b') y = PV.H - pad - lh * lines.length;
    g.fillStyle = rgba(color, alpha);
    lines.forEach((ln, i) => g.fillText(ln, x, y + i * lh));
    g.restore();
  }

  function loop(ts) {
    if (!active) return;
    const dt = Math.min(0.1, (ts - (PV.last || ts)) / 1000) || 0.016;
    PV.last = ts;
    PV.t += dt;
    const g = PV.ctx;
    g.clearRect(0, 0, PV.W, PV.H);
    syncParts();
    step(dt);
    draw(g);
    drawOverlay(g, PV.t);
    PV.raf = requestAnimationFrame(loop);
  }

  /* ---------------------------------------------------------- 背景 */
  function applyBg() {
    const img = q('#pvImg'), vid = q('#pvVideo'), col = q('#pvColor');
    [img, vid, col].forEach((el) => { el.style.display = 'none'; });
    if (vid) { try { vid.pause(); } catch (e) {} }
    if (ST.bg.type === 'color') {
      col.style.display = '';
      col.style.background = `linear-gradient(180deg,${ST.bg.color} 0%,${ST.bg.color2 || ST.bg.color} 100%)`;
      return;
    }
    const isVideo = ST.bg.type === 'video';
    const el = isVideo ? vid : img;
    if (!el) return;
    if (ST.bg.src) {
      if (isVideo) {
        el.src = '/file?dyn=1&name=' + encodeURIComponent(ST.bg.name || basename(ST.bg.src));
        el.play().catch(() => {});
      } else {
        el.src = '/file?name=' + encodeURIComponent(ST.bg.name || basename(ST.bg.src));
      }
      el.style.display = '';
    }
  }

  const basename = (p) => String(p || '').split(/[\\/]/).pop();

  /* ---------------------------------------------------------- 面板 */
  function slider(scope, key, label, min, max, step, val, unit) {
    return `<div class="st-line"><span>${label}</span>
      <input type="range" data-scope="${scope}" data-f="${key}" min="${min}" max="${max}"
             step="${step}" value="${val}"><b>${val}${unit || ''}</b></div>`;
  }

  function buildPanel() {
    const seg = (scope, cur, opts) => `<div class="st-seg" data-seg="${scope}">` +
      opts.map(([v, t]) => `<button data-v="${v}" class="${cur === v ? 'on' : ''}">${t}</button>`).join('') +
      '</div>';

    let h = '';

    /* 背景 */
    h += `<div class="st-sec"><h3>背景</h3>`;
    h += seg('bg.type', ST.bg.type, [['color', '渐变色'], ['image', '图片'], ['video', '视频']]);
    h += `<div id="bgColor" ${ST.bg.type !== 'color' ? 'hidden' : ''}>
        <div class="st-line"><span>主色</span><input type="color" data-scope="bg" data-f="color" value="${ST.bg.color}">
        <span style="width:34px;text-align:right">副色</span><input type="color" data-scope="bg" data-f="color2" value="${ST.bg.color2}"></div>
      </div>`;
    h += `<div id="bgPick" ${ST.bg.type === 'color' ? 'hidden' : ''}>
        <button class="st-chip" id="bgUpload">＋ 导入本地${ST.bg.type === 'video' ? '视频' : '图片'}</button>
        <div class="st-chips" id="bgList"></div>
      </div>`;
    h += slider('bg', 'motion_speed', '推拉', 0.2, 3, 0.1, ST.bg.motion_speed, 'x');
    h += `</div>`;

    /* 特效 */
    h += `<div class="st-sec"><h3>画面特效 <span class="tagn">点名称展开参数</span></h3>`;
    KINDS.forEach((K) => {
      const s = ST.fx[K.k];
      h += `<div class="fx-item ${s.on ? 'on' : ''}" data-kind="${K.k}">
        <div class="fx-top" data-fold="${K.k}">
          <span class="nm">${K.label}</span>
          <label class="switch sw" onclick="event.stopPropagation()">
            <input type="checkbox" data-scope="${K.k}" data-f="on" ${s.on ? 'checked' : ''}><i class="track"></i>
          </label>
        </div>
        <div class="fx-body" data-body="${K.k}" ${s.on ? '' : 'hidden'}>
          ${slider(K.k, 'count', '数量', 0, 400, 5, s.count)}
          ${slider(K.k, 'size', '大小', 0.3, 3, 0.1, s.size, 'x')}
          ${slider(K.k, 'speed', '速度', 0.1, 3, 0.1, s.speed, 'x')}
          ${slider(K.k, 'alpha', '浓淡', 0.05, 1, 0.05, s.alpha)}
          ${K.angle ? slider(K.k, 'angle', '倾角', 0, 40, 1, s.angle, '°') : ''}
          <div class="st-line"><span>颜色</span><input type="color" data-scope="${K.k}" data-f="color" value="${s.color}"></div>
        </div>
      </div>`;
    });
    h += `</div>`;

    /* 鼠标互动 */
    h += `<div class="st-sec"><h3>鼠标互动</h3>
      <div class="st-line"><span>跟随光晕</span>
        <label class="switch"><input type="checkbox" data-scope="glow" data-f="on" ${ST.glow.on ? 'checked' : ''}><i class="track"></i></label>
        <input type="color" data-scope="glow" data-f="color" value="${ST.glow.color}">
      </div>
      ${slider('glow', 'size', '光晕大小', 120, 800, 20, ST.glow.size)}
      ${slider('glow', 'alpha', '强度', 0.05, 1, 0.05, ST.glow.alpha)}
      <div class="st-line" style="margin-top:12px"><span>点击涟漪</span>
        <label class="switch"><input type="checkbox" data-scope="ripple" data-f="on" ${ST.ripple.on ? 'checked' : ''}><i class="track"></i></label>
        <input type="color" data-scope="ripple" data-f="color" value="${ST.ripple.color}">
      </div>
      ${slider('ripple', 'size', '涟漪范围', 120, 900, 20, ST.ripple.size)}
      ${slider('ripple', 'alpha', '强度', 0.05, 1, 0.05, ST.ripple.alpha)}
    </div>`;

    /* 时钟 */
    h += `<div class="st-sec"><h3>桌面时钟
      <label class="switch" style="margin-left:auto"><input type="checkbox" data-scope="clock" data-f="on" ${ST.clock.on ? 'checked' : ''}><i class="track"></i></label></h3>
      <div class="st-line"><span>位置</span>
        <select data-scope="clock" data-f="pos">${POS.map(([v, t]) => `<option value="${v}" ${ST.clock.pos === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
      </div>
      ${slider('clock', 'size', '字号', 16, 160, 2, ST.clock.size)}
      ${slider('clock', 'alpha', '透明度', 0.1, 1, 0.05, ST.clock.alpha)}
      <div class="st-line"><span>显示秒</span>
        <label class="switch"><input type="checkbox" data-scope="clock" data-f="seconds" ${ST.clock.seconds ? 'checked' : ''}><i class="track"></i></label>
        <span style="width:58px;text-align:right">只显时间</span>
        <label class="switch"><input type="checkbox" data-scope="clock" data-f="only_time" ${ST.clock.only_time ? 'checked' : ''}><i class="track"></i></label>
      </div>
      <div class="st-line"><span>颜色</span><input type="color" data-scope="clock" data-f="color" value="${ST.clock.color}"></div>
    </div>`;

    /* 文字 */
    h += `<div class="st-sec"><h3>一句话
      <label class="switch" style="margin-left:auto"><input type="checkbox" data-scope="text" data-f="on" ${ST.text.on ? 'checked' : ''}><i class="track"></i></label></h3>
      <div class="st-line"><span>内容</span><input type="text" data-scope="text" data-f="value" value="${esc(ST.text.value)}" placeholder="想写在桌面上的话"></div>
      <div class="st-line"><span>位置</span>
        <select data-scope="text" data-f="pos">${POS.map(([v, t]) => `<option value="${v}" ${ST.text.pos === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
      </div>
      ${slider('text', 'size', '字号', 12, 120, 2, ST.text.size)}
      ${slider('text', 'alpha', '透明度', 0.1, 1, 0.05, ST.text.alpha)}
      <div class="st-line"><span>颜色</span><input type="color" data-scope="text" data-f="color" value="${ST.text.color}"></div>
    </div>`;

    q('#stPanel').innerHTML = h;
    fillBgList();
  }

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function target(scope) {
    if (scope === 'bg') return ST.bg;
    if (scope === 'glow' || scope === 'ripple' || scope === 'clock' || scope === 'text') return ST[scope];
    return ST.fx[scope];
  }

  function fillBgList() {
    const box = q('#bgList');
    if (!box) return;
    const wantVideo = ST.bg.type === 'video';
    const items = LIB.filter((i) => wantVideo
      ? /\.(mp4|webm|mov|mkv|avi|m4v|wmv)$/i.test(i.name)
      : /\.(jpg|jpeg|png|webp|bmp|avif|gif)$/i.test(i.name));
    if (!items.length) {
      box.innerHTML = `<span style="font-size:12px;color:var(--text-3)">还没有素材，先导入一个${wantVideo ? '视频' : '图片'}</span>`;
      return;
    }
    box.innerHTML = items.slice(0, 24).map((i) => {
      const on = ST.bg.name === i.name;
      return `<button class="st-chip" data-pick="${esc(i.name)}" data-path="${esc(i.path)}"
        style="${on ? 'border-color:var(--accent);color:var(--accent)' : ''}">${esc(i.name.length > 18 ? i.name.slice(0, 17) + '…' : i.name)}</button>`;
    }).join('');
  }

  /* ---------------------------------------------------------- 事件 */
  function bind() {
    const panel = q('#stPanel');
    panel.addEventListener('input', (e) => {
      const el = e.target;
      const scope = el.dataset.scope, f = el.dataset.f;
      if (!scope || !f) return;
      let v = el.type === 'checkbox' ? el.checked : el.value;
      if (el.type === 'range' || el.type === 'number') v = parseFloat(v);
      const t = target(scope);
      if (!t) return;
      t[f] = v;
      if (el.type === 'range') {
        const b = el.parentElement.querySelector('b');
        if (b) {
          const unit = f === 'angle' ? '°' : (f === 'size' || f === 'speed' || f === 'motion_speed') ? 'x' : '';
          b.textContent = (el.value) + (f === 'motion_speed' ? 'x' : unit);
        }
      }
      if (f === 'on') {
        const item = el.closest('.fx-item');
        if (item) {
          item.classList.toggle('on', !!v);
          const body = item.querySelector('.fx-body');
          if (body) body.hidden = !v;
        }
      }
      if (scope === 'bg' && (f === 'color' || f === 'color2')) applyBg();
    });

    panel.addEventListener('change', (e) => {
      const el = e.target;
      if (el.tagName === 'SELECT') {
        const t = target(el.dataset.scope);
        if (t) t[el.dataset.f] = el.value;
      }
      if (el.dataset.f === 'on' && el.type === 'checkbox') {
        const t = target(el.dataset.scope);
        if (t) t[el.dataset.f] = el.checked;
      }
    });

    panel.addEventListener('click', (e) => {
      const segBtn = e.target.closest('.st-seg[data-seg] button');
      if (segBtn) {
        const seg = segBtn.closest('.st-seg');
        const key = seg.dataset.seg;           // bg.type
        if (key === 'bg.type') {
          ST.bg.type = segBtn.dataset.v;
          ST.bg.src = ''; ST.bg.name = '';
          seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === segBtn));
          q('#bgColor').hidden = ST.bg.type !== 'color';
          q('#bgPick').hidden = ST.bg.type === 'color';
          q('#bgUpload').textContent = '＋ 导入本地' + (ST.bg.type === 'video' ? '视频' : '图片');
          fillBgList();
          applyBg();
        }
        return;
      }
      const fold = e.target.closest('[data-fold]');
      if (fold && !e.target.closest('.switch')) {
        const body = fold.parentElement.querySelector('.fx-body');
        body.hidden = !body.hidden;
        return;
      }
      const pick = e.target.closest('[data-pick]');
      if (pick) {
        ST.bg.name = pick.dataset.pick;
        ST.bg.src = pick.dataset.path;
        applyBg();
        fillBgList();
        return;
      }
      if (e.target.id === 'bgUpload') q('#bgFile').click();
    });

    q('#bgFile').addEventListener('change', async (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!f) return;
      const isVideo = /^video\//.test(f.type) || /\.(mp4|webm|mov|mkv)$/i.test(f.name);
      if (ST.bg.type !== (isVideo ? 'video' : 'image')) {
        ST.bg.type = isVideo ? 'video' : 'image';
        buildPanel();
      }
      const t = window.toast ? toast('正在导入素材…') : null;
      try {
        const data = await readFileB64(f);
        const r = await post('/api/scene/upload', { name: f.name, data });
        if (!r.ok) throw new Error(r.error || '导入失败');
        ST.bg.name = r.name; ST.bg.src = r.path;
        LIB.unshift({ name: r.name, path: r.path, url: r.url });
        applyBg();
        fillBgList();
        if (t) t.remove();
        if (window.toast) toast('✅ 素材已导入图库');
      } catch (err) {
        if (t) t.remove();
        if (window.toast) toast(err.message, true);
      }
    });

    // 画布交互：光晕 + 涟漪
    const cvs = PV.cvs;
    cvs.addEventListener('mousemove', (e) => {
      const r = cvs.getBoundingClientRect();
      PV.mx = e.clientX - r.left;
      PV.my = e.clientY - r.top;
    });
    cvs.addEventListener('mouseleave', () => { PV.mx = PV.my = -999; });
    cvs.addEventListener('click', (e) => {
      const r = cvs.getBoundingClientRect();
      if (ST.ripple.on && PV.ripples.length < 12) {
        PV.ripples.push({ x: e.clientX - r.left, y: e.clientY - r.top, t: 0 });
      }
    });
  }

  function readFileB64(f) {
    return new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result));
      fr.onerror = () => rej(new Error('读取文件失败'));
      fr.readAsDataURL(f);
    });
  }

  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    return r.json();
  }
  async function getJSON(url) {
    const r = await fetch(url);
    return r.json();
  }

  /* ---------------------------------------------------------- 缩略图 */
  function makeThumb() {
    const W = 640, H = 360;
    const c = document.createElement('canvas');
    c.width = W; c.height = H;
    const g = c.getContext('2d');
    if (ST.bg.type === 'color') {
      const grd = g.createLinearGradient(0, 0, 0, H);
      grd.addColorStop(0, ST.bg.color);
      grd.addColorStop(1, ST.bg.color2 || ST.bg.color);
      g.fillStyle = grd;
      g.fillRect(0, 0, W, H);
    } else {
      const el = ST.bg.type === 'video' ? q('#pvVideo') : q('#pvImg');
      try {
        if (el && (el.readyState >= 2 || el.complete)) {
          const sw = el.videoWidth || el.naturalWidth, sh = el.videoHeight || el.naturalHeight;
          if (sw && sh) {
            const s = Math.max(W / sw, H / sh);
            g.drawImage(el, (W - sw * s) / 2, (H - sh * s) / 2, sw * s, sh * s);
          }
        }
      } catch (e) { g.fillStyle = '#111a2e'; g.fillRect(0, 0, W, H); }
    }
    try { g.drawImage(PV.cvs, 0, 0, W, H); } catch (e) {}
    return c.toDataURL('image/jpeg', 0.85);
  }

  /* ---------------------------------------------------------- 保存 / 应用 */
  function buildCfg() {
    const fx = [];
    fxList().forEach(({ K, s }) => {
      const o = { kind: K.k, count: +s.count, size: +s.size, speed: +s.speed,
                  alpha: +s.alpha, color: s.color };
      if (K.angle) o.angle = +s.angle;
      fx.push(o);
    });
    return {
      name: ST.name,
      bg: { type: ST.bg.type, src: ST.bg.src, name: ST.bg.name,
            color: ST.bg.color, color2: ST.bg.color2, motion_speed: +ST.bg.motion_speed },
      fx,
      mouse: { glow: { ...ST.glow }, ripple: { ...ST.ripple } },
      clock: { ...ST.clock }, text: { ...ST.text }
    };
  }

  async function save(apply) {
    ST.name = (q('#stName').value || '我的特效壁纸').trim().slice(0, 40) || '我的特效壁纸';
    const btn = apply ? q('#stApply') : q('#stSave');
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = '保存中…';
    try {
      const cfg = buildCfg();
      const r = await post('/api/scene/save', { id: ST.id, name: ST.name, cfg, thumb: makeThumb() });
      if (!r.ok) throw new Error(r.error || '保存失败');
      ST.id = r.id;
      if (apply) {
        btn.textContent = '正在铺到桌面…';
        const a = await post('/api/scene/apply', { id: r.id });
        if (!a.ok) throw new Error(a.error || '启动失败');
        if (window.toast) toast('✅ 已铺到桌面，点桌面空白处试试涟漪');
      } else if (window.toast) {
        toast('已保存到「我的特效壁纸」');
      }
      await refresh();
    } catch (e) {
      if (window.toast) toast(e.message, true);
    } finally {
      btn.disabled = false; btn.textContent = old;
    }
  }

  /* ---------------------------------------------------------- 风格预设 */
  let PRESETS = [];
  async function loadPresets() {
    const box = q('#stPresets');
    if (!box) return;
    try {
      const j = await getJSON('/api/scene/presets');
      PRESETS = j.items || [];
    } catch (e) { PRESETS = []; }
    if (!PRESETS.length) {
      box.innerHTML = '<span style="color:var(--text-3); font-size:12px">预设加载失败</span>';
      return;
    }
    box.innerHTML = PRESETS.map((p) =>
      `<button class="st-chip pre" data-pid="${p.id}">${esc(p.label)}</button>`).join('');
    box.querySelectorAll('.pre').forEach((b) => {
      b.onclick = () => {
        const p = PRESETS.find((x) => x.id === b.dataset.pid);
        if (!p) return;
        loadCfg(p.cfg, '');
        if (window.toast) toast(`已载入「${p.label}」，右侧可继续微调`);
      };
    });
  }

  async function refresh() {
    if (q('#stPresets') && !PRESETS.length) loadPresets();
    try {
      const j = await getJSON('/api/scene/list');
      LIB = j.lib || [];
      SCENES = j.items || [];
      RUN = j.state || { running: false };
      renderState();
      renderMine();
      if (q('#bgList')) fillBgList();
    } catch (e) {}
  }

  function renderState() {
    const box = q('#stState');
    if (!box) return;
    box.innerHTML = RUN.running
      ? `<span class="live"></span>桌面正在播放：${esc(RUN.name || '')}
         <button class="st-chip" id="stStop" style="margin-left:6px">停止</button>`
      : `<span style="color:var(--text-3)">桌面当前没有特效壁纸在播放</span>`;
    const btn = q('#stStop');
    if (btn) btn.onclick = async () => {
      await post('/api/scene/stop', {});
      refresh();
    };
  }

  function renderMine() {
    const box = q('#stMine');
    if (!box) return;
    const cnt = q('#stCount');
    if (cnt) cnt.textContent = SCENES.length ? SCENES.length + ' 张' : '';
    if (!SCENES.length) {
      box.innerHTML = `<div class="st-empty">还没有自制壁纸。左边调好参数，点「保存并铺到桌面」就会出现在这里。</div>`;
      return;
    }
    box.innerHTML = SCENES.map((s) => `
      <div class="st-card" data-id="${s.id}">
        <div class="th">${s.has_thumb
          ? `<img src="${s.thumb}" alt="">`
          : `<div class="ph">${esc(s.summary || '无预览图')}</div>`}</div>
        <div class="bd">
          <div class="nm">${esc(s.name)}</div>
          <div class="sm">${esc(s.summary || '')}</div>
          <div class="ops">
            <button class="pri" data-act="use">使用</button>
            <button data-act="edit">编辑</button>
            <button data-act="del">删除</button>
          </div>
        </div>
      </div>`).join('');
    box.onclick = async (e) => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      const id = btn.closest('.st-card').dataset.id;
      const sc = SCENES.find((x) => x.id === id);
      if (!sc) return;
      if (btn.dataset.act === 'use') {
        btn.disabled = true; btn.textContent = '…';
        const r = await post('/api/scene/apply', { id });
        btn.disabled = false; btn.textContent = '使用';
        if (r.ok) { if (window.toast) toast('✅ 已铺到桌面'); refresh(); }
        else if (window.toast) toast(r.error || '启动失败', true);
      } else if (btn.dataset.act === 'edit') {
        loadCfg(sc.cfg, id);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } else if (btn.dataset.act === 'del') {
        if (!confirm('删除「' + sc.name + '」？')) return;
        await post('/api/scene/delete', { id });
        if (ST.id === id) ST.id = '';
        refresh();
      }
    };
  }

  /* ---------------------------------------------------------- 载入配置 */
  function loadCfg(cfg, id) {
    ST = DEF();
    ST.id = id || '';
    if (cfg) {
      ST.name = cfg.name || ST.name;
      const bg = cfg.bg || {};
      Object.keys(ST.bg).forEach((k) => { if (bg[k] != null) ST.bg[k] = bg[k]; });
      if (!ST.bg.name && ST.bg.src) ST.bg.name = basename(ST.bg.src);
      // 场景里没列出的特效要关掉（DEF 默认会带一层雨）
      Object.keys(ST.fx).forEach((k) => { ST.fx[k].on = false; });
      (cfg.fx || []).forEach((it) => {
        const s = ST.fx[it.kind];
        if (!s) return;
        s.on = true;
        ['count', 'size', 'speed', 'alpha', 'color', 'angle'].forEach((f) => {
          if (it[f] != null) s[f] = it[f];
        });
      });
      const m = cfg.mouse || {};
      if (m.glow) Object.assign(ST.glow, m.glow);
      if (m.ripple) Object.assign(ST.ripple, m.ripple);
      if (cfg.clock) Object.assign(ST.clock, cfg.clock);
      if (cfg.text) Object.assign(ST.text, cfg.text);
    }
    q('#stName').value = ST.name;
    buildPanel();
    applyBg();
    spawnAll();
  }

  /* ---------------------------------------------------------- 尺寸 */
  function resize() {
    const cvs = PV.cvs;
    if (!cvs) return;
    const stage = cvs.parentElement;
    const w = stage.clientWidth || 1280, h = stage.clientHeight || 720;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    PV.W = w; PV.H = h; PV.sc = h / 1080; PV.dpr = dpr;
    cvs.width = Math.round(w * dpr);
    cvs.height = Math.round(h * dpr);
    PV.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    spawnAll();
  }

  /* ---------------------------------------------------------- 对外 */
  const Studio = {
    init() {
      PV.cvs = q('#pvCanvas');
      if (!PV.cvs) return;
      PV.ctx = PV.cvs.getContext('2d');
      buildPanel();
      bind();
      resize();
      window.addEventListener('resize', () => { if (active) resize(); });
      applyBg();
      refresh();
    },
    enter() {
      active = true;
      q('#stName').value = ST.name;
      if (!PV.W) resize();
      else if (PV.cvs.width !== Math.round(PV.cvs.parentElement.clientWidth * PV.dpr)) resize();
      spawnAll();
      PV.last = 0;
      cancelAnimationFrame(PV.raf);
      PV.raf = requestAnimationFrame(loop);
      refresh();
    },
    leave() {
      active = false;
      cancelAnimationFrame(PV.raf);
    }
  };

  function boot() {
    Studio.init();
    q('#stSave').onclick = () => save(false);
    q('#stApply').onclick = () => save(true);
    q('#stNew').onclick = () => {
      if (!confirm('清空当前编辑，新建一个？')) return;
      ST = DEF();
      q('#stName').value = ST.name;
      buildPanel(); applyBg(); spawnAll();
    };
    // 直接带 #studio 打开时，switchTab 早于本脚本执行，这里补一次进入
    if (document.querySelector('main').classList.contains('studio-mode')) Studio.enter();
  }
  window.Studio = Studio;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
