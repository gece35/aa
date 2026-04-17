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

    const state = {
        market: 'us',
        currency: 'USD',
        tab: 'scan',
        minScore: 0,
        search: '',
        scanResults: [],
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
        newsArea: document.getElementById('newsArea'),
        modal: document.getElementById('stockModal'),
        modalClose: document.getElementById('modalClose'),
        modalContent: document.getElementById('modalContent'),
    };

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

    const tsToTime = (t) => {
        if (!t) return '-';
        const d = new Date(t * 1000);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    const renderSkeletons = (count = 8) => {
        els.skeletons.innerHTML = Array.from({ length: count })
            .map(() => '<div class="skeleton"></div>')
            .join('');
        els.skeletons.style.display = 'grid';
    };

    const hideSkeletons = () => (els.skeletons.style.display = 'none');

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

    async function loadScan(force = false) {
        renderSkeletons(8);
        els.resultsArea.querySelectorAll('.stock-card').forEach((x) => x.remove());
        const notFound = els.resultsArea.querySelector('.empty');
        if (notFound) notFound.remove();
        try {
            const data = await API.scan(state.market, force);
            if (data.error) throw new Error(data.error);
            state.scanResults = data.results || [];
            updateSummary(data);
            updateMeta(data);
            renderResults();
        } catch (err) {
            console.error(err);
            hideSkeletons();
            els.resultsArea.innerHTML += `<div class="empty glass">Tarama yuklenemedi: ${err.message}</div>`;
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
        if (data.cached) {
            const mins = Math.floor((data.cache_age_remaining || 0) / 60);
            const secs = (data.cache_age_remaining || 0) % 60;
            els.cacheState.innerHTML = `cache (${mins}:${String(secs).padStart(2, '0')} kaldi)`;
            els.cacheState.style.color = '#34f5a8';
        } else {
            els.cacheState.textContent = 'canli';
            els.cacheState.style.color = '#22d3ee';
        }
    }

    function renderResults() {
        hideSkeletons();
        const filtered = state.scanResults.filter((r) => {
            if (r.score < state.minScore) return false;
            if (state.search) {
                return r.symbol.toLowerCase().includes(state.search.toLowerCase());
            }
            return true;
        });

        els.resultsArea.querySelectorAll('.stock-card, .empty').forEach((x) => x.remove());

        if (!filtered.length) {
            const empty = document.createElement('div');
            empty.className = 'empty glass';
            empty.textContent = 'Secili filtrelere uygun hisse bulunamadi.';
            els.resultsArea.appendChild(empty);
            return;
        }

        filtered.forEach((r, idx) => {
            const card = document.createElement('div');
            card.className = 'stock-card glass';
            card.addEventListener('click', () => openStockModal(r.symbol));
            const change = Number(r.change_pct || 0);
            const changeClass = change >= 0 ? 'up' : 'down';
            const displaySymbol = r.symbol.replace('.IS', '');
            card.innerHTML = `
                <div class="stock-rank">${idx + 1}</div>
                <div>
                    <div class="stock-symbol">${displaySymbol}</div>
                    <div class="stock-sub">${r.symbol}</div>
                </div>
                <div class="price-block">
                    <div class="price">${fmtPrice(r.price, state.currency)}</div>
                    <div class="change ${changeClass}">${fmtChange(change)}</div>
                </div>
                <div class="indicators">
                    ${r.indicators
                        .map(
                            (ind) => `<span class="badge ${ind.signal ? 'on' : ''}" title="${escapeAttr(ind.detail || '')}">${ind.name}</span>`,
                        )
                        .join('')}
                </div>
                <div class="score-chip" data-score="${r.score}">
                    <span class="star">&#9733;</span> ${r.score}/5
                </div>
            `;
            els.resultsArea.appendChild(card);
        });
    }

    function escapeAttr(s) {
        return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }

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

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    async function openStockModal(symbol) {
        els.modal.classList.remove('hidden');
        els.modalContent.innerHTML = '<div class="empty">Yukleniyor...</div>';
        try {
            const data = await API.stock(symbol);
            if (data.error) throw new Error(data.error);
            els.modalContent.innerHTML = renderStockDetail(data);
            drawSparkline(data.history || []);
        } catch (err) {
            els.modalContent.innerHTML = `<div class="empty">Detay yuklenemedi: ${err.message}</div>`;
        }
    }

    function renderStockDetail(d) {
        const display = d.symbol.replace('.IS', '');
        const change = Number(d.change_pct || 0);
        const cls = change >= 0 ? 'up' : 'down';
        return `
            <h2 style="margin:0 0 4px;font-family:'Outfit';font-size:28px;">${display}</h2>
            <div style="color: var(--text-3); font-size: 12px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 16px;">${d.symbol}</div>
            <div class="score-chip" data-score="${d.score}" style="margin-bottom: 14px;"><span class="star">&#9733;</span> ${d.score}/5</div>
            <div class="detail-row"><span class="k">Fiyat</span><span>${fmtPrice(d.price, state.currency)}</span></div>
            <div class="detail-row"><span class="k">Gunluk Degisim</span><span class="${cls}" style="color: ${change >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(change)}</span></div>
            <div class="detail-row"><span class="k">20g Ort. Hacim</span><span>${(d.avg_volume_20d || 0).toLocaleString()}</span></div>
            <div class="detail-row"><span class="k">Veri Noktasi</span><span>${d.data_points}</span></div>
            <canvas id="detailChart" class="mini-chart"></canvas>
            <div style="margin-top:18px;">
                ${d.indicators
                    .map(
                        (ind) => `
                        <div class="detail-ind">
                            <div class="di-head">
                                <span class="di-name">${ind.name} ${ind.value != null ? `<span style="color:var(--text-3); font-weight:500">(${ind.value})</span>` : ''}</span>
                                <span class="badge ${ind.signal ? 'on' : ''}">${ind.signal ? 'AL' : '-'}</span>
                            </div>
                            <div class="di-reason">${ind.detail || ''}</div>
                        </div>`,
                    )
                    .join('')}
            </div>
        `;
    }

    function drawSparkline(history) {
        const canvas = document.getElementById('detailChart');
        if (!canvas || !history.length) return;
        const ctx = canvas.getContext('2d');
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * devicePixelRatio;
        canvas.height = rect.height * devicePixelRatio;
        ctx.scale(devicePixelRatio, devicePixelRatio);
        const w = rect.width;
        const h = rect.height;
        const closes = history.map((p) => p.close);
        const min = Math.min(...closes);
        const max = Math.max(...closes);
        const range = max - min || 1;
        const step = w / Math.max(1, closes.length - 1);
        ctx.clearRect(0, 0, w, h);
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, 'rgba(52, 245, 168, 0.45)');
        grad.addColorStop(1, 'rgba(52, 245, 168, 0)');
        ctx.beginPath();
        closes.forEach((v, i) => {
            const x = i * step;
            const y = h - ((v - min) / range) * (h - 12) - 6;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#34f5a8';
        ctx.shadowColor = 'rgba(52, 245, 168, 0.45)';
        ctx.shadowBlur = 10;
        ctx.stroke();
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.shadowBlur = 0;
        ctx.fillStyle = grad;
        ctx.fill();
    }

    function closeModal() { els.modal.classList.add('hidden'); }

    /* event wiring */
    els.tabs.forEach((t) => {
        t.addEventListener('click', () => {
            els.tabs.forEach((x) => x.classList.remove('active'));
            t.classList.add('active');
            state.tab = t.dataset.tab;
            els.tabPanels.forEach((p) => p.classList.remove('active'));
            document.getElementById(`tab-${state.tab}`).classList.add('active');
            if (state.tab === 'news' && !els.newsArea.querySelector('.news-card')) loadNews();
        });
    });

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
            els.scoreFilters.querySelectorAll('.chip').forEach((x) => x.classList.remove('active'));
            c.classList.add('active');
            state.minScore = Number(c.dataset.min || 0);
            renderResults();
        });
    });

    els.modalClose.addEventListener('click', closeModal);
    els.modal.querySelector('.modal-backdrop').addEventListener('click', closeModal);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

    /* bootstrap */
    loadMarkets().then(() => loadScan());
})();
