/* Fit, not format — interactions. No dependencies. Every number below is from the paper. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.documentElement;

  /* ---------------- language ---------------- */
  const TITLES = {
    en: 'Fit, not format — how the edit interface shapes coding agents (Physics of Coding Agents, Part 1)',
    zh: '重在契合，不在格式：编辑接口如何塑造编程智能体（Physics of Coding Agents · Part 1）',
  };
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  function setLang(lang, push) {
    root.dataset.lang = lang;
    root.lang = lang === 'zh' ? 'zh-CN' : 'en';
    document.title = TITLES[lang];
    $$('[data-setlang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.setlang === lang)));
    store.set('fnf-lang', lang);
    if (push) {
      const u = new URL(location.href);
      if (lang === 'zh') u.searchParams.set('lang', 'zh'); else u.searchParams.delete('lang');
      history.replaceState(null, '', u);
    }
    renderEditor(state.tab, state.step); // verdict text is language-dependent
  }
  $$('[data-setlang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.setlang, true)));

  /* ---------------- theme ---------------- */
  const themeBtn = $('#theme');
  const savedTheme = store.get('fnf-theme');
  if (savedTheme) root.dataset.theme = savedTheme;
  themeBtn?.addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    store.set('fnf-theme', root.dataset.theme);
  });

  /* ---------------- hero editor: one edit, three ways ---------------- */
  const NEW = 's += x.price * x.qty';
  const CALLS = {
    quote: [
      `<span class="k">edit_text</span>(<br>&nbsp;&nbsp;<span class="k">old_text</span>: <span class="q">"s += item.price"</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)<br><span class="chip bad">✕ <span lang="en">no match — reread, retype</span><span lang="zh">对不上原文，重读重打</span></span>`,
      `<span class="k">edit_text</span>(<br>&nbsp;&nbsp;<span class="k">old_text</span>: <span class="q">"s += x.price"</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)<br><span class="chip ok">✓ <span lang="en">matched, applied (2nd try)</span><span lang="zh">对上了，已应用（第 2 次）</span></span>`,
    ],
    point: [
      `<span class="k">edit_lines</span>(<br>&nbsp;&nbsp;<span class="k">start_line</span>: <span class="n">14</span>, <span class="k">end_line</span>: <span class="n">14</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)`,
      `<span class="k">edit_lines</span>(<br>&nbsp;&nbsp;<span class="k">start_line</span>: <span class="n">14</span>, <span class="k">end_line</span>: <span class="n">14</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)<br><span class="chip warn">✓ <span lang="en">applied — to line 14, no error</span><span lang="zh">已应用：改到了第 14 行，没有报错</span></span>`,
    ],
    ours: [
      `<span class="k">edit_lines</span>(<br>&nbsp;&nbsp;<span class="k">start_line</span>: <span class="n">14</span>, <span class="k">end_line</span>: <span class="n">14</span>,<br>&nbsp;&nbsp;<span class="k">first_line</span>: <span class="q">"s += x.price"</span>, <span class="k">last_line</span>: <span class="q">"s += x.price"</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)`,
      `<span class="k">edit_lines</span>(<br>&nbsp;&nbsp;<span class="k">start_line</span>: <span class="n">14</span>, <span class="k">end_line</span>: <span class="n">14</span>,<br>&nbsp;&nbsp;<span class="k">first_line</span>: <span class="q">"s += x.price"</span>, <span class="k">last_line</span>: <span class="q">"s += x.price"</span>,<br>&nbsp;&nbsp;<span class="k">new_text</span>: <span class="q">"${NEW}"</span>)<br><span class="chip ok">✓ <span lang="en">ends found at 15 — aligned +1, applied</span><span lang="zh">两端原文在第 15 行：对齐 +1 后应用</span></span>`,
    ],
  };
  const VERDICT = {
    quote: { en: '<b>Quote.</b> The harness can check it, so a mismatch is caught — but every retry is paid in output.', zh: '<b>引原文。</b>harness 能核对，对不上会被拦下；代价是每次重试都要重新输出。' },
    point: { en: '<b>Point.</b> Cheap to write — but a range one line off edits the wrong code, and nothing complains.', zh: '<b>指行号。</b>写起来便宜；可一旦偏了一行，就悄悄改错了地方，没有任何报错。' },
    ours: { en: '<b>Point + quote the two ends.</b> Cheap like a pointer, checked like a quote.', zh: '<b>指行号 + 只引首尾两行。</b>像指行号一样便宜，像引原文一样可核对。' },
  };
  const state = { tab: 'quote', step: 0, timer: null, paused: 0 };
  const lines = () => $$('.editor .ln');
  function setLine(n, cls, text) {
    const ln = lines().find((l) => l.dataset.n === String(n));
    if (!ln) return;
    if (cls !== undefined) { ln.classList.remove('hl-quote', 'hl-point', 'hl-bad', 'hl-ok'); if (cls) ln.classList.add(cls); }
    if (text !== undefined) $('.tx', ln).innerHTML = text;
  }
  function resetCode() {
    lines().forEach((l) => { l.classList.remove('hl-quote', 'hl-point', 'hl-bad', 'hl-ok', 'pinned', 'lit'); $('.tx', l).innerHTML = l.dataset.orig; });
  }
  const NEWHTML = '        <span class="tok-v">s</span> <span class="tok-p">+=</span> <span class="tok-v">x</span>.<span class="tok-v">price</span> <span class="tok-p">*</span> <span class="tok-v">x</span>.<span class="tok-v">qty</span>';
  function renderEditor(tab, step) {
    const ed = $('.editor'); if (!ed) return;
    const lang = root.dataset.lang || 'en';
    resetCode();
    $$('.editor .tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    $('.editor .call').innerHTML = CALLS[tab][step];
    $('.editor .verdict').innerHTML = step === 1 ? VERDICT[tab][lang] : '&nbsp;';
    const ln14 = lines().find((l) => l.dataset.n === '14');
    const ln15 = lines().find((l) => l.dataset.n === '15');
    if (tab === 'quote') {
      if (step === 0) setLine(15, 'hl-quote');
      else setLine(15, 'hl-ok', NEWHTML);
    } else if (tab === 'point') {
      ln14.classList.add('pinned', 'lit');
      if (step === 0) setLine(14, 'hl-point');
      else setLine(14, 'hl-bad', NEWHTML);
    } else {
      if (step === 0) { ln14.classList.add('pinned', 'lit'); setLine(14, 'hl-point'); }
      else { ln15.classList.add('pinned', 'lit'); setLine(15, 'hl-ok', NEWHTML); }
    }
  }
  const ORDER = ['quote', 'point', 'ours'];
  const STEP_MS = [1900, 2900];
  function play() {
    clearTimeout(state.timer);
    const bar = $('.editor .progress i');
    const dur = STEP_MS[state.step];
    if (bar && !reduce) { bar.style.transition = 'none'; bar.style.width = state.step ? '50%' : '0%'; requestAnimationFrame(() => { bar.style.transition = `width ${dur}ms linear`; bar.style.width = state.step ? '100%' : '50%'; }); }
    state.timer = setTimeout(() => {
      if (state.step === 0) state.step = 1;
      else { state.step = 0; state.tab = ORDER[(ORDER.indexOf(state.tab) + 1) % 3]; }
      renderEditor(state.tab, state.step);
      play();
    }, dur);
  }
  $$('.editor .tabs button').forEach((b) => b.addEventListener('click', () => {
    clearTimeout(state.timer);
    state.tab = b.dataset.tab; state.step = 0; renderEditor(state.tab, 0);
    // show the outcome after a beat, then resume the tour
    state.timer = setTimeout(() => { state.step = 1; renderEditor(state.tab, 1); if (!reduce) state.timer = setTimeout(() => { state.step = 0; state.tab = ORDER[(ORDER.indexOf(state.tab) + 1) % 3]; renderEditor(state.tab, 0); play(); }, 6500); }, 1100);
  }));
  lines().forEach((l) => { l.dataset.orig = $('.tx', l).innerHTML; });
  renderEditor('quote', 0);
  if (!reduce) play(); else { state.step = 1; renderEditor('quote', 1); }

  /* ---------------- data (paper Table 1, first run) ---------------- */
  const ROWS = [
    { m: 'GPT-5.6-luna', b: 'CanItEdit', acc: [.93, .23, .99], suc: [.756, .780, .805] },
    { m: 'GLM-5.3', b: 'CanItEdit', acc: [.97, .89, .96], suc: [.817, .793, .768] },
    { m: 'DeepSeek-V4-Flash', b: 'CanItEdit', acc: [.84, .25, .90], suc: [.732, .683, .659] },
    { m: 'MiMo-v2.5-Pro', b: 'CanItEdit', acc: [.93, .16, .87], suc: [.780, .817, .829] },
    { m: 'Qwen3.8-Flash', b: 'CanItEdit', acc: [.66, .86, .45], suc: [.823, .861, .848] },
    { m: 'Claude Sonnet 5', b: 'CanItEdit', acc: [.92, null, 1.00], suc: [.787, null, .825] },
    { m: 'GPT-5.6-luna', b: 'Refactors', acc: [.58, .33, .99], suc: [.944, .944, .944] },
    { m: 'MiMo-v2.5-Pro', b: 'Refactors', acc: [.76, .19, .80], suc: [.932, .841, .841] },
  ];
  const IFACE = [
    { k: 'sr', en: 'search/replace', zh: '搜索替换', color: 'var(--quote)', shape: 'circle' },
    { k: 'pa', en: 'patch', zh: '补丁', color: 'var(--patch)', shape: 'square' },
    { k: 'lr', en: 'line range', zh: '行号范围', color: 'var(--point)', shape: 'tri' },
  ];

  /* ---------------- viz 1: the puzzle — acceptance spreads, success does not ---------------- */
  let puzzleMode = 'acc';
  function buildPuzzle() {
    const host = $('#viz-puzzle svg'); if (!host) return;
    const compact = host.clientWidth < 600;
    const W = compact ? 420 : 860, L = compact ? 12 : 236, R = compact ? 404 : 836, top = compact ? 40 : 36, rowH = compact ? 50 : 40;
    const H = top + ROWS.length * rowH + 30;
    host.setAttribute('viewBox', `0 0 ${W} ${H}`);
    const x = (v) => L + (R - L) * v;
    let s = '';
    for (let g = 0; g <= 4; g++) {
      const v = g / 4;
      s += `<line x1="${x(v)}" x2="${x(v)}" y1="${top - 14}" y2="${H - 24}" stroke="var(--hair)" stroke-width="1"/>`;
      s += `<text x="${x(v)}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--muted)">${Math.round(v * 100)}%</text>`;
    }
    ROWS.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      if (i === 6) s += `<line x1="16" x2="${R}" y1="${y - rowH / 2}" y2="${y - rowH / 2}" stroke="var(--hair)" stroke-dasharray="3 4"/>`;
      if (compact) {
        s += `<text x="${L}" y="${y - 13}" font-size="12" fill="var(--ink)">${r.m} <tspan fill="var(--muted)" font-size="10.5">· ${r.b === 'Refactors' ? 'refactor' : 'CanItEdit'}</tspan></text>`;
      } else {
        s += `<text x="16" y="${y + 4}" font-size="12.5" fill="var(--ink)">${r.m}</text>`;
        s += `<text x="${L - 12}" y="${y + 4}" font-size="10.5" text-anchor="end" fill="var(--muted)">${r.b === 'Refactors' ? 'refactor' : 'CanItEdit'}</text>`;
      }
      s += `<line x1="${L}" x2="${R}" y1="${y}" y2="${y}" stroke="var(--hair)" stroke-width="1"/>`;
      s += `<rect class="span" data-row="${i}" x="${x(0)}" y="${y - 7}" width="0" height="14" rx="7" fill="var(--accent)" opacity=".13"/>`;
      IFACE.forEach((f, j) => {
        if (r.acc[j] == null) return;
        const mark = f.shape === 'circle' ? `<circle r="7" fill="${f.color}"/>`
          : f.shape === 'square' ? `<rect x="-6.5" y="-6.5" width="13" height="13" rx="2" fill="${f.color}"/>`
          : `<path d="M0,-8 L7.5,6 L-7.5,6 Z" fill="${f.color}"/>`;
        s += `<g class="mk" data-row="${i}" data-j="${j}" style="transform: translate(${x(0)}px, ${y}px)">${mark}</g>`;
      });
    });
    host.innerHTML = s;
    const show = (mode) => {
      ROWS.forEach((r, i) => {
        const y = top + i * rowH + rowH / 2;
        const vals = (mode === 'acc' ? r.acc : r.suc).filter((v) => v != null);
        const span = $(`rect.span[data-row="${i}"]`, host);
        const lo = Math.min(...vals), hi = Math.max(...vals);
        span.style.x = (x(lo) - 9) + 'px'; span.style.width = (x(hi) - x(lo) + 18) + 'px';
        $$(`g.mk[data-row="${i}"]`, host).forEach((g) => {
          const v = (mode === 'acc' ? r.acc : r.suc)[+g.dataset.j];
          g.style.transform = `translate(${x(v)}px, ${y}px)`;
        });
      });
      $$('#viz-puzzle [data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
      puzzleMode = mode;
    };
    return show;
  }
  let showPuzzle = buildPuzzle();
  $$('#viz-puzzle [data-mode]').forEach((b) => b.addEventListener('click', () => { $('#viz-puzzle').dataset.touched = '1'; showPuzzle(b.dataset.mode); }));
  let puzzleSeen = false;
  onView($('#viz-puzzle'), () => {
    puzzleSeen = true;
    requestAnimationFrame(() => showPuzzle('acc'));
    if (!reduce) setTimeout(() => { if (!$('#viz-puzzle').dataset.touched) showPuzzle('suc'); }, 3400);
  });
  let lastCompact = ($('#viz-puzzle svg')?.clientWidth || 900) < 600;
  addEventListener('resize', () => {
    const c = ($('#viz-puzzle svg')?.clientWidth || 900) < 600;
    if (c === lastCompact) return;
    lastCompact = c; showPuzzle = buildPuzzle();
    if (puzzleSeen) { const m = puzzleMode; requestAnimationFrame(() => showPuzzle(m)); }
  });

  /* ---------------- viz 2: large edits — visible vs silent failures (100 cells each) ---------------- */
  function buildRegion() {
    const host = $('#viz-region'); if (!host) return;
    $$('.units', host).forEach((u) => {
      const rej = +u.dataset.rej, brk = +u.dataset.brk;
      u.innerHTML = Array.from({ length: 100 }, (_, k) => `<i data-k="${k}"></i>`).join('');
      onView(host, () => {
        $$('i', u).forEach((c, k) => {
          const cls = k < rej ? 'rej' : k < rej + brk ? 'brk' : '';
          if (cls) setTimeout(() => c.classList.add(cls), reduce ? 0 : 300 + k * 28);
        });
      });
    });
  }

  /* ---------------- viz 3: fit matrix ---------------- */
  function buildMatrix() {
    const tb = $('#viz-matrix tbody'); if (!tb) return;
    const lang = () => root.dataset.lang || 'en';
    const shade = (v) => `color-mix(in srgb, var(--accent) ${Math.round(8 + 62 * v * v)}%, var(--card))`;
    let html = '';
    ROWS.forEach((r, i) => {
      if (i === 0) html += `<tr class="group"><th colspan="4">CanItEdit · <span lang="en">short files</span><span lang="zh">短文件</span></th></tr>`;
      if (i === 6) html += `<tr class="group"><th colspan="4"><span lang="en">Large-file refactors</span><span lang="zh">大文件重构</span></th></tr>`;
      const best = Math.max(...r.acc.filter((v) => v != null));
      html += `<tr><th>${r.m}</th>` + r.acc.map((v, j) => v == null
        ? `<td class="na">—</td>`
        : `<td data-v="${v}" class="${v === best ? 'best' : ''}" style="background:${shade(0)}"><span class="val">${Math.round(v * 100)}%</span><span class="sub">${Math.round(r.suc[j] * 1000) / 10}% <span lang="en">solved</span><span lang="zh">解出</span></span></td>`).join('') + '</tr>';
    });
    tb.innerHTML = html;
    onView($('#viz-matrix'), () => $$('td[data-v]', tb).forEach((td, k) => setTimeout(() => { td.style.background = shade(+td.dataset.v); }, reduce ? 0 : k * 45)));
  }

  /* ---------------- viz 4: habit vs fluency (GPT-5.6-luna) ---------------- */
  function buildHabit() {
    const host = $('#viz-habit'); if (!host) return;
    onView(host, () => {
      $$('.stack div', host).forEach((d) => { d.style.width = d.dataset.w + '%'; });
      $$('.mini-bars .track i', host).forEach((d) => { d.style.width = d.dataset.w + '%'; });
    });
  }

  /* ---------------- viz 5: broken first edits — line ranges vs verified selection ---------------- */
  function buildBroken() {
    const host = $('#viz-broken'); if (!host) return;
    $$('.units', host).forEach((u) => {
      const n = +u.dataset.from;
      u.innerHTML = Array.from({ length: n }, () => '<i class="brk"></i>').join('');
    });
    const set = (mode) => {
      $$('.units', host).forEach((u) => {
        const keep = +u.dataset.to;
        $$('i', u).forEach((c, k) => {
          const on = mode === 'ours';
          const delay = reduce ? 0 : on ? (u.children.length - k) * 18 : k * 6;
          setTimeout(() => {
            c.classList.toggle('gone', on && k >= keep);
            c.classList.toggle('keep', on && k < keep);
            c.classList.toggle('brk', !on || k >= keep);
          }, delay);
        });
        const lab = $(`.val[data-for="${u.id}"]`, host);
        if (lab) lab.innerHTML = mode === 'ours' ? lab.dataset.ours : lab.dataset.lr;
      });
      $$('[data-bmode]', host).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.bmode === mode)));
    };
    $$('[data-bmode]', host).forEach((b) => b.addEventListener('click', () => { host.dataset.touched = '1'; set(b.dataset.bmode); }));
    set('lr');
    onView(host, () => { if (!reduce) setTimeout(() => { if (!host.dataset.touched) set('ours'); }, 1400); });
  }

  /* ---------------- viz 6: efficiency bars ---------------- */
  function buildEff() {
    const host = $('#viz-eff'); if (!host) return;
    onView(host, () => $$('.track i', host).forEach((d) => { d.style.width = d.dataset.w + '%'; }));
  }


  /* ---------------- run log: lines print in order, numbers count up ---------------- */
  function countUp(el) {
    const end = parseFloat(el.dataset.count), dec = +(el.dataset.dec || 0), suf = el.dataset.suffix || '';
    const fmt = (v) => (v < 0 ? '−' : '') + Math.abs(v).toFixed(dec) + suf;
    if (reduce) { el.textContent = fmt(end); return; }
    const t0 = performance.now(), dur = 900;
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(end * e);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  (function runlog() {
    const host = $('#runlog'); if (!host) return;
    const rows = $$('.rl', host);
    onView(host, () => rows.forEach((r, i) => setTimeout(() => {
      r.classList.add('on');
      $$('[data-count]', r).forEach(countUp);
    }, reduce ? 0 : 250 + i * 420)));
  })();

  /* ---------------- lines to write: bars draw one by one ---------------- */
  (function linesViz() {
    const host = $('#viz-lines'); if (!host) return;
    const rows = $$('.bars', host);
    rows.forEach((b) => {
      const q = +(b.dataset.quote || 0), n = +(b.dataset.new || 0), e = +(b.dataset.ends || 0), r = +(b.dataset.ref || 0);
      b.innerHTML = '<i class="q"></i>'.repeat(q) + '<i></i>'.repeat(n) + '<i class="e"></i>'.repeat(e) + '<i class="r"></i>'.repeat(r);
    });
    const timers = [];
    const play = () => {
      timers.splice(0).forEach(clearTimeout);
      rows.forEach((b) => $$('i', b).forEach((i) => i.classList.remove('on')));
      let t = 0;
      rows.forEach((b) => {
        $$('i', b).forEach((i) => { timers.push(setTimeout(() => i.classList.add('on'), reduce ? 0 : t)); t += 22; });
        t += 260;
      });
    };
    $('.replay', host)?.addEventListener('click', play);
    onView(host, play);
  })();

  /* ---------------- scroll machinery ---------------- */
  function onView(el, fn) {
    if (!el) return;
    if (reduce || !('IntersectionObserver' in window)) { fn(); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(); } }, { threshold: 0.35 });
    io.observe(el);
  }
  $$('.reveal').forEach((el) => onView(el, () => el.classList.add('in')));

  // scrollspy: the rail's pin and the top nav follow the reader
  const secs = $$('section[data-spy]');
  if ('IntersectionObserver' in window) {
    const spy = new IntersectionObserver((es) => {
      es.forEach((e) => {
        if (!e.isIntersecting) return;
        const id = e.target.id;
        $$('.rail a, .nav a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
        $('.rail')?.classList.toggle('on-dark', e.target.classList.contains('band-dark'));
      });
    }, { rootMargin: '-40% 0px -55% 0px' });
    secs.forEach((s) => spy.observe(s));
  }

  /* ---------------- GitHub stars ---------------- */
  $$('[data-stars]').forEach(async (el) => {
    const repo = el.dataset.stars;
    try {
      const cached = JSON.parse(store.get('stars:' + repo) || 'null');
      if (cached && Date.now() - cached.t < 36e5) { el.textContent = cached.n; return; }
      const r = await fetch(`https://api.github.com/repos/${repo}`);
      if (!r.ok) return;
      const n = (await r.json()).stargazers_count;
      const txt = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
      el.textContent = txt;
      store.set('stars:' + repo, JSON.stringify({ n: txt, t: Date.now() }));
    } catch { /* offline or rate-limited: keep the placeholder */ }
  });

  /* ---------------- copy BibTeX ---------------- */
  $$('.copy').forEach((b) => b.addEventListener('click', async () => {
    const txt = $(b.dataset.target).innerText;
    try { await navigator.clipboard.writeText(txt); } catch { /* ignore */ }
    const old = b.textContent; b.textContent = '✓ copied'; setTimeout(() => { b.textContent = old; }, 1600);
  }));

  /* ---------------- lightbox ---------------- */
  const lb = $('.lightbox');
  $$('[data-zoom]').forEach((img) => img.addEventListener('click', () => { $('img', lb).src = img.dataset.zoom || img.src; lb.classList.add('open'); }));
  lb?.addEventListener('click', () => lb.classList.remove('open'));
  addEventListener('keydown', (e) => { if (e.key === 'Escape') lb?.classList.remove('open'); });

  buildRegion(); buildMatrix(); buildHabit(); buildBroken(); buildEff();

  // initial language (default English; ?lang=zh or a saved choice switches)
  const q = new URL(location.href).searchParams.get('lang');
  setLang(q === 'zh' || q === 'en' ? q : (store.get('fnf-lang') || 'en'), false);
})();
