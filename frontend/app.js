/* Nebula Scanner - frontend mantigi */
(function () {
    const API = {
        markets: () => fetch('/api/markets').then((r) => r.json()),
        scan: (market, force = false) =>
            fetch(`/api/scan?market=${market}&force=${force ? 1 : 0}`).then((r) => r.json()),
        news: (market, force = false) =>
            fetch(`/api/news?market=${market}&force=${force ? 1 : 0}`).then((r) => r.json()),
        stock: (symbol) => fetch(`/api/stock/${encodeURIComponent(symbol)}`).then((r) => r.json()),
    };

    const WATCHLIST_KEY = 'nebula.watchlist.v1';

    const state = {
        market: 'us',
        currency: 'USD',
        tab: 'scan',
        minScore: 0,
        onlyWatched: false,
        search: '',
        sort: 'score',
        scanResults: [],
        lastGeneratedAt: 0,
        cacheRemaining: 0,
        watchlist: new Set(),
    };

    const els = {
        marketButtons: document.getElementById('marketButtons'),
        tabs: document.querySelectorAll('.tab'),
        tabPanels: document.querySelectorAll('.tab-panel'),
        refreshBtn: document.getElementById('refreshBtn'),
        lastUpdated: document.getElementById('lastUpdated'),
        cacheState: document.getElementById('cacheState'),
        statTotal: document.getElementById('statTotal'),
        statScored: document.getElementById('statScored'),
        statAvg: document.getElementById('statAvg'),
        statPerfect: document.getElementById('statPerfect'),
        resultsArea: document.getElementById('resultsArea'),
        skeletons: document.getElementById('skeletons'),
        searchInput: document.getElementById('searchInput'),
        scoreFilters: document.getElementById('scoreFilters'),
        sortSelect: document.getElementById('sortSelect'),
        newsArea: document.getElementById('newsArea'),
        modal: document.getElementById('stockModal'),
        modalClose: document.getElementById('modalClose'),
        modalContent: document.getElementById('modalContent'),
    };

    // --- helpers ---
    const fmtPrice = (p, ccy) => {
        if (p == null || isNaN(p)) return '-';
        const symbol = ccy === 'TRY' ? '₺' : ccy === 'USD' ? '$' : '';
        return `${symbol}${Number(p).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
    };

    const fmtChange = (c) => {
        if (c == null || isNaN(c)) return '0.00%';
        const v = Number(c);
        return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
    };

    const fmtVolume = (v) => {
        if (!v) return '-';
        if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
        if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
        if (v >= 1e3) return (v / 1e3).toFixed(2) + 'K';
        return String(v);
    };

    const tsToTime = (t) => {
        if (!t) return '-';
        const d = new Date(t * 1000);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    // --- watchlist (localStorage) ---
    function loadWatchlist() {
        try {
            const raw = localStorage.getItem(WATCHLIST_KEY);
            if (raw) state.watchlist = new Set(JSON.parse(raw));
        } catch (_) { state.watchlist = new Set(); }
    }

    function saveWatchlist() {
        try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...state.watchlist])); } catch (_) {}
    }

    function toggleWatch(symbol) {
        if (state.watchlist.has(symbol)) state.watchlist.delete(symbol);
        else state.watchlist.add(symbol);
        saveWatchlist();
    }

    // --- skeletons ---
    const renderSkeletons = (count = 8) => {
        els.skeletons.innerHTML = Array.from({ length: count })
            .map(() => '<div class="skeleton"></div>')
            .join('');
        els.skeletons.style.display = 'grid';
    };

    const hideSkeletons = () => (els.skeletons.style.display = 'none');

    // --- markets ---
    async function loadMarkets() {
        const res = await API.markets();
        els.marketButtons.innerHTML = '';
        res.markets.forEach((m) => {
            const btn = document.createElement('button');
            btn.className = 'market-btn' + (m.code === state.market ? ' active' : '');
            btn.dataset.market = m.code;
            btn.dataset.currency = m.currency;
            btn.innerHTML = `<span class="flag">${m.flag}</span>
                             <span>${m.label}</span>
                             <span style="opacity:.6;font-weight:500">&middot; ${m.ticker_count}</span>`;
            btn.addEventListener('click', () => {
                if (state.market === m.code) return;
                document.querySelectorAll('.market-btn').forEach((x) => x.classList.remove('active'));
                btn.classList.add('active');
                state.market = m.code;
                state.currency = m.currency;
                loadScan();
                if (state.tab === 'news') loadNews();
            });
            els.marketButtons.appendChild(btn);
            if (m.code === state.market) state.currency = m.currency;
        });
    }

    // --- scan ---
    async function loadScan(force = false) {
        renderSkeletons(8);
        els.resultsArea.querySelectorAll('.stock-card, .empty').forEach((x) => x.remove());
        try {
            const data = await API.scan(state.market, force);
            if (data.error) throw new Error(data.error);
            state.scanResults = data.results || [];
            state.lastGeneratedAt = data.generated_at || 0;
            state.cacheRemaining = data.cache_age_remaining || 0;
            updateSummary(data);
            updateMeta(data);
            renderResults();
        } catch (err) {
            console.error(err);
            hideSkeletons();
            const empty = document.createElement('div');
            empty.className = 'empty glass';
            empty.textContent = `Tarama yuklenemedi: ${err.message}`;
            els.resultsArea.appendChild(empty);
        }
    }

    function updateSummary(data) {
        els.statTotal.textContent = data.total ?? '-';
        els.statScored.textContent = data.scored ?? '-';
        const results = data.results || [];
        const avg = results.length ? (results.reduce((s, r) => s + r.score, 0) / results.length) : 0;
        els.statAvg.textContent = avg ? avg.toFixed(2) : '-';
        els.statPerfect.textContent = results.filter((r) => r.score >= 5).length;
    }

    function updateMeta(data) {
        els.lastUpdated.textContent = tsToTime(data.generated_at);
        renderCacheState();
    }

    function renderCacheState() {
        if (!state.lastGeneratedAt) {
            els.cacheState.textContent = '-';
            return;
        }
        const remaining = Math.max(0, state.cacheRemaining);
        if (remaining > 0) {
            const mins = Math.floor(remaining / 60);
            const secs = remaining % 60;
            els.cacheState.innerHTML = `canli &middot; ${mins}:${String(secs).padStart(2, '0')} sonra yenile`;
            els.cacheState.style.color = '#22d3ee';
        } else {
            els.cacheState.textContent = 'cache suresi doldu';
            els.cacheState.style.color = '#ffb86b';
        }
    }

    // tick every second to update countdown
    setInterval(() => {
        if (state.cacheRemaining > 0) {
            state.cacheRemaining -= 1;
            renderCacheState();
        }
    }, 1000);

    // --- sorting ---
    function sortResults(arr) {
        const s = state.sort;
        const copy = arr.slice();
        switch (s) {
            case 'change_desc':
                copy.sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0)); break;
            case 'change_asc':
                copy.sort((a, b) => (a.change_pct || 0) - (b.change_pct || 0)); break;
            case 'week':
                copy.sort((a, b) => (b.change_week_pct || 0) - (a.change_week_pct || 0)); break;
            case 'month':
                copy.sort((a, b) => (b.change_month_pct || 0) - (a.change_month_pct || 0)); break;
            case 'symbol':
                copy.sort((a, b) => a.symbol.localeCompare(b.symbol)); break;
            case 'score':
            default:
                copy.sort((a, b) => (b.score - a.score) || (b.change_pct - a.change_pct));
        }
        return copy;
    }

    // --- render results ---
    function renderResults() {
        hideSkeletons();
        let filtered = state.scanResults.filter((r) => {
            if (r.score < state.minScore) return false;
            if (state.onlyWatched && !state.watchlist.has(r.symbol)) return false;
            if (state.search) {
                return r.symbol.toLowerCase().includes(state.search.toLowerCase());
            }
            return true;
        });

        filtered = sortResults(filtered);

        els.resultsArea.querySelectorAll('.stock-card, .empty').forEach((x) => x.remove());

        if (!filtered.length) {
            const empty = document.createElement('div');
            empty.className = 'empty glass';
            empty.textContent = state.onlyWatched
                ? 'Favori listenizde bu pazardan hisse yok.'
                : 'Secili filtrelere uygun hisse bulunamadi.';
            els.resultsArea.appendChild(empty);
            return;
        }

        const frag = document.createDocumentFragment();
        filtered.forEach((r, idx) => {
            const card = buildStockCard(r, idx);
            frag.appendChild(card);
        });
        els.resultsArea.appendChild(frag);

        // draw sparklines after DOM insert
        filtered.forEach((r) => {
            const canvas = document.getElementById(`spark-${cssSafe(r.symbol)}`);
            if (canvas) drawSparkline(canvas, r.sparkline || [], r.change_pct >= 0);
        });
    }

    function cssSafe(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, '_'); }

    function buildStockCard(r, idx) {
        const card = document.createElement('div');
        card.className = 'stock-card glass';
        const change = Number(r.change_pct || 0);
        const changeClass = change >= 0 ? 'up' : 'down';
        const displaySymbol = r.symbol.replace('.IS', '');
        const isWatched = state.watchlist.has(r.symbol);

        const weekCls = (r.change_week_pct || 0) >= 0 ? 'up' : 'down';
        const monthCls = (r.change_month_pct || 0) >= 0 ? 'up' : 'down';

        card.innerHTML = `
            <button class="star-toggle ${isWatched ? 'active' : ''}" data-sym="${r.symbol}" title="Favorilere ekle">&#9733;</button>
            <div class="stock-rank">${idx + 1}</div>
            <div>
                <div class="stock-symbol">${displaySymbol}</div>
                <div class="stock-sub">${r.symbol} &middot; Hacim ${fmtVolume(r.volume || 0)}</div>
                <div class="week-month">
                    <span>7g <b class="${weekCls}">${fmtChange(r.change_week_pct)}</b></span>
                    <span>30g <b class="${monthCls}">${fmtChange(r.change_month_pct)}</b></span>
                </div>
            </div>
            <div class="spark-wrap"><canvas id="spark-${cssSafe(r.symbol)}"></canvas></div>
            <div class="price-block">
                <div class="price">${fmtPrice(r.price, state.currency)}</div>
                <div class="change ${changeClass}">${fmtChange(change)}</div>
            </div>
            <div class="indicators">
                ${r.indicators.map((ind) => `<span class="badge ${ind.signal ? 'on' : ''}" title="${escapeAttr(ind.detail || '')}">${ind.name}</span>`).join('')}
            </div>
            <div class="score-chip" data-score="${r.score}">
                <span class="star">&#9733;</span> ${r.score}/5
            </div>
        `;

        card.addEventListener('click', (e) => {
            if (e.target.closest('.star-toggle')) return;
            openStockModal(r.symbol);
        });

        const starBtn = card.querySelector('.star-toggle');
        starBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleWatch(r.symbol);
            starBtn.classList.toggle('active');
            if (state.onlyWatched) renderResults();
        });

        return card;
    }

    function escapeAttr(s) {
        return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    // --- sparkline ---
    function drawSparkline(canvas, data, isUp) {
        if (!canvas || !data || data.length < 2) return;
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const w = Math.max(1, rect.width);
        const h = Math.max(1, rect.height);
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, w, h);

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;
        const step = w / Math.max(1, data.length - 1);
        const pad = 3;

        const color = isUp ? '#34f5a8' : '#ff5370';
        const shadowCol = isUp ? 'rgba(52,245,168,.45)' : 'rgba(255,83,112,.45)';

        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, isUp ? 'rgba(52, 245, 168, 0.35)' : 'rgba(255, 83, 112, 0.3)');
        grad.addColorStop(1, isUp ? 'rgba(52, 245, 168, 0)' : 'rgba(255, 83, 112, 0)');

        ctx.beginPath();
        data.forEach((v, i) => {
            const x = i * step;
            const y = h - ((v - min) / range) * (h - pad * 2) - pad;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.lineWidth = 1.8;
        ctx.strokeStyle = color;
        ctx.shadowColor = shadowCol;
        ctx.shadowBlur = 6;
        ctx.stroke();
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.shadowBlur = 0;
        ctx.fillStyle = grad;
        ctx.fill();
    }

    // --- news ---
    async function loadNews(force = false) {
        els.newsArea.innerHTML = '<div class="empty glass">Haberler yukleniyor...</div>';
        try {
            const data = await API.news(state.market, force);
            if (!data.items || !data.items.length) {
                els.newsArea.innerHTML = '<div class="empty glass">Gosterilecek haber bulunamadi.</div>';
                return;
            }
            els.newsArea.innerHTML = '';
            data.items.forEach((n) => {
                const card = document.createElement('a');
                card.className = 'news-card glass';
                card.href = n.link;
                card.target = '_blank';
                card.rel = 'noopener noreferrer';
                card.innerHTML = `
                    <span class="news-source">${n.source || 'Kaynak'}</span>
                    <h3 class="news-title">${escapeHtml(n.title)}</h3>
                    ${n.summary ? `<p class="news-summary">${escapeHtml(n.summary)}</p>` : ''}
                    <span class="news-meta">${n.published || ''}</span>
                `;
                els.newsArea.appendChild(card);
            });
        } catch (err) {
            console.error(err);
            els.newsArea.innerHTML = `<div class="empty glass">Haberler yuklenemedi: ${err.message}</div>`;
        }
    }

    // --- modal ---
    async function openStockModal(symbol) {
        els.modal.classList.remove('hidden');
        els.modalContent.innerHTML = '<div class="empty">Yukleniyor...</div>';
        try {
            const data = await API.stock(symbol);
            if (data.error) throw new Error(data.error);
            els.modalContent.innerHTML = renderStockDetail(data);
            drawDetailChart(data.history || []);
            wireModalWatchToggle(data.symbol);
        } catch (err) {
            els.modalContent.innerHTML = `<div class="empty">Detay yuklenemedi: ${err.message}</div>`;
        }
    }

    function wireModalWatchToggle(symbol) {
        const btn = document.getElementById('modalStar');
        if (!btn) return;
        btn.addEventListener('click', () => {
            toggleWatch(symbol);
            btn.classList.toggle('active');
            // re-render underlying list if visible
            renderResults();
        });
    }

    function renderStockDetail(d) {
        const display = d.symbol.replace('.IS', '');
        const change = Number(d.change_pct || 0);
        const cls = change >= 0 ? 'up' : 'down';
        const weekCls = (d.change_week_pct || 0) >= 0 ? 'up' : 'down';
        const monthCls = (d.change_month_pct || 0) >= 0 ? 'up' : 'down';
        const isWatched = state.watchlist.has(d.symbol);

        return `
            <div style="display:flex; align-items:center; gap:14px;">
                <div>
                    <h2 style="margin:0;font-family:'Outfit';font-size:28px;">${display}</h2>
                    <div style="color: var(--text-3); font-size: 12px; letter-spacing: 1px; text-transform: uppercase;">${d.symbol}</div>
                </div>
                <button id="modalStar" class="star-toggle ${isWatched ? 'active' : ''}" style="position:static; font-size:22px;" title="Favorilere ekle">&#9733;</button>
                <div style="margin-left:auto">
                    <div class="score-chip" data-score="${d.score}"><span class="star">&#9733;</span> ${d.score}/5</div>
                </div>
            </div>
            <canvas id="detailChart" class="mini-chart" style="margin-top:18px;"></canvas>
            <div class="detail-row"><span class="k">Fiyat</span><span>${fmtPrice(d.price, state.currency)}</span></div>
            <div class="detail-row"><span class="k">Gunluk Degisim</span><span class="${cls}" style="color: ${change >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(change)}</span></div>
            <div class="detail-row"><span class="k">Haftalik Degisim</span><span style="color: ${(d.change_week_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(d.change_week_pct)}</span></div>
            <div class="detail-row"><span class="k">Aylik Degisim</span><span style="color: ${(d.change_month_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(d.change_month_pct)}</span></div>
            <div class="detail-row"><span class="k">52 Hafta Yuksek</span><span>${fmtPrice(d.high_52w, state.currency)}</span></div>
            <div class="detail-row"><span class="k">52 Hafta Dusuk</span><span>${fmtPrice(d.low_52w, state.currency)}</span></div>
            <div class="detail-row"><span class="k">20g Ort. Hacim</span><span>${fmtVolume(d.avg_volume_20d || 0)}</span></div>
            <div class="detail-row"><span class="k">Veri Noktasi</span><span>${d.data_points}</span></div>
            <div style="margin-top:18px;">
                ${d.indicators.map((ind) => `
                    <div class="detail-ind">
                        <div class="di-head">
                            <span class="di-name">${ind.name} ${ind.value != null ? `<span style="color:var(--text-3); font-weight:500">(${ind.value})</span>` : ''}</span>
                            <span class="badge ${ind.signal ? 'on' : ''}">${ind.signal ? 'AL' : '-'}</span>
                        </div>
                        <div class="di-reason">${ind.detail || ''}</div>
                    </div>`).join('')}
            </div>
        `;
    }

    function drawDetailChart(history) {
        const canvas = document.getElementById('detailChart');
        if (!canvas || !history.length) return;
        const closes = history.map((p) => p.close);
        const last = closes[closes.length - 1];
        const first = closes[0];
        drawSparkline(canvas, closes, last >= first);
    }

    function closeModal() { els.modal.classList.add('hidden'); }

    // --- events ---
    els.tabs.forEach((t) => {
        t.addEventListener('click', () => setTab(t.dataset.tab));
    });

    function setTab(name) {
        state.tab = name;
        els.tabs.forEach((x) => x.classList.toggle('active', x.dataset.tab === name));
        els.tabPanels.forEach((p) => p.classList.remove('active'));
        document.getElementById(`tab-${name}`).classList.add('active');
        if (name === 'news' && !els.newsArea.querySelector('.news-card')) loadNews();
    }

    els.refreshBtn.addEventListener('click', () => {
        if (state.tab === 'scan') loadScan(true);
        else loadNews(true);
    });

    els.searchInput.addEventListener('input', (e) => {
        state.search = e.target.value.trim();
        renderResults();
    });

    els.scoreFilters.querySelectorAll('.chip').forEach((c) => {
        c.addEventListener('click', () => {
            if (c.dataset.watch === '1') {
                state.onlyWatched = !state.onlyWatched;
                c.classList.toggle('active', state.onlyWatched);
            } else {
                els.scoreFilters.querySelectorAll('.chip:not(.chip-star)').forEach((x) => x.classList.remove('active'));
                c.classList.add('active');
                state.minScore = Number(c.dataset.min || 0);
            }
            renderResults();
        });
    });

    els.sortSelect.addEventListener('change', (e) => {
        state.sort = e.target.value;
        renderResults();
    });

    els.modalClose.addEventListener('click', closeModal);
    els.modal.querySelector('.modal-backdrop').addEventListener('click', closeModal);

    // keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        const isTyping = ['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target && e.target.tagName) || '');
        if (e.key === 'Escape') { closeModal(); return; }
        if (isTyping) return;
        if (e.key === '/') { e.preventDefault(); els.searchInput.focus(); return; }
        if (e.key === '1') { setTab('scan'); return; }
        if (e.key === '2') { setTab('news'); return; }
        if (e.key.toLowerCase() === 'r') { if (state.tab === 'scan') loadScan(true); else loadNews(true); }
    });

    window.addEventListener('resize', () => {
        if (state.tab === 'scan' && state.scanResults.length) renderResults();
    });

    // bootstrap
    loadWatchlist();
    loadMarkets().then(() => loadScan());
})();
