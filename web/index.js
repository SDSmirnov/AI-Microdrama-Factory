'use strict';

// ── Config ──────────────────────────────────────────────────────────────────
const BASE = '..';  // workdir is served as static root

const PATHS = {
  screenplay:    `${BASE}/cinematic_render/animation_episodes.json`,
  metadata:      `${BASE}/cinematic_render/animation_metadata.json`,
  qa:            `${BASE}/cinematic_render/quality_report.json`,
  pipelineState: `${BASE}/cinematic_render/pipeline_state.json`,
  refDir:        `${BASE}/ref_thriller`,
  customPrompts: `${BASE}/custom_prompts`,
  prompts:       `${BASE}/prompts`,
  panels:        `${BASE}/cinematic_render/panels`,
  sceneGrid:     `${BASE}/cinematic_render`,
};

const PROMPT_FILES = ['style.md', 'casting.md', 'scenery.md', 'imagery.md', 'setting.md'];

// ── Helpers ──────────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function fetchText(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.text();
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

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Lightbox ─────────────────────────────────────────────────────────────────
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

// ── Tabs ─────────────────────────────────────────────────────────────────────
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');
const tabLoaded = {};

tabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.tab;
    tabBtns.forEach(b => b.classList.toggle('active', b === btn));
    tabPanes.forEach(p => p.classList.toggle('active', p.id === `tab-${id}`));
    if (!tabLoaded[id]) {
      tabLoaded[id] = true;
      initTab(id);
    }
  });
});

// Init active tab immediately
tabLoaded['story'] = true;
initTab('story');

function initTab(id) {
  switch (id) {
    case 'story':       initStory();       break;
    case 'prompts':     initPrompts();     break;
    case 'screenplay':  initScreenplay();  break;
    case 'casting':     initCasting();     break;
    case 'scenes':      initScenes();      break;
    case 'qa':          initQA();          break;
    case 'refinements': initRefinements(); break;
  }
}

// ── Story Text ───────────────────────────────────────────────────────────────
async function initStory() {
  const select = document.getElementById('story-file-select');
  const content = document.getElementById('story-content');

  // Discover .txt files by trying known patterns
  const candidates = [];
  for (let s = 1; s <= 3; s++) {
    for (let e = 1; e <= 30; e++) {
      candidates.push(`s0${s}e${String(e).padStart(2,'0')}.txt`);
    }
  }
  const found = [];
  await Promise.all(candidates.map(async f => {
    try {
      const r = await fetch(`${BASE}/${f}`, { method: 'HEAD' });
      if (r.ok) found.push(f);
    } catch {}
  }));
  found.sort();

  if (!found.length) {
    content.textContent = 'No story files found (s01e01.txt, etc.)';
    return;
  }

  found.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f;
    opt.textContent = f;
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

  // Auto-load first
  select.value = found[0];
  select.dispatchEvent(new Event('change'));
}

// ── Custom Prompts ────────────────────────────────────────────────────────────
let promptsDir = 'custom_prompts';

async function initPrompts() {
  const subTabs = document.getElementById('prompts-tabs');
  const contentEl = document.getElementById('prompts-content');

  document.querySelectorAll('.toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      promptsDir = btn.dataset.dir;
      loadPromptFile(subTabs.querySelector('.sub-tab-btn.active')?.dataset.file || PROMPT_FILES[0], contentEl);
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

  loadPromptFile(PROMPT_FILES[0], contentEl);
}

async function loadPromptFile(file, el) {
  el.className = 'text-content';
  el.textContent = 'Loading…';
  try {
    el.textContent = await fetchText(`${BASE}/${promptsDir}/${file}`);
  } catch (e) {
    el.className = 'text-content placeholder';
    el.textContent = `Not found: ${promptsDir}/${file}`;
  }
}

// ── Screenplay ───────────────────────────────────────────────────────────────
async function initScreenplay() {
  const metaEl = document.getElementById('screenplay-meta');
  const listEl = document.getElementById('screenplay-episodes');
  metaEl.innerHTML = '<span class="label">Loading…</span>';

  let data;
  try {
    data = await fetchJSON(PATHS.screenplay);
  } catch {
    // Try metadata fallback
    try {
      data = await fetchJSON(PATHS.metadata);
    } catch (e) {
      metaEl.innerHTML = `<span class="error-msg">No screenplay found: ${e.message}</span>`;
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
  const grid = document.getElementById('casting-grid');
  const countEl = document.getElementById('casting-count');
  const searchEl = document.getElementById('casting-search');
  const typeFilterEl = document.getElementById('casting-type-filter');

  grid.innerHTML = 'Loading…';

  // Collect all ref JSONs by probing listing or brute-force
  let refs = [];
  try {
    // Try to get directory listing (works if server provides it)
    const listing = await fetchText(`${PATHS.refDir}/`);
    const names = [...listing.matchAll(/href="([^"]+\.json)"/g)].map(m => m[1]);
    refs = await Promise.all(names.map(async n => {
      const url = `${PATHS.refDir}/${n.replace(/^.*\//, '')}`;
      try { return await fetchJSON(url); } catch { return null; }
    }));
    refs = refs.filter(Boolean);
  } catch {
    grid.innerHTML = '<span class="text-muted">ref_thriller/ directory not found or empty.</span>';
    return;
  }

  castingAll = refs;
  countEl.textContent = refs.length;

  // Populate type filter
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
    const imgSrc = `${PATHS.refDir}/${ref.name}.png`;
    const typeCls = `type-${(ref.type || 'unknown').toLowerCase()}`;
    const card = el('div', 'ref-card');
    card.innerHTML = `
      <div class="ref-img-wrap">
        <img src="${imgSrc}" alt="${esc(ref.name)}" loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
        <div class="ref-img-placeholder" style="display:none">🎭</div>
      </div>
      <div class="ref-info">
        <div class="ref-name">${esc(ref.name)}</div>
        <span class="ref-type-badge ${typeCls}">${esc(ref.type || 'unknown')}</span>
        <div class="ref-logline">${esc(ref.logline_subject_info || ref.video_visual_desc || '')}</div>
      </div>
    `;
    card.querySelector('.ref-img-wrap').addEventListener('click', () => openLightbox(imgSrc));
    container.appendChild(card);
  });
}

// ── Scenes ────────────────────────────────────────────────────────────────────
async function initScenes() {
  const sceneSelect = document.getElementById('scene-select');
  const contentEl = document.getElementById('scenes-content');

  // Discover scene files
  const sceneFiles = await discoverSceneFiles();

  if (!sceneFiles.length) {
    contentEl.innerHTML = '<span class="placeholder">No scene files found in cinematic_render/.</span>';
    return;
  }

  sceneFiles.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.url;
    opt.textContent = f.label;
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
  const files = [];
  // Try metadata first — best source
  try {
    await fetchJSON(PATHS.metadata);
    files.push({ url: PATHS.metadata, label: 'animation_metadata.json (merged)' });
  } catch {}

  // Probe numbered scene files
  for (let i = 1; i <= 50; i++) {
    const n = String(i).padStart(3, '0');
    const urls = [
      { url: `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`, label: `Episode ${i} (refined)` },
      { url: `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`, label: `Episode ${i}` },
    ];
    for (const u of urls) {
      try {
        const r = await fetch(u.url, { method: 'HEAD' });
        if (r.ok) { files.push(u); break; }
      } catch {}
    }
  }
  return files;
}

function renderScenes(container, data, sourceUrl) {
  container.innerHTML = '';
  const scenes = data.scenes || [];
  if (!scenes.length) {
    container.innerHTML = '<span class="placeholder">No scenes in this file.</span>';
    return;
  }

  // Storyboard grid image if available
  const episodeNum = sourceUrl.match(/(\d{3})(?:_refined)?\.json$/)?.[1];
  if (episodeNum) {
    const gridUrl = `${PATHS.sceneGrid}/scene_${episodeNum}_grid_combined.png`;
    const wrap = el('div', 'storyboard-img-wrap');
    wrap.innerHTML = `<img src="${gridUrl}" alt="Storyboard ${episodeNum}"
      onerror="this.parentElement.style.display='none'"
      onclick="">`;
    wrap.querySelector('img').addEventListener('click', () => openLightbox(gridUrl));
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
    (scene.panels || []).forEach(panel => {
      panelsEl.appendChild(renderPanelCard(scene, panel));
    });

    container.appendChild(block);
  });
}

function renderPanelCard(scene, panel) {
  const sceneId = String(scene.scene_id).padStart(3, '0');
  const panelId = String(panel.panel_index).padStart(2, '0');
  const imgUrl = `${PATHS.panels}/${sceneId}_${panelId}_static.png`;
  const hookCls = `hook-${(panel.hook_type || 'none').replace(/[^a-z_]/g,'_')}`;

  const card = el('div', 'panel-card');
  card.innerHTML = `
    <div class="panel-img-wrap">
      <img src="${imgUrl}" alt="Panel ${panel.panel_index}" loading="lazy"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="panel-img-placeholder" style="display:none">🎬</div>
    </div>
    <div class="panel-meta">
      <div class="panel-idx">Panel ${panel.panel_index}
        <span class="panel-hook ${hookCls}">${esc(panel.hook_type || 'none')}</span>
        ${panel.is_reversed ? '<span class="reversed-badge">REV</span>' : ''}
      </div>
      <div class="panel-beat"><b>Beat:</b> ${esc(panel.emotional_beat || '')}</div>
      ${panel.dialogue ? `<div class="panel-field dialogue">💬 ${esc(panel.dialogue)}</div>` : ''}
      ${panel.voiceover ? `<div class="panel-field">🎙 ${esc(panel.voiceover)}</div>` : ''}
      <div class="panel-field"><b>Start:</b> ${esc((panel.visual_start || '').slice(0, 120))}${panel.visual_start?.length > 120 ? '…' : ''}</div>
      <div class="panel-field"><b>End:</b> ${esc((panel.visual_end || '').slice(0, 120))}${panel.visual_end?.length > 120 ? '…' : ''}</div>
      ${panel.motion_prompt ? `<div class="panel-field"><b>Motion:</b> ${esc((panel.motion_prompt || '').slice(0,100))}…</div>` : ''}
      ${panel.sound_design ? `<div class="panel-field">🔊 ${esc(panel.sound_design)}</div>` : ''}
    </div>
  `;
  card.querySelector('.panel-img-wrap').addEventListener('click', () => openLightbox(imgUrl));
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
    summaryEl.innerHTML = `<span class="error-msg">quality_report.json not found</span>`;
    contentEl.innerHTML = '';
    return;
  }

  // report is {scene_id: {panel_index: {fidelity, ...}}} or flat array
  // Normalise to [{scene_id, panels: [{panel_index, ...}]}]
  const scenes = normalizeQAReport(report);

  const totalPanels = scenes.reduce((s, sc) => s + sc.panels.length, 0);
  const needsRef = scenes.reduce((s, sc) => s + sc.panels.filter(p => p.needs_refinement).length, 0);
  const avgFid = scenes.reduce((s, sc) => s + sc.panels.reduce((a,p) => a + (p.fidelity||0), 0), 0) / (totalPanels || 1);

  summaryEl.innerHTML = `
    <div class="meta-row"><span class="label">Scenes:</span><span class="value">${scenes.length}</span></div>
    <div class="meta-row"><span class="label">Panels:</span><span class="value">${totalPanels}</span></div>
    <div class="meta-row"><span class="label">Needs refinement:</span><span class="value" style="color:var(--red)">${needsRef}</span></div>
    <div class="meta-row"><span class="label">Avg fidelity:</span><span class="value">${avgFid.toFixed(1)}/10</span></div>
  `;

  contentEl.innerHTML = '';
  scenes.forEach(scene => {
    const block = el('div', 'qa-scene-block');
    block.innerHTML = `<div class="qa-scene-title">Scene ${scene.scene_id}</div>`;
    const grid = el('div', 'qa-grid');
    scene.panels.forEach(p => {
      const card = el('div', `qa-card ${p.needs_refinement ? 'needs-refinement' : 'ok'}`);
      card.innerHTML = `
        <div class="qa-panel-id">Panel ${p.panel_index}
          ${p.needs_refinement
            ? '<span class="needs-refinement-badge">⚠ Needs refinement</span>'
            : '<span class="ok-badge">✓ OK</span>'}
        </div>
        <div class="qa-scores">
          ${qaScore('Fidelity', p.fidelity)}
          ${qaScore('Chars', p.character_consistency)}
          ${qaScore('Comp', p.composition_match)}
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

function normalizeQAReport(report) {
  // Format A: [{scene_id, panels: [{panel_index, ...}]}]
  if (Array.isArray(report) && report[0]?.panels) return report;
  // Format B: {scene_id: [{panel_index, ...}]}
  if (typeof report === 'object' && !Array.isArray(report)) {
    return Object.entries(report).map(([scene_id, panels]) => ({
      scene_id: Number(scene_id) || scene_id,
      panels: Array.isArray(panels) ? panels : Object.entries(panels).map(([pi, data]) => ({panel_index: Number(pi), ...data}))
    })).sort((a,b) => a.scene_id - b.scene_id);
  }
  // Format C: flat array of {scene_id, panel_index, ...}
  if (Array.isArray(report) && report[0]?.scene_id !== undefined) {
    const byScene = {};
    report.forEach(item => {
      (byScene[item.scene_id] = byScene[item.scene_id] || []).push(item);
    });
    return Object.entries(byScene).map(([k,v]) => ({scene_id:Number(k)||k, panels:v}))
                 .sort((a,b) => a.scene_id - b.scene_id);
  }
  return [];
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

  for (const pair of pairs) {
    const card = el('div', 'refinement-card');
    const label = pair.label;
    card.innerHTML = `
      <div class="refinement-header">
        <span class="ep-num">${pair.episodeNum}</span>
        <span>${esc(label)}</span>
        <span class="refinement-chevron">▼</span>
      </div>
      <div class="refinement-body">Loading…</div>
    `;
    card.querySelector('.refinement-header').addEventListener('click', async () => {
      card.classList.toggle('open');
      if (card.classList.contains('open') && !card._loaded) {
        card._loaded = true;
        await loadRefinementDiff(card.querySelector('.refinement-body'), pair);
      }
    });
    container.appendChild(card);
  }
}

async function collectRefinementPairs() {
  const pairs = [];
  for (let i = 1; i <= 50; i++) {
    const n = String(i).padStart(3, '0');
    const refinedUrl = `${PATHS.sceneGrid}/animation_episode_scenes_${n}_refined.json`;
    const rawUrl     = `${PATHS.sceneGrid}/animation_episode_scenes_${n}.json`;
    try {
      const r = await fetch(refinedUrl, { method: 'HEAD' });
      if (r.ok) pairs.push({ episodeNum: i, label: `Episode ${i}`, refinedUrl, rawUrl });
    } catch {}
  }
  return pairs;
}

async function loadRefinementDiff(container, pair) {
  try {
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
      const sceneHeader = el('div', 'qa-scene-title', `Scene ${scene.scene_id} — ${esc(scene.location || '')}`);
      container.appendChild(sceneHeader);

      (scene.panels || []).forEach(panel => {
        const rawPanel = (rawScene?.panels || []).find(p => p.panel_index === panel.panel_index);
        const block = el('div', 'refinement-card');
        block.style.marginBottom = '8px';
        block.style.overflow = 'visible';

        const startChanged = rawPanel && rawPanel.visual_start !== panel.visual_start;
        const endChanged   = rawPanel && rawPanel.visual_end   !== panel.visual_end;

        block.innerHTML = `
          <div style="padding:8px 12px;font-weight:700;font-size:12px;color:var(--accent)">
            Panel ${panel.panel_index}
            ${startChanged || endChanged ? '<span style="color:var(--yellow);margin-left:8px">✏ changed</span>' : '<span style="color:var(--green);margin-left:8px">= same</span>'}
          </div>
          ${startChanged || !rawPanel ? diffRow('Visual Start', rawPanel?.visual_start, panel.visual_start) : ''}
          ${endChanged   || !rawPanel ? diffRow('Visual End',   rawPanel?.visual_end,   panel.visual_end)   : ''}
          ${panel.motion_prompt ? `<div style="padding:4px 12px 8px;font-size:11px;color:var(--text-muted)"><b>Motion:</b> ${esc(panel.motion_prompt)}</div>` : ''}
        `;
        container.appendChild(block);
      });
    });
  } catch (e) {
    container.innerHTML = `<span class="error-msg">${esc(e.message)}</span>`;
  }
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
