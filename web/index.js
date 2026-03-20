'use strict';

// ── Config ───────────────────────────────────────────────────────────────────
// BASE = '..' because the server serves the project root, and index.html is in web/
const BASE = '..';

// Appended to image URLs to bust browser cache when reloading from a different folder
const CACHE_BUST = '?v=' + Date.now();

const PATHS = {
  screenplay:    `${BASE}/cinematic_render/animation_episodes.json`,
  metadata:      `${BASE}/cinematic_render/animation_metadata.json`,
  qa:            `${BASE}/cinematic_render/quality_report.json`,
  refDir:        `${BASE}/ref_thriller`,
  panels:        `${BASE}/cinematic_render/panels`,
  sceneGrid:     `${BASE}/cinematic_render`,
};

const PROMPT_FILES = ['style.md', 'casting.md', 'scenery.md', 'imagery.md', 'setting.md'];

// Max episodes to probe (CLAUDE.md says ~30 episodes)
const MAX_EPISODES = 30;

// ── Helpers ──────────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function fetchText(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.text();
}

async function headExists(url) {
  try {
    const r = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(5000) });
    return r.ok;
  } catch {
    return false;
  }
}

// Loads web/server-info.json written by `make webserver`.
// Falls back to null if not present (HEAD-probe fallback paths handle that case).
let _serverInfo = undefined;
async function loadServerInfo() {
  if (_serverInfo !== undefined) return _serverInfo;
  try {
    _serverInfo = await fetchJSON('server-info.json');
  } catch {
    _serverInfo = null;
  }
  return _serverInfo;
}

function scoreClass(v) {
  if (v >= 8) return 'score-high';
  if (v >= 5) return 'score-mid';
  return 'score-low';
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

// Escapes HTML including " for safe use in attributes
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
const lightbox = document.getElementById('lightbox');
const lightboxImg = lightbox.querySelector('.lightbox-img');
const lightboxBackdrop = lightbox.querySelector('.lightbox-backdrop');
const lightboxClose = lightbox.querySelector('.lightbox-close');

function openLightbox(src) {
  lightboxImg.src = src;
  lightbox.classList.remove('hidden');
}
function closeLightbox() {
  lightbox.classList.add('hidden');
  lightboxImg.src = '';
}
lightboxBackdrop.addEventListener('click', closeLightbox);
lightboxClose.addEventListener('click', closeLightbox);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

// Open lightbox only if image actually loaded
function makeLightboxHandler(wrapEl, src) {
  wrapEl.addEventListener('click', () => {
    const img = wrapEl.querySelector('img');
    if (img && img.complete && img.naturalWidth > 0) openLightbox(src);
  });
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
const tabBtns  = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

tabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.tab;
    tabBtns.forEach(b => b.classList.toggle('active', b === btn));
    const pane = document.getElementById(`tab-${id}`);
    tabPanes.forEach(p => p.classList.toggle('active', p === pane));
    // Allow retry on error; skip if already successfully loaded
    if (pane.dataset.loaded !== 'ok') initTab(id, pane);
  });
});

// Init active tab immediately
const firstPane = document.querySelector('.tab-pane.active');
initTab('story', firstPane);

function initTab(id, pane) {
  pane.dataset.loaded = 'loading';
  const done = () => { pane.dataset.loaded = 'ok'; };
  const fail = () => { pane.dataset.loaded = 'error'; };

  switch (id) {
    case 'story':       initStory().then(done, fail);       break;
    case 'prompts':     initPrompts().then(done, fail);     break;
    case 'screenplay':  initScreenplay().then(done, fail);  break;
    case 'casting':     initCasting().then(done, fail);     break;
    case 'scenes':      initScenes().then(done, fail);      break;
    case 'qa':          initQA().then(done, fail);          break;
    case 'storyboards': initStoryboards().then(done, fail); break;
    case 'refinements': initRefinements().then(done, fail); break;
  }
}

// ── Story Text ────────────────────────────────────────────────────────────────
async function initStory() {
  const select  = document.getElementById('story-file-select');
  const content = document.getElementById('story-content');

  const CACHE_KEY = 'story-files';
  let found = JSON.parse(sessionStorage.getItem(CACHE_KEY) || 'null');

  if (!found) {
    const info = await loadServerInfo();
    if (info?.novels) {
      found = info.novels;
    } else {
      const candidates = [];
      for (let s = 1; s <= 2; s++)
        for (let e = 1; e <= 15; e++)
          candidates.push(`s0${s}e${String(e).padStart(2, '0')}.txt`);

      const results = await Promise.all(
        candidates.map(f => headExists(`${BASE}/${f}`).then(ok => ok ? f : null))
      );
      found = results.filter(Boolean).sort();
    }
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(found));
  }

  if (!found.length) {
    content.textContent = 'No story files found (s01e01.txt … s02e15.txt)';
    return;
  }

  found.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f;
    select.appendChild(opt);
  });

  select.addEventListener('change', async () => {
    if (!select.value) return;
    content.className = 'text-content';
    content.textContent = 'Loading…';
    try {
      content.textContent = await fetchText(`${BASE}/${select.value}`);
    } catch (e) {
      content.textContent = `Error: ${e.message}`;
    }
  });

  select.value = found[0];
  select.dispatchEvent(new Event('change'));
}

// ── Custom Prompts ────────────────────────────────────────────────────────────
let promptsDir = 'custom_prompts';

async function initPrompts() {
  const subTabs  = document.getElementById('prompts-tabs');
  const contentEl = document.getElementById('prompts-content');

  document.querySelectorAll('.toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      promptsDir = btn.dataset.dir;
      const active = subTabs.querySelector('.sub-tab-btn.active');
      loadPromptFile(active?.dataset.file || PROMPT_FILES[0], contentEl);
    });
  });

  subTabs.innerHTML = '';
  PROMPT_FILES.forEach((f, i) => {
    const b = el('button', `sub-tab-btn${i === 0 ? ' active' : ''}`);
    b.textContent = f.replace('.md', '');
    b.dataset.file = f;
    b.addEventListener('click', () => {
      subTabs.querySelectorAll('.sub-tab-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      loadPromptFile(f, contentEl);
    });
    subTabs.appendChild(b);
  });

  await loadPromptFile(PROMPT_FILES[0], contentEl);
}

async function loadPromptFile(file, el) {
  el.className = 'prose';
  el.textContent = 'Loading…';
  try {
    const text = await fetchText(`${BASE}/${promptsDir}/${file}`);
    if (file.endsWith('.md') && typeof marked !== 'undefined') {
      el.innerHTML = marked.parse(text);
    } else {
      el.className = 'text-content';
      el.textContent = text;
    }
  } catch {
    el.className = 'prose placeholder';
    el.textContent = `Not found: ${promptsDir}/${file}`;
  }
}

// ── Screenplay ────────────────────────────────────────────────────────────────
async function initScreenplay() {
  const metaEl = document.getElementById('screenplay-meta');
  const listEl = document.getElementById('screenplay-episodes');
  metaEl.innerHTML = '<span class="label">Loading…</span>';

  let data;
  try {
    data = await fetchJSON(PATHS.screenplay);
  } catch {
    try {
      data = await fetchJSON(PATHS.metadata);
    } catch (e) {
      metaEl.innerHTML = `<span class="error-msg">No screenplay found: ${esc(e.message)}</span>`;
      return;
    }
  }

  const episodes = data.episodes || [];
  metaEl.innerHTML = `
    <div class="meta-row"><span class="label">Title:</span><span class="value">${esc(data.title || '—')}</span></div>
    <div class="meta-row"><span class="label">Logline:</span><span class="value">${esc(data.logline || '—')}</span></div>
    <div class="meta-row"><span class="label">Characters:</span><span class="value">${esc((data.characters || []).join(', ') || '—')}</span></div>
    <div class="meta-row"><span class="label">Episodes:</span><span class="value">${episodes.length}</span></div>
  `;

  listEl.innerHTML = '';
  episodes.forEach(ep => {
    const card = el('div', 'episode-card');
    card.innerHTML = `
      <div class="episode-header">
        <span class="ep-num">${ep.episode_id}</span>
        <span class="ep-loc">${esc(ep.location || '')}</span>
        <span class="ep-time">${esc(ep.daytime || '')}</span>
        <span class="ep-chevron">▼</span>
      </div>
      <div class="episode-body">
        ${epField('Instructions', ep.screenplay_instructions)}
        ${epField('Narrative', ep.raw_narrative)}
        ${epField('Visual Continuity Rules', ep.visual_continuity_rules)}
      </div>
    `;
    card.querySelector('.episode-header').addEventListener('click', () => card.classList.toggle('open'));
    listEl.appendChild(card);
  });
}

function epField(label, val) {
  if (!val) return '';
  return `<div class="ep-field"><div class="ep-field-label">${esc(label)}</div><div class="ep-field-value">${esc(val)}</div></div>`;
}

// ── Casting ───────────────────────────────────────────────────────────────────
let castingAll = [];

async function initCasting() {
  const grid        = document.getElementById('casting-grid');
  const countEl     = document.getElementById('casting-count');
  const searchEl    = document.getElementById('casting-search');
  const typeFilterEl = document.getElementById('casting-type-filter');

  grid.innerHTML = 'Loading…';

  let refs = [];
  try {
    const listing = await fetchText(`${PATHS.refDir}/`);
    // Python SimpleHTTPServer generates href="filename.json" — filter out any with slashes (parent links etc.)
    const names = [...listing.matchAll(/href="([^"]+\.json)"/g)]
      .map(m => decodeURIComponent(m[1]))
      .filter(name => !name.includes('/'));

    const loaded = await Promise.all(names.map(async name => {
      const url = `${PATHS.refDir}/${name}`;
      try {
        const data = await fetchJSON(url);
        // Store actual filename (without .json) so PNG lookup uses the real on-disk name
        data._filename = name.replace(/\.json$/, '');
        return data;
      } catch (e) {
        console.warn('ref load failed:', url, e);
        return null;
      }
    }));
    refs = loaded.filter(Boolean);
  } catch {
    grid.innerHTML = '<span style="color:var(--text-muted)">ref_thriller/ not found or directory listing disabled.</span>';
    return;
  }

  castingAll = refs;
  countEl.textContent = refs.length;

  const types = [...new Set(refs.map(r => r.type || 'unknown'))].sort();
  types.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t;
    typeFilterEl.appendChild(opt);
  });

  const render = () => {
    const q = searchEl.value.toLowerCase();
    const t = typeFilterEl.value;
    const filtered = castingAll.filter(r =>
      (!q || (r.name || '').toLowerCase().includes(q) || (r.type || '').toLowerCase().includes(q)) &&
      (!t || r.type === t)
    );
    renderRefGrid(grid, filtered);
  };

  searchEl.addEventListener('input', render);
  typeFilterEl.addEventListener('change', render);
  render();
}

function renderRefGrid(container, refs) {
  container.innerHTML = '';
  if (!refs.length) {
    container.innerHTML = '<span style="color:var(--text-muted)">No results.</span>';
    return;
  }
  refs.forEach(ref => {
    // Use actual filename from disk (tracks JSON name, avoids capitalisation mismatch)
    const imgSrc  = `${PATHS.refDir}/${ref._filename || ref.name.toLowerCase().replace(/\s+/g, '-')}.png${CACHE_BUST}`;
    const typeCls = `type-${(ref.type || 'unknown').toLowerCase()}`;
    const card = el('div', 'ref-card');
    card.innerHTML = `
      <div class="ref-img-wrap">
        <img src="${esc(imgSrc)}" alt="${esc(ref.name)}" loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
        <div class="ref-img-placeholder" style="display:none">🎭</div>
      </div>
      <div class="ref-info">
        <div class="ref-name">${esc(ref.name)}</div>
        <span class="ref-type-badge ${esc(typeCls)}">${esc(ref.type || 'unknown')}</span>
        ${ref.logline_subject_info ? `<div class="ref-logline ref-logline-labeled"><b>Logline:</b> ${esc(ref.logline_subject_info)}</div>` : ''}
        ${ref.visual_desc ? `<details class="ref-desc-details"><summary>Visual desc</summary><div class="ref-logline">${esc(ref.visual_desc)}</div></details>` : ''}
      </div>
    `;
    makeLightboxHandler(card.querySelector('.ref-img-wrap'), imgSrc);
    container.appendChild(card);
  });
}

// ── Scenes ────────────────────────────────────────────────────────────────────
async function initScenes() {
  const sceneSelect = document.getElementById('scene-select');
  const contentEl   = document.getElementById('scenes-content');

  const sceneFiles = await discoverSceneFiles();
  if (!sceneFiles.length) {
    contentEl.innerHTML = '<span class="placeholder">No scene files found in cinematic_render/.</span>';
    return;
  }

  sceneFiles.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.url; opt.textContent = f.label;
    sceneSelect.appendChild(opt);
  });

  sceneSelect.addEventListener('change', async () => {
    if (!sceneSelect.value) return;
    contentEl.innerHTML = 'Loading…';
    try {
      const data = await fetchJSON(sceneSelect.value);
      renderScenes(contentEl, data, sceneSelect.value);
    } catch (e) {
      contentEl.innerHTML = `<span class="error-msg">${esc(e.message)}</span>`;
    }
  });

  sceneSelect.value = sceneFiles[0].url;
  sceneSelect.dispatchEvent(new Event('change'));
}

async function discoverSceneFiles() {
  const CACHE_KEY = 'scene-files';
  const cached = sessionStorage.getItem(CACHE_KEY);
  if (cached) return JSON.parse(cached);

  const files = [];
  const info = await loadServerInfo();

  if (info) {
    if (info.has_metadata)
      files.push({ url: PATHS.metadata, label: 'animation_metadata.json (merged)' });
    (info.scene_files || []).forEach(({ episode, has_refined, has_raw }) => {
      const n = String(episode).padStart(3, '0');
      const refined = `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`;
      const raw     = `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`;
      if (has_refined) files.push({ url: refined, label: `Episode ${episode} (refined)` });
      else if (has_raw) files.push({ url: raw, label: `Episode ${episode}` });
    });
  } else {
    // Fallback: probe all episode files in parallel
    if (await headExists(PATHS.metadata))
      files.push({ url: PATHS.metadata, label: 'animation_metadata.json (merged)' });

    const checks = Array.from({ length: MAX_EPISODES }, (_, i) => {
      const n = String(i + 1).padStart(3, '0');
      const refined = `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`;
      const raw     = `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`;
      return Promise.all([headExists(refined), headExists(raw)]).then(([hasRefined, hasRaw]) => ({
        i: i + 1, n, refined, raw, hasRefined, hasRaw,
      }));
    });
    const results = await Promise.all(checks);
    results.forEach(({ i, n, refined, raw, hasRefined, hasRaw }) => {
      if (hasRefined) files.push({ url: refined, label: `Episode ${i} (refined)` });
      else if (hasRaw) files.push({ url: raw, label: `Episode ${i}` });
    });
  }

  sessionStorage.setItem(CACHE_KEY, JSON.stringify(files));
  return files;
}

function renderScenes(container, data, sourceUrl) {
  container.innerHTML = '';
  const scenes = data.scenes || [];
  if (!scenes.length) {
    container.innerHTML = '<span class="placeholder">No scenes in this file.</span>';
    return;
  }

  // Storyboard grid — only available for single-episode files
  const episodeNum = sourceUrl.match(/(\d{3})(?:_refined)?\.json$/)?.[1];
  if (episodeNum) {
    const gridUrl = `${PATHS.sceneGrid}/scene_${episodeNum}_grid_combined.png${CACHE_BUST}`;
    const wrap = el('div', 'storyboard-img-wrap');
    wrap.innerHTML = `<img src="${esc(gridUrl)}" alt="Storyboard ${episodeNum}"
      loading="lazy" onerror="this.parentElement.style.display='none'">`;
    makeLightboxHandler(wrap, gridUrl);
    container.appendChild(wrap);
  }

  scenes.forEach(scene => {
    const block = el('div', 'scene-block');
    block.innerHTML = `
      <div class="scene-block-header">
        <span class="scene-num">Scene ${scene.scene_id}</span>
        <span class="scene-loc">${esc(scene.location || '')}</span>
        <span class="scene-chevron">▼</span>
      </div>
      <div class="scene-panels"></div>
    `;
    block.querySelector('.scene-block-header').addEventListener('click', () => block.classList.toggle('open'));
    const panelsEl = block.querySelector('.scene-panels');
    (scene.panels || []).forEach(panel => panelsEl.appendChild(renderPanelCard(scene, panel)));
    container.appendChild(block);
  });
}

// Map a reference name to its image URL, using castingAll if already loaded
function refUrl(name) {
  const found = castingAll.find(r => r.name === name);
  const filename = found?._filename ?? name.toLowerCase().replace(/\s+/g, '-');
  return `${PATHS.refDir}/${filename}.png${CACHE_BUST}`;
}

function renderPanelCard(scene, panel) {
  const sceneId = String(scene.scene_id).padStart(3, '0');
  const panelId = String(panel.panel_index).padStart(2, '0');
  const imgUrl  = `${PATHS.panels}/${sceneId}_${panelId}_static.png${CACHE_BUST}`;
  const hookCls = `hook-${(panel.hook_type || 'none').replace(/[^a-z_]/g, '_')}`;

  const allRefs = [...(panel.references || []), ...(panel.location_references || [])];

  const card = el('div', 'panel-card');
  card.innerHTML = `
    <div class="panel-top-row">
      <div class="panel-img-wrap">
        <img src="${esc(imgUrl)}" alt="Panel ${panel.panel_index}" loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
        <div class="panel-img-placeholder" style="display:none">🎬</div>
      </div>
      <div class="panel-speech">
        <div class="panel-idx">Panel ${panel.panel_index}
          <span class="panel-hook ${hookCls}">${esc(panel.hook_type || 'none')}</span>
          ${panel.is_reversed ? '<span class="reversed-badge">REV</span>' : ''}
        </div>
        ${panel.dialogue  ? `<div class="panel-field dialogue">💬 ${esc(panel.dialogue)}</div>` : '<div class="panel-field panel-no-speech">No dialogue</div>'}
        ${panel.voiceover ? `<div class="panel-field voiceover">🎙 ${esc(panel.voiceover)}</div>` : ''}
        ${allRefs.length ? `
        <div class="panel-refs">
          ${allRefs.map(name => `<img class="panel-ref-thumb" src="${esc(refUrl(name))}" title="${esc(name)}" loading="lazy" onerror="this.style.display='none'">`).join('')}
        </div>` : ''}
      </div>
    </div>
    <div class="panel-details">
      <div class="panel-field"><b>Beat:</b> ${esc(panel.emotional_beat || '')}</div>
      ${panel.lights_and_camera ? `<div class="panel-field"><b>Camera:</b> ${esc(panel.lights_and_camera)}</div>` : ''}
      <div class="panel-field"><b>Start:</b> ${esc(panel.visual_start || '')}</div>
      <div class="panel-field"><b>End:</b> ${esc(panel.visual_end || '')}</div>
      ${panel.visual_disposition ? `<div class="panel-field panel-field-disposition"><b>Disposition:</b> ${esc(panel.visual_disposition)}</div>` : ''}
      ${panel.motion_prompt ? `<div class="panel-field"><b>Motion:</b> ${esc(panel.motion_prompt)}</div>` : ''}
      ${panel.sound_design  ? `<div class="panel-field">🔊 ${esc(panel.sound_design)}</div>` : ''}
    </div>
  `;

  makeLightboxHandler(card.querySelector('.panel-img-wrap'), imgUrl);
  card.querySelectorAll('.panel-ref-thumb').forEach(img => {
    img.addEventListener('click', () => {
      if (img.complete && img.naturalWidth > 0) openLightbox(img.src);
    });
  });
  return card;
}

// ── QA ────────────────────────────────────────────────────────────────────────
async function initQA() {
  const summaryEl = document.getElementById('qa-summary');
  const contentEl = document.getElementById('qa-content');
  summaryEl.innerHTML = 'Loading…';

  let report;
  try {
    report = await fetchJSON(PATHS.qa);
  } catch (e) {
    summaryEl.innerHTML = `<span class="error-msg">quality_report.json not found: ${esc(e.message)}</span>`;
    return;
  }

  // Real format from critic.py:
  // { threshold, total_panels, needs_refinement, avg_fidelity,
  //   panels: [{scene_id, panel_id, fidelity, character_consistency,
  //             composition_match, artifacts, needs_refinement, refinement_prompt, reasoning}] }
  const panels = report.panels || [];
  if (!panels.length) {
    summaryEl.innerHTML = '<span class="error-msg">No panels in report.</span>';
    return;
  }

  // Use pre-computed stats from file; fall back to computing if absent (older format)
  const totalPanels = report.total_panels ?? panels.length;
  const needsRef    = report.needs_refinement ?? panels.filter(p => p.needs_refinement).length;
  const avgFid      = report.avg_fidelity ?? (panels.reduce((s, p) => s + (p.fidelity || 0), 0) / panels.length);
  const threshold   = report.threshold ?? '—';

  summaryEl.innerHTML = `
    <div class="meta-row"><span class="label">Panels:</span><span class="value">${totalPanels}</span></div>
    <div class="meta-row"><span class="label">Needs refinement:</span><span class="value" style="color:var(--red)">${needsRef}</span></div>
    <div class="meta-row"><span class="label">Avg fidelity:</span><span class="value">${Number(avgFid).toFixed(1)}/10</span></div>
    <div class="meta-row"><span class="label">Threshold:</span><span class="value">${threshold}</span></div>
  `;

  // Group by scene_id for display
  const byScene = new Map();
  panels.forEach(p => {
    const sid = p.scene_id;
    if (!byScene.has(sid)) byScene.set(sid, []);
    byScene.get(sid).push(p);
  });

  contentEl.innerHTML = '';
  [...byScene.entries()].sort((a, b) => a[0] - b[0]).forEach(([sceneId, scenePanels]) => {
    const block = el('div', 'qa-scene-block');
    block.innerHTML = `<div class="qa-scene-title">Scene ${sceneId}</div>`;
    const grid = el('div', 'qa-grid');
    scenePanels.forEach(p => {
      const card = el('div', `qa-card ${p.needs_refinement ? 'needs-refinement' : 'ok'}`);
      card.innerHTML = `
        <div class="qa-panel-id">Panel ${p.panel_id}
          ${p.needs_refinement
            ? '<span class="needs-refinement-badge">⚠ Needs refinement</span>'
            : '<span class="ok-badge">✓ OK</span>'}
        </div>
        <div class="qa-scores">
          ${qaScore('Fidelity', p.fidelity)}
          ${qaScore('Chars',    p.character_consistency)}
          ${qaScore('Comp',     p.composition_match)}
        </div>
        ${p.artifacts?.length ? `<div class="qa-artifacts"><ul>${p.artifacts.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div>` : ''}
        <div class="qa-reasoning">${esc(p.reasoning || '')}</div>
        ${p.needs_refinement && p.refinement_prompt ? `<div class="qa-refinement-prompt">Fix: ${esc(p.refinement_prompt)}</div>` : ''}
      `;
      grid.appendChild(card);
    });
    block.appendChild(grid);
    contentEl.appendChild(block);
  });
}

function qaScore(label, val) {
  const v = val ?? 0;
  return `<div class="qa-score"><span class="qa-score-label">${label}</span><span class="qa-score-val ${scoreClass(v)}">${v}</span></div>`;
}

// ── Storyboards ───────────────────────────────────────────────────────────────
async function initStoryboards() {
  const container = document.getElementById('storyboards-content');
  container.textContent = 'Loading…';

  const info = await loadServerInfo();
  const storyboards = info?.storyboards;

  if (!storyboards?.length) {
    container.className = 'placeholder';
    container.textContent = 'No storyboard images found. Run `make webserver` to refresh server-info.json.';
    return;
  }

  container.className = 'sb-list';
  container.innerHTML = '';

  storyboards.forEach(({ scene, current, backups }) => {
    const row   = el('div', 'sb-row');
    const badge = el('div', 'sb-scene-badge', String(scene).padStart(3, '0'));
    const body  = el('div', 'sb-body');

    // Primary pair: current + first backup side-by-side
    const primary = el('div', 'sb-primary-pair');

    if (current) {
      const url = `${BASE}/${current}${CACHE_BUST}`;
      primary.appendChild(sbPrimaryItem(url, 'Current'));
    }

    const firstBackup = backups?.[0];
    if (firstBackup) {
      const url       = `${BASE}/${firstBackup}${CACHE_BUST}`;
      const dateMatch = firstBackup.match(/backup-(\d{8}(?:-\d+)?)/);
      const label     = dateMatch ? `Original (${dateMatch[1]})` : 'Original';
      primary.appendChild(sbPrimaryItem(url, label));
    }

    body.appendChild(primary);

    // Remaining backups below as small thumbnails
    const extraBackups = (backups || []).slice(1);
    if (extraBackups.length) {
      const secondaryEl = el('div', 'sb-secondary');
      extraBackups.forEach(bpath => {
        const url       = `${BASE}/${bpath}${CACHE_BUST}`;
        const dateMatch = bpath.match(/backup-(\d{8}(?:-\d+)?)/);
        const label     = dateMatch ? dateMatch[1] : 'backup';
        const wrap      = el('div', 'sb-backup-item');
        wrap.innerHTML  = `<img src="${esc(url)}" alt="${esc(label)}" loading="lazy"
             onerror="this.parentElement.style.display='none'">
           <div class="sb-backup-label">${esc(label)}</div>`;
        makeLightboxHandler(wrap, url);
        secondaryEl.appendChild(wrap);
      });
      body.appendChild(secondaryEl);
    }

    row.appendChild(badge);
    row.appendChild(body);
    container.appendChild(row);
  });
}

function sbPrimaryItem(url, label) {
  const wrap = el('div', 'sb-primary-item');
  wrap.innerHTML = `
    <div class="sb-primary-label">${esc(label)}</div>
    <div class="sb-primary-img-wrap">
      <img src="${esc(url)}" alt="${esc(label)}" loading="lazy"
           onerror="this.parentElement.style.display='none'">
    </div>
  `;
  makeLightboxHandler(wrap.querySelector('.sb-primary-img-wrap'), url);
  return wrap;
}

// ── Refinements ───────────────────────────────────────────────────────────────
async function initRefinements() {
  const container = document.getElementById('refinements-content');
  container.innerHTML = 'Scanning for refined scene files…';

  const pairs = await collectRefinementPairs();
  if (!pairs.length) {
    container.className = 'placeholder';
    container.textContent = 'No refined scene files found (_refined.json).';
    return;
  }

  container.className = 'refinements-list';
  container.innerHTML = '';

  pairs.forEach(pair => {
    const card = el('div', 'refinement-card');
    card.innerHTML = `
      <div class="refinement-header">
        <span class="ep-num">${pair.episodeNum}</span>
        <span>${esc(pair.label)}</span>
        <span class="refinement-chevron">▼</span>
      </div>
      <div class="refinement-body">Click to load…</div>
    `;
    card.querySelector('.refinement-header').addEventListener('click', async () => {
      card.classList.toggle('open');
      if (card.classList.contains('open') && !card._loaded) {
        const body = card.querySelector('.refinement-body');
        try {
          await loadRefinementDiff(body, pair);
          card._loaded = true;  // mark loaded only on success — allows retry on error
        } catch (e) {
          body.innerHTML = `<span class="error-msg">${esc(e.message)}</span>`;
        }
      }
    });
    container.appendChild(card);
  });
}

async function collectRefinementPairs() {
  const CACHE_KEY = 'refinement-pairs';
  const cached = sessionStorage.getItem(CACHE_KEY);
  if (cached) return JSON.parse(cached);

  const info = await loadServerInfo();
  let results;

  if (info) {
    results = (info.scene_files || [])
      .filter(f => f.has_refined)
      .map(({ episode }) => {
        const n = String(episode).padStart(3, '0');
        return {
          episodeNum: episode,
          label: `Episode ${episode}`,
          refinedUrl: `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`,
          rawUrl:     `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`,
        };
      });
  } else {
    const checks = Array.from({ length: MAX_EPISODES }, (_, i) => {
      const n = String(i + 1).padStart(3, '0');
      const refinedUrl = `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`;
      const rawUrl     = `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`;
      return headExists(refinedUrl).then(ok => ok
        ? { episodeNum: i + 1, label: `Episode ${i + 1}`, refinedUrl, rawUrl }
        : null
      );
    });
    results = (await Promise.all(checks)).filter(Boolean);
  }

  sessionStorage.setItem(CACHE_KEY, JSON.stringify(results));
  return results;
}

async function loadRefinementDiff(container, pair) {
  const [refined, raw] = await Promise.all([
    fetchJSON(pair.refinedUrl),
    fetchJSON(pair.rawUrl).catch(() => null),
  ]);

  const refinedScenes = refined.scenes || [];
  if (!refinedScenes.length) {
    container.textContent = 'No scenes.';
    return;
  }

  container.innerHTML = '';
  refinedScenes.forEach(scene => {
    const rawScene = (raw?.scenes || []).find(s => s.scene_id === scene.scene_id);
    container.appendChild(el('div', 'qa-scene-title', `Scene ${scene.scene_id} — ${esc(scene.location || '')}`));

    (scene.panels || []).forEach(panel => {
      const rawPanel    = (rawScene?.panels || []).find(p => p.panel_index === panel.panel_index);
      const startChanged = rawPanel && rawPanel.visual_start !== panel.visual_start;
      const endChanged   = rawPanel && rawPanel.visual_end   !== panel.visual_end;

      const block = el('div', 'refinement-card');
      block.style.cssText = 'margin-bottom:8px;overflow:visible';
      block.innerHTML = `
        <div style="padding:8px 12px;font-weight:700;font-size:12px;color:var(--accent)">
          Panel ${panel.panel_index}
          ${startChanged || endChanged
            ? '<span style="color:var(--yellow);margin-left:8px">✏ changed</span>'
            : '<span style="color:var(--green);margin-left:8px">= same</span>'}
        </div>
        ${startChanged || !rawPanel ? diffRow('Visual Start', rawPanel?.visual_start, panel.visual_start) : ''}
        ${endChanged   || !rawPanel ? diffRow('Visual End',   rawPanel?.visual_end,   panel.visual_end)   : ''}
        ${panel.motion_prompt ? `<div style="padding:4px 12px 8px;font-size:11px;color:var(--text-muted)"><b>Motion:</b> ${esc(panel.motion_prompt)}</div>` : ''}
      `;
      container.appendChild(block);
    });
  });
}

function diffRow(label, before, after) {
  if (!before && !after) return '';
  return `
    <div style="padding:4px 12px 8px">
      <div class="diff-col-label">${esc(label)}</div>
      <div class="diff-block">
        <div class="diff-col"><div class="diff-col-label">Before</div><div class="diff-before">${esc(before || '(none)')}</div></div>
        <div class="diff-col"><div class="diff-col-label">After</div><div class="diff-after">${esc(after || '(none)')}</div></div>
      </div>
    </div>
  `;
}
