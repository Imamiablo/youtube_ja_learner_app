const appRoot = document.getElementById('app');
if (appRoot) {
  const articleId = Number(appRoot.dataset.articleId);
  const sourceValue = appRoot.dataset.sourceValue || '';
  let article = null;
  let player = null;
  let currentSegmentId = null;
  let syncTimer = null;
  let contextCache = new Map();
  let autoContextInFlight = false;
  let hoverCard = null;

  const state = {
    tab: 'watch',
    showTranslation: true,
    showFurigana: true,
    autoContext: true,
    targetLanguage: localStorage.getItem('jp_watch_target_language') || appRoot.dataset.defaultTargetLanguage || 'English',
    apiKey: localStorage.getItem('jp_watch_api_key') || '',
    baseUrl: localStorage.getItem('jp_watch_base_url') || appRoot.dataset.defaultBaseUrl || 'http://localhost:11434/',
    model: localStorage.getItem('jp_watch_model') || appRoot.dataset.defaultModel || 'qwen3-coder:30b',
    vocabFilter: 'recommended',
    hideIgnored: true,
  };

  function escapeHtml(text) {
    return String(text || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  }
  function timeFmt(sec) {
    const total = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h > 0 ? `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function truncate(text, maxLen) { text = String(text || ''); return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text; }

  function renderShell() {
    appRoot.innerHTML = `
      <main class="container">
        <div class="header-row">
          <div>
            <div class="eyebrow">Single-app build</div>
            <h1 id="title">Loading…</h1>
            <div class="muted small" id="subtitle"></div>
          </div>
          <div class="header-actions">
            <a class="button" href="/">Home</a>
            <button id="openFullVideoBtn">Open on YouTube</button>
            <button id="deleteArticleBtn">Delete article</button>
          </div>
        </div>
        <div id="message"></div>
        <div class="article-tabs" id="tabs">
          <button data-tab="watch" class="tab active">Watch mode</button>
          <button data-tab="segments" class="tab">Segments</button>
          <button data-tab="vocab" class="tab">Vocabulary</button>
        </div>
        <div id="tab-watch" class="tab-panel"></div>
        <div id="tab-segments" class="tab-panel hidden"></div>
        <div id="tab-vocab" class="tab-panel hidden"></div>
      </main>
      <div id="hoverCard" class="hover-card hidden"></div>
    `;
    hoverCard = document.getElementById('hoverCard');
    bindGlobalUi();
    renderWatchTab();
  }

  function bindGlobalUi() {
    document.getElementById('openFullVideoBtn').addEventListener('click', () => { if (sourceValue) window.open(sourceValue, '_blank', 'noopener'); });
    document.getElementById('deleteArticleBtn').addEventListener('click', async () => {
      if (!confirm('Delete this article?')) return;
      await fetch(`/api/article/${articleId}/delete`, {method:'POST'});
      window.location.href = '/';
    });
    document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => setTab(btn.dataset.tab)));
    document.body.addEventListener('click', async (event) => {
      const rateBtn = event.target.closest('.rate-btn');
      const ignoreBtn = event.target.closest('.ignore-btn');
      if (rateBtn) await onRateClick({ currentTarget: rateBtn });
      if (ignoreBtn) await onIgnoreClick({ currentTarget: ignoreBtn });
    });
  }

  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
    document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.add('hidden'));
    document.getElementById(`tab-${tab}`).classList.remove('hidden');
    if (tab === 'segments') renderSegmentsTab();
    if (tab === 'vocab') renderVocabTab();
  }

  function setMessage(html, kind='notice') {
    const message = document.getElementById('message');
    message.innerHTML = html ? `<div class="${kind}">${html}</div>` : '';
  }

  async function loadArticle() {
    const res = await fetch(`/api/article/${articleId}`);
    if (!res.ok) throw new Error('Could not load article');
    article = await res.json();
    document.getElementById('title').textContent = article.title;
    document.getElementById('subtitle').textContent = `${article.source_type} · ${article.created_at}`;
    renderSegmentsTab();
    renderVocabTab();
    setupYouTubePlayer();
  }

  function renderWatchTab() {
    document.getElementById('tab-watch').innerHTML = `
      <div class="layout">
        <section>
          <div class="panel player-shell">
            <div class="player-top">
              <div class="toggle-row">
                <label class="toggle"><input type="checkbox" id="showTranslationToggle" checked> Show translation</label>
                <label class="toggle"><input type="checkbox" id="showFuriganaToggle" checked> Show furigana</label>
                <label class="toggle"><input type="checkbox" id="autoContextToggle" checked> Auto context gloss</label>
              </div>
              <button class="small" id="seekLineBtn">Open current line on YouTube</button>
            </div>
            <div class="player-wrap"><div id="player"></div></div>
            <div class="panel inner-panel">
              <div class="controls-bar">
                <div class="time-label" id="currentTimeLabel">00:00</div>
                <div class="progress-wrap"><input class="progress" id="progressBar" type="range" min="0" max="1000" value="0"></div>
                <div class="segment-title" id="segmentShortLabel">Waiting for video…</div>
              </div>
              <div class="notice small">Hover any highlighted word in the current line for a quick popup card. Technical multi-part terms should be preferred over raw sub-words.</div>
            </div>
          </div>
          <div class="panel stack-gap top-gap">
            <h2>Current line</h2>
            <div class="small muted" id="currentTimestamp">--:--</div>
            <div class="current-line-jp" id="currentLineJP"></div>
            <div class="current-line-tr" id="currentLineTR"></div>
          </div>
          <div class="panel top-gap">
            <h2>Nearby lines</h2>
            <div class="nearby-list" id="nearbyList"></div>
          </div>
        </section>
        <aside>
          <div class="panel">
            <h2>Context gloss settings</h2>
            <div class="settings-grid">
              <div><div class="small muted">Base URL</div><input id="baseUrlInput" type="text"></div>
              <div><div class="small muted">Model</div><input id="modelInput" type="text"></div>
              <div><div class="small muted">Target language</div><input id="targetLanguageInput" type="text"></div>
            </div>
            <div class="top-gap-small"><div class="small muted">API key</div><input id="apiKeyInput" type="password"></div>
          </div>
          <div class="panel top-gap">
            <div class="header-row"><h2>Words from this line</h2><button class="small" id="refreshContextBtn">Refresh context gloss</button></div>
            <div id="vocabStatus" class="small muted"></div>
            <div class="vocab-list" id="vocabList"></div>
          </div>
        </aside>
      </div>`;

    document.getElementById('showTranslationToggle').checked = state.showTranslation;
    document.getElementById('showFuriganaToggle').checked = state.showFurigana;
    document.getElementById('autoContextToggle').checked = state.autoContext;
    document.getElementById('baseUrlInput').value = state.baseUrl;
    document.getElementById('modelInput').value = state.model;
    document.getElementById('targetLanguageInput').value = state.targetLanguage;
    document.getElementById('apiKeyInput').value = state.apiKey;

    document.getElementById('showTranslationToggle').addEventListener('change', (e) => { state.showTranslation = e.target.checked; renderActiveSegment(); renderSegmentsTab(); });
    document.getElementById('showFuriganaToggle').addEventListener('change', (e) => { state.showFurigana = e.target.checked; renderActiveSegment(); renderSegmentsTab(); });
    document.getElementById('autoContextToggle').addEventListener('change', (e) => { state.autoContext = e.target.checked; if (currentSegmentId && state.autoContext) fetchContextGloss(); });
    document.getElementById('seekLineBtn').addEventListener('click', openCurrentLineOnYouTube);
    document.getElementById('refreshContextBtn').addEventListener('click', fetchContextGloss);
    ['baseUrlInput','modelInput','targetLanguageInput','apiKeyInput'].forEach((id) => {
      document.getElementById(id).addEventListener('change', persistSettings);
      document.getElementById(id).addEventListener('blur', persistSettings);
    });
    document.getElementById('progressBar').addEventListener('input', (e) => {
      if (!article || !article.segments.length) return;
      const ratio = Number(e.target.value) / 1000;
      const target = ratio * totalDuration();
      if (player && player.seekTo) {
        player.seekTo(target, true);
        updateFromPlayerTime(target);
      }
    });
  }

  function renderSegmentsTab() {
    const root = document.getElementById('tab-segments');
    if (!article) { root.innerHTML = ''; return; }
    root.innerHTML = `
      <div class="panel top-gap-small">
        <div class="toggle-row">
          <label class="toggle"><input type="checkbox" ${state.showTranslation ? 'checked' : ''} id="segmentsTranslationToggle"> Show translations</label>
          <label class="toggle"><input type="checkbox" ${state.showFurigana ? 'checked' : ''} id="segmentsFuriganaToggle"> Show furigana</label>
        </div>
      </div>
      <div class="stack-list top-gap">
        ${article.segments.map(seg => `
          <div class="panel segment-card2">
            <div class="small muted">${timeFmt(seg.start_sec || 0)}</div>
            <div class="segment-japanese">${renderSegmentUnits(seg)}</div>
            ${state.showTranslation && seg.translation_text ? `<div class="translation-text">${escapeHtml(seg.translation_text)}</div>` : ''}
          </div>`).join('')}
      </div>`;
    document.getElementById('segmentsTranslationToggle').addEventListener('change', e => { state.showTranslation = e.target.checked; renderSegmentsTab(); renderActiveSegment(); });
    document.getElementById('segmentsFuriganaToggle').addEventListener('change', e => { state.showFurigana = e.target.checked; renderSegmentsTab(); renderActiveSegment(); });
  }

  function groupVocab() {
    const items = Object.values(article.vocab_by_id || {});
    const filtered = items.filter(item => !(state.hideIgnored && Number(item.ignored_in_reviews || 0) === 1));
    const technical = filtered.filter(i => i.word_type === 'technical');
    const names = filtered.filter(i => i.word_type === 'name');
    const jlpt = lvl => filtered.filter(i => (i.jlpt_level_estimate || '').toUpperCase() === lvl);
    const uncategorized = filtered.filter(i => !i.jlpt_level_estimate && i.word_type !== 'technical' && i.word_type !== 'name');
    const recommended = filtered.filter(i => i.word_type === 'technical' || Number(i.topic_score || 0) >= 2 || Number(i.occurrence_count || 0) >= 2).slice(0, 80);
    return { all: filtered, recommended, technical, names, n5: jlpt('N5'), n4: jlpt('N4'), n3: jlpt('N3'), n2: jlpt('N2'), n1: jlpt('N1'), uncategorized };
  }

  function renderVocabTab() {
    const root = document.getElementById('tab-vocab');
    if (!article) { root.innerHTML = ''; return; }
    const groups = groupVocab();
    const current = groups[state.vocabFilter] || groups.recommended;
    const labels = [['recommended','Recommended'],['all','All'],['technical','Technical'],['names','Names'],['n5','N5'],['n4','N4'],['n3','N3'],['n2','N2'],['n1','N1'],['uncategorized','Uncategorized']];
    root.innerHTML = `
      <div class="panel top-gap-small">
        <div class="header-row"><h2>Vocabulary from this article</h2><label class="toggle"><input type="checkbox" id="hideIgnoredToggle" ${state.hideIgnored ? 'checked':''}> Hide ignored</label></div>
        <div class="chip-row">${labels.map(([key,label]) => `<button class="chip ${state.vocabFilter===key?'active':''}" data-filter="${key}">${label} (${(groups[key]||[]).length})</button>`).join('')}</div>
      </div>
      <div class="stack-list top-gap">${current.map(item => `<div class="panel">${vocabCardHtml(item, {})}</div>`).join('') || '<div class="panel muted">Nothing in this bucket yet.</div>'}</div>`;
    root.querySelectorAll('.chip').forEach(btn => btn.addEventListener('click', () => { state.vocabFilter = btn.dataset.filter; renderVocabTab(); }));
    document.getElementById('hideIgnoredToggle').addEventListener('change', e => { state.hideIgnored = e.target.checked; renderVocabTab(); });
  }

  function persistSettings() {
    state.baseUrl = document.getElementById('baseUrlInput').value.trim();
    state.model = document.getElementById('modelInput').value.trim();
    state.targetLanguage = document.getElementById('targetLanguageInput').value.trim() || 'English';
    state.apiKey = document.getElementById('apiKeyInput').value;
    localStorage.setItem('jp_watch_base_url', state.baseUrl);
    localStorage.setItem('jp_watch_model', state.model);
    localStorage.setItem('jp_watch_target_language', state.targetLanguage);
    localStorage.setItem('jp_watch_api_key', state.apiKey);
  }

  function setupYouTubePlayer() {
    if (!article.video_id) { setMessage('This article does not have a usable YouTube URL, so synced watch mode cannot attach to a player.', 'error'); return; }
    if (window.YT && window.YT.Player) createPlayer(); else window.onYouTubeIframeAPIReady = createPlayer;
  }
  function createPlayer() {
    if (player) return;
    player = new YT.Player('player', {
      videoId: article.video_id,
      playerVars: { rel: 0, playsinline: 1, start: 0, origin: window.location.origin },
      events: {
        onReady: () => { setMessage('Watch mode is live. Line switching should track the actual player time automatically.'); startSyncLoop(); updateFromPlayerTime(0); },
        onStateChange: () => { if (!syncTimer) startSyncLoop(); },
        onError: (event) => { setMessage(`YouTube player error: ${event.data}. Sometimes this is a browser/privacy/YouTube restriction issue.`, 'error'); },
      },
    });
  }
  function startSyncLoop() { if (syncTimer) clearInterval(syncTimer); syncTimer = setInterval(() => { if (!player || typeof player.getCurrentTime !== 'function') return; updateFromPlayerTime(player.getCurrentTime()); }, 250); }
  function totalDuration() { if (!article?.segments?.length) return 0; const last = article.segments[article.segments.length - 1]; return Math.max(1, Number(last.end_sec || last.start_sec || 1)); }
  function findActiveSegment(timeSec) { const segments = article.segments; if (!segments?.length) return null; for (let i = 0; i < segments.length; i++) { const seg = segments[i]; const start = Number(seg.start_sec || 0); const nextStart = i < segments.length - 1 ? Number(segments[i + 1].start_sec || start + 999) : Number(seg.end_sec || start + 999); if (timeSec >= start && timeSec < nextStart) return seg; } return segments[segments.length - 1]; }
  function updateFromPlayerTime(timeSec) {
    if (!article) return;
    const currentTimeLabel = document.getElementById('currentTimeLabel');
    const progressBar = document.getElementById('progressBar');
    if (currentTimeLabel) currentTimeLabel.textContent = timeFmt(timeSec);
    if (progressBar) progressBar.value = Math.min(1000, Math.max(0, Math.round((timeSec / totalDuration()) * 1000)));
    const seg = findActiveSegment(timeSec);
    if (!seg) return;
    if (currentSegmentId !== seg.id) {
      currentSegmentId = seg.id;
      renderActiveSegment();
      if (state.autoContext) fetchContextGloss();
    }
  }
  function activeSegment() { return article?.segments?.find((s) => s.id === currentSegmentId) || null; }
  function renderSegmentUnits(seg) { return (seg.inline_units || []).map((unit) => { const html = state.showFurigana ? unit.html : escapeHtml(unit.plain || unit.text || ''); if (unit.vocab_id) return `<span class="inline-vocab" data-vocab-id="${unit.vocab_id}">${html}</span>`; return `<span>${html}</span>`; }).join(''); }
  function renderActiveSegment() {
    const seg = activeSegment(); if (!seg) return;
    document.getElementById('currentTimestamp').textContent = timeFmt(seg.start_sec || 0);
    document.getElementById('currentLineJP').innerHTML = renderSegmentUnits(seg);
    document.getElementById('currentLineTR').textContent = state.showTranslation ? (seg.translation_text || '') : '';
    document.getElementById('segmentShortLabel').textContent = truncate(seg.japanese_text, 44);
    bindHoverTargets(); renderNearby(seg.id); renderVocab(seg.id);
  }
  function renderNearby(segmentId) {
    const idx = article.segments.findIndex((s) => s.id === segmentId);
    const slice = article.segments.slice(Math.max(0, idx - 3), Math.min(article.segments.length, idx + 4));
    const html = slice.map((seg) => `<div class="nearby-item ${seg.id === segmentId ? 'active' : ''}" data-segment-id="${seg.id}"><div class="small muted">${timeFmt(seg.start_sec || 0)}</div><div>${renderNearbyUnits(seg)}</div>${state.showTranslation && seg.translation_text ? `<div class="small top-gap-small" style="color:#d9e6f5;">${escapeHtml(seg.translation_text)}</div>` : ''}</div>`).join('');
    const container = document.getElementById('nearbyList'); container.innerHTML = html;
    container.querySelectorAll('.nearby-item').forEach((node) => node.addEventListener('click', () => seekToSegment(Number(node.dataset.segmentId))));
  }
  function renderNearbyUnits(seg) { return (seg.inline_units || []).map((unit) => state.showFurigana ? unit.html : escapeHtml(unit.plain || unit.text || '')).join(''); }
  function vocabForSegment(segmentId) { return (article.segment_vocab_map[String(segmentId)] || []).filter(Boolean); }
  function renderVocab(segmentId) {
    const items = vocabForSegment(segmentId); const cached = contextCache.get(segmentId) || {};
    const html = items.map((item) => vocabCardHtml(item, cached[item.id] || {})).join('');
    document.getElementById('vocabList').innerHTML = html || `<div class="muted">No vocabulary candidates were mapped to this line.</div>`;
  }
  function vocabCardHtml(item, context) {
    const gloss = context.context_translation || item.translation_text || '—';
    const note = context.context_note ? ` · ${escapeHtml(context.context_note)}` : '';
    const ignored = Number(item.ignored_in_reviews || 0) === 1;
    return `<div class="vocab-item"><div class="vocab-head"><div><div class="vocab-word">${escapeHtml(item.display_form || item.surface_form)}</div><div class="vocab-meta">${escapeHtml(item.reading_hiragana || '')} · ${escapeHtml(gloss)}${note}</div><div class="vocab-meta">${escapeHtml(item.word_type || 'common')} · ${escapeHtml(item.pos || '')}${item.jlpt_level_estimate ? ` · ${escapeHtml(item.jlpt_level_estimate)}` : ''}</div></div><div class="badge">${ignored ? 'ignored' : (item.rating || 'new')}</div></div>${ratingRowHtml(item, ignored)}</div>`;
  }
  function ratingRowHtml(item, ignored) { return `<div class="rating-row"><button class="small rate-btn" data-id="${item.id}" data-rating="dont_know">😵 don't know</button><button class="small rate-btn" data-id="${item.id}" data-rating="forgot">🤔 forgot</button><button class="small rate-btn" data-id="${item.id}" data-rating="somewhat">🙂 somewhat</button><button class="small rate-btn" data-id="${item.id}" data-rating="solid">😎 solid</button><button class="small ignore-btn" data-id="${item.id}" data-ignored="${ignored ? '0' : '1'}">${ignored ? 'Unignore' : 'Ignore in reviews'}</button></div>`; }
  async function onRateClick(event) { const id = Number(event.currentTarget.dataset.id); const rating = event.currentTarget.dataset.rating; await fetch(`/api/vocab/${id}/rate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rating }) }); updateLocalVocab(id, { rating, ignored_in_reviews: 0 }); }
  async function onIgnoreClick(event) { const id = Number(event.currentTarget.dataset.id); const ignored = event.currentTarget.dataset.ignored === '1'; await fetch(`/api/vocab/${id}/ignore`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ignored }) }); updateLocalVocab(id, { ignored_in_reviews: ignored ? 1 : 0 }); }
  function updateLocalVocab(id, patch) {
    Object.values(article.segment_vocab_map).forEach((bucket) => bucket.forEach((item) => { if (item.id === id) Object.assign(item, patch); }));
    Object.values(article.vocab_by_id).forEach((item) => { if (item.id === id) Object.assign(item, patch); });
    renderVocab(currentSegmentId); renderVocabTab();
    const shown = document.querySelector(`.inline-vocab[data-vocab-id="${id}"]`); if (shown) showHoverCard(id, shown);
  }
  function seekToSegment(segmentId) { const seg = article.segments.find((s) => s.id === segmentId); if (!seg || !player || !player.seekTo) return; player.seekTo(Number(seg.start_sec || 0), true); updateFromPlayerTime(Number(seg.start_sec || 0)); setTab('watch'); }
  function openCurrentLineOnYouTube() { const seg = activeSegment(); if (!seg) return; const url = `${sourceValue}${sourceValue.includes('?') ? '&' : '?'}t=${Math.floor(seg.start_sec || 0)}s`; window.open(url, '_blank', 'noopener'); }
  async function fetchContextGloss() {
    const seg = activeSegment(); if (!seg || autoContextInFlight) return;
    const items = vocabForSegment(seg.id); if (!items.length) return; persistSettings();
    if (!state.baseUrl || !state.model) { document.getElementById('vocabStatus').textContent = 'Context glosses are off because base URL or model is empty.'; return; }
    const cacheKey = seg.id; if (state.autoContext && contextCache.has(cacheKey)) { document.getElementById('vocabStatus').textContent = 'Using cached context glosses for this line.'; renderVocab(seg.id); return; }
    autoContextInFlight = true; document.getElementById('vocabStatus').textContent = 'Fetching context-aware glosses…';
    const idx = article.segments.findIndex((s) => s.id === seg.id); const previousLine = idx > 0 ? article.segments[idx - 1].japanese_text : ''; const nextLine = idx < article.segments.length - 1 ? article.segments[idx + 1].japanese_text : '';
    try {
      const res = await fetch('/api/context-gloss', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ article_id: article.id, segment_id: seg.id, vocab_item_ids: items.map((item) => item.id), current_line: seg.japanese_text, previous_line: previousLine, next_line: nextLine, article_title: article.title, target_language: state.targetLanguage, api_key: state.apiKey, base_url: state.baseUrl, model: state.model }) });
      const data = await res.json(); const mapped = {}; (data.items || []).forEach((item) => { mapped[item.id] = item; }); contextCache.set(cacheKey, mapped); document.getElementById('vocabStatus').textContent = 'Context glosses updated for this line.'; renderVocab(seg.id);
    } catch (err) { console.error(err); document.getElementById('vocabStatus').textContent = 'Context gloss request failed. Falling back to stored translations.'; }
    finally { autoContextInFlight = false; }
  }
  function bindHoverTargets() {
    const root = document.getElementById('currentLineJP');
    root.querySelectorAll('.inline-vocab').forEach((node) => {
      node.addEventListener('mouseenter', () => showHoverCard(Number(node.dataset.vocabId), node));
      node.addEventListener('mouseleave', () => scheduleHideHoverCard());
    });
  }
  let hideTimer = null;
  function scheduleHideHoverCard() { clearTimeout(hideTimer); hideTimer = setTimeout(() => hoverCard?.classList.add('hidden'), 120); }
  function showHoverCard(vocabId, anchorNode) {
    clearTimeout(hideTimer); const item = article.vocab_by_id[String(vocabId)] || article.vocab_by_id[vocabId]; if (!item || !hoverCard) return;
    const context = (contextCache.get(currentSegmentId) || {})[vocabId] || {}; const gloss = context.context_translation || item.translation_text || '—';
    const note = context.context_note ? `<div class="hover-note">${escapeHtml(context.context_note)}</div>` : ''; const ignored = Number(item.ignored_in_reviews || 0) === 1;
    hoverCard.innerHTML = `<div class="hover-title">${escapeHtml(item.display_form || item.surface_form)}</div><div class="hover-meta">${escapeHtml(item.reading_hiragana || '')}</div><div class="hover-meta">${escapeHtml(gloss)}</div><div class="hover-meta">${escapeHtml(item.word_type || 'common')} · ${escapeHtml(item.pos || '')}${item.jlpt_level_estimate ? ` · ${escapeHtml(item.jlpt_level_estimate)}` : ''}</div><div class="hover-meta">Base: ${escapeHtml(item.base_form || item.surface_form || '')}</div><div class="hover-meta">Seen: ${escapeHtml(String(item.occurrence_count || 0))}</div>${note}${ratingRowHtml(item, ignored)}`;
    const rect = anchorNode.getBoundingClientRect(); hoverCard.style.left = `${Math.min(window.innerWidth - 340, rect.left + window.scrollX)}px`; hoverCard.style.top = `${rect.bottom + window.scrollY + 8}px`; hoverCard.classList.remove('hidden'); hoverCard.onmouseenter = () => clearTimeout(hideTimer); hoverCard.onmouseleave = () => scheduleHideHoverCard();
  }

  renderShell();
  loadArticle().catch((err) => { console.error(err); setMessage(escapeHtml(err.message || String(err)), 'error'); });
}
