/* Nebula Scanner - frontend mantigi */
(function () {
    const API = {
        markets: () => fetch('/api/markets').then((r) => r.json()),
        scanChunk: (market, offset, limit, force = false, sort = 'score') =>
            fetch(`/api/scan?market=${market}&offset=${offset}&limit=${limit}&force=${force ? 1 : 0}&sort=${sort}`).then((r) => r.json()),
        stock: (symbol) => fetch(`/api/stock/${encodeURIComponent(symbol)}`).then((r) => r.json()),
        stockNews: (symbol) => fetch(`/api/news/stock/${encodeURIComponent(symbol)}`).then((r) => r.json()),
        exchangeRate: () => fetch('/api/exchange-rate').then((r) => r.json()),
        alertsList: () => fetch('/api/alerts').then((r) => r.json()),
        alertsCreate: (body) => fetch('/api/alerts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json()),
        alertsDelete: (id) => fetch(`/api/alerts/${id}`, { method: 'DELETE' }).then((r) => r.json()),
        alertsDismiss: (id) => fetch(`/api/alerts/${id}/dismiss`, { method: 'POST' }).then((r) => r.json()),
        alertsTriggered: () => fetch('/api/alerts/triggered').then((r) => r.json()),
        alertsConditions: () => fetch('/api/alerts/conditions').then((r) => r.json()),
        watchlistGet: () => fetch('/api/watchlist').then((r) => r.json()),
        watchlistAdd: (symbol) => fetch('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) }).then((r) => r.json()),
        watchlistRemove: (symbol) => fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' }).then((r) => r.json()),
        portfolioGet: () => fetch('/api/portfolio').then((r) => r.json()),
        portfolioAdd: (body) => fetch('/api/portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json()),
        portfolioRemove: (id) => fetch(`/api/portfolio/${id}`, { method: 'DELETE' }).then((r) => r.json()),
    };

    const WATCHLIST_KEY = 'nebula.watchlist.v1';
    const BATCH_SIZE = 30;
    const IDLE_PREFETCH_MS = 1500;

    function newMarketState() {
        return {
            results: [],
            bySymbol: new Map(),
            offset: 0,
            total: 0,
            hasMore: true,
            loading: false,
            generatedAt: 0,
            cacheRemaining: 0,
            loadedOnce: false,
        };
    }

    const state = {
        market: 'bist',
        currency: 'TRY',
        minScore: 0,
        onlyWatched: false,
        search: '',
        sort: 'score',
        watchlist: new Set(),
        byMarket: { us: newMarketState(), bist: newMarketState() },
        scrollObserver: null,
        prefetchTimer: null,
        usdRate: null,
        showUsd: false,
    };

    function ms() { return state.byMarket[state.market]; }

    const els = {
        marketButtons: document.getElementById('marketButtons'),
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
        currencyToggleWrap: document.getElementById('currencyToggleWrap'),
        modal: document.getElementById('stockModal'),
        modalClose: document.getElementById('modalClose'),
        modalContent: document.getElementById('modalContent'),
    };

    // --- helpers ---
    const fmtPrice = (p, ccy) => {
        if (p == null || isNaN(p)) return '-';
        let val = Number(p);
        let displayCcy = ccy;
        if (ccy === 'TRY' && state.showUsd && state.usdRate) {
            val = val / state.usdRate;
            displayCcy = 'USD';
        }
        const sym = displayCcy === 'TRY' ? '₺' : displayCcy === 'USD' ? '$' : '';
        return `${sym}${val.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
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

    // --- watchlist ---
    async function loadWatchlist() {
        if (_currentUser) {
            try {
                const d = await API.watchlistGet();
                state.watchlist = new Set(d.watchlist || []);
            } catch (_) { state.watchlist = new Set(); }
        } else {
            try {
                const raw = localStorage.getItem(WATCHLIST_KEY);
                if (raw) state.watchlist = new Set(JSON.parse(raw));
            } catch (_) { state.watchlist = new Set(); }
        }
    }

    function saveWatchlist() {
        if (_currentUser) return;
        try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...state.watchlist])); } catch (_) {}
    }

    function toggleWatch(symbol) {
        if (_currentUser) {
            if (state.watchlist.has(symbol)) {
                state.watchlist.delete(symbol);
                API.watchlistRemove(symbol).catch(() => state.watchlist.add(symbol));
            } else {
                state.watchlist.add(symbol);
                API.watchlistAdd(symbol).catch(() => state.watchlist.delete(symbol));
            }
        } else {
            if (state.watchlist.has(symbol)) state.watchlist.delete(symbol);
            else state.watchlist.add(symbol);
            saveWatchlist();
        }
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
                // Misafir ABD'ye geçemez
                if (m.code === 'us' && !_currentUser) {
                    showMarketGate();
                    return;
                }
                document.querySelectorAll('.market-btn').forEach((x) => x.classList.remove('active'));
                btn.classList.add('active');
                state.market = m.code;
                state.currency = m.currency;
                state.showUsd = false;
                updateCurrencyToggle();
                if (m.code === 'bist') fetchExchangeRate();
                loadScan();
            });
            els.marketButtons.appendChild(btn);
            if (m.code === state.market) state.currency = m.currency;
        });
    }

    // --- scan (lazy / chunked) ---
    async function loadScan(force = false) {
        const m = ms();
        if (force) {
            state.byMarket[state.market] = newMarketState();
        }

        if (!force && m.loadedOnce) {
            updateSummary();
            updateMeta();
            renderResults();
            schedulePrefetch();
            return;
        }

        renderSkeletons(8);
        els.resultsArea.querySelectorAll('.stock-card, .empty, .loader-sentinel, .plan-gate-banner').forEach((x) => x.remove());

        try {
            await loadNextChunk(force);
        } catch (err) {
            console.error(err);
            hideSkeletons();
            const empty = document.createElement('div');
            empty.className = 'empty glass';
            empty.textContent = `Tarama yuklenemedi: ${err.message}`;
            els.resultsArea.appendChild(empty);
            return;
        }
        updateSummary();
        updateMeta();
        renderResults();
        schedulePrefetch();
    }

    async function loadNextChunk(force = false) {
        const market = state.market;
        const m = state.byMarket[market];
        if (m.loading || !m.hasMore) return false;
        m.loading = true;
        try {
            const data = await API.scanChunk(market, m.offset, BATCH_SIZE, force, state.sort);
            if (data.error) throw new Error(data.error);

            const incoming = data.results || [];
            for (const r of incoming) {
                if (!m.bySymbol.has(r.symbol)) {
                    m.bySymbol.set(r.symbol, r);
                    m.results.push(r);
                }
            }
            m.total = data.total || m.total;
            m.offset = data.next_offset != null ? data.next_offset : (m.offset + (data.limit || BATCH_SIZE));
            m.hasMore = Boolean(data.has_more);
            m.generatedAt = data.generated_at || m.generatedAt || Math.floor(Date.now() / 1000);
            m.cacheRemaining = 600;
            m.loadedOnce = true;
            return true;
        } finally {
            m.loading = false;
        }
    }

    function schedulePrefetch() {
        if (state.prefetchTimer) clearTimeout(state.prefetchTimer);
        const m = ms();
        if (!m.hasMore) return;
        state.prefetchTimer = setTimeout(async function tick() {
            const mm = ms();
            if (!mm.hasMore || mm.loading) return;
            const ok = await loadNextChunk(false).catch(() => false);
            if (ok) {
                updateSummary();
                updateMeta();
                renderResults();
            }
            if (ms().hasMore) {
                state.prefetchTimer = setTimeout(tick, IDLE_PREFETCH_MS);
            }
        }, IDLE_PREFETCH_MS);
    }

    function updateSummary() {
        const m = ms();
        els.statTotal.textContent = m.total || '-';
        els.statScored.textContent = m.results.length || '-';
        const avg = m.results.length ? (m.results.reduce((s, r) => s + r.score, 0) / m.results.length) : 0;
        els.statAvg.textContent = avg ? avg.toFixed(2) : '-';
        els.statPerfect.textContent = m.results.filter((r) => r.score >= 5).length;
    }

    function updateMeta() {
        const m = ms();
        els.lastUpdated.textContent = tsToTime(m.generatedAt);
        renderCacheState();
    }

    function renderCacheState() {
        const m = ms();
        if (!m.generatedAt) {
            els.cacheState.textContent = '-';
            return;
        }
        const remaining = Math.max(0, m.cacheRemaining);
        const loadedInfo = m.total ? ` &middot; ${m.results.length}/${m.total} yuklendi` : '';
        if (remaining > 0) {
            const mins = Math.floor(remaining / 60);
            const secs = remaining % 60;
            els.cacheState.innerHTML = `canli &middot; ${mins}:${String(secs).padStart(2, '0')} sonra yenile${loadedInfo}`;
            els.cacheState.style.color = '#22d3ee';
        } else {
            els.cacheState.innerHTML = `cache suresi doldu${loadedInfo}`;
            els.cacheState.style.color = '#ffb86b';
        }
    }

    setInterval(() => {
        const m = ms();
        if (m.cacheRemaining > 0) {
            m.cacheRemaining -= 1;
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

    function renderResults() {
        hideSkeletons();
        const m = ms();
        let filtered = m.results.filter((r) => {
            if (r.score < state.minScore) return false;
            if (state.onlyWatched && !state.watchlist.has(r.symbol)) return false;
            if (state.search) {
                return r.symbol.toLowerCase().includes(state.search.toLowerCase());
            }
            return true;
        });

        filtered = sortResults(filtered);

        els.resultsArea.querySelectorAll('.stock-card, .empty, .loader-sentinel, .plan-gate-banner').forEach((x) => x.remove());

        if (!filtered.length && !m.loading) {
            const empty = document.createElement('div');
            empty.className = 'empty glass';
            empty.textContent = state.onlyWatched
                ? 'Favori listenizde bu pazardan hisse yok.'
                : m.hasMore
                    ? 'Daha fazla hisse yukleniyor...'
                    : 'Secili filtrelere uygun hisse bulunamadi.';
            els.resultsArea.appendChild(empty);
        } else {
            const frag = document.createDocumentFragment();
            filtered.forEach((r, idx) => {
                const card = buildStockCard(r, idx);
                frag.appendChild(card);
            });
            els.resultsArea.appendChild(frag);

            filtered.forEach((r) => {
                const canvas = document.getElementById(`spark-${cssSafe(r.symbol)}`);
                if (canvas) drawSparkline(canvas, r.sparkline || [], r.change_pct >= 0);
            });
        }

        if (m.hasMore) {
            const sentinel = document.createElement('div');
            sentinel.className = 'loader-sentinel';
            sentinel.innerHTML = `<div class="loader-dot"></div><div class="loader-dot"></div><div class="loader-dot"></div>
                <span class="loader-text">${m.loading ? 'Yukleniyor...' : `Daha fazlasi... (${m.results.length}/${m.total})`}</span>`;
            els.resultsArea.appendChild(sentinel);
            observeSentinel(sentinel);
        } else if (m.loadedOnce) {
            // Sadece misafir kullanıcılara kayıt motivasyonu göster
            if (!_currentUser) {
                const banner = document.createElement('div');
                banner.className = 'plan-gate-banner';
                banner.innerHTML = `
                    <div class="plan-gate-icon">🔒</div>
                    <div class="plan-gate-text">
                        <strong>BIST'te ${m.results.length} hisse tarandı</strong>
                        <span>Tüm hisselere, ABD borsasına ve detay analizine ulaşmak için <a href="#" onclick="openAuthModal('signup');return false;">ücretsiz kayıt olun →</a></span>
                    </div>`;
                els.resultsArea.appendChild(banner);
            }
        }
    }

    function observeSentinel(el) {
        if (state.scrollObserver) state.scrollObserver.disconnect();
        state.scrollObserver = new IntersectionObserver(async (entries) => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue;
                const m = ms();
                if (m.loading || !m.hasMore) return;
                const ok = await loadNextChunk(false).catch(() => false);
                if (ok) {
                    updateSummary();
                    updateMeta();
                    renderResults();
                }
            }
        }, { rootMargin: '400px 0px' });
        state.scrollObserver.observe(el);
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

        const spikeBadge = r.volume_spike
            ? `<span class="badge volume-spike" title="Son 10 gun ortalamasinin 1.5x uzeri hacim">&#128640; Hacim Patlamasi</span>`
            : '';
        const nearPeakBadge = r.near_peak
            ? `<span class="badge near-peak" title="52 haftalik zirveye %5 icinde">&#9650; Tepe</span>`
            : '';
        const reason = buildScoreReason(r);

        const chartBtnHtml = r.score >= 4
            ? `<button class="scan-chart-btn btn btn-sm" data-sym="${r.symbol}" title="Candlestick grafik ve formasyon analizi">&#128202; Grafik</button>`
            : '';

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
                ${spikeBadge}${nearPeakBadge}
            </div>
            <div class="score-chip" data-score="${r.score}">
                <span class="star">&#9733;</span> ${r.score}/5
            </div>
            ${reason ? `<div class="score-reason">${escapeHtml(reason)}</div>` : ''}
            ${chartBtnHtml}
        `;

        card.addEventListener('click', (e) => {
            if (e.target.closest('.star-toggle') || e.target.closest('.scan-chart-btn')) return;
            openStockModal(r.symbol);
        });

        const starBtn = card.querySelector('.star-toggle');
        starBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleWatch(r.symbol);
            starBtn.classList.toggle('active');
            if (state.onlyWatched) renderResults();
        });

        const scanChartBtn = card.querySelector('.scan-chart-btn');
        if (scanChartBtn) scanChartBtn.addEventListener('click', (e) => { e.stopPropagation(); openScanChart(r); });

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

    function buildScoreReason(r) {
        if (!r || !r.indicators) return '';
        const parts = [];
        const byKey = {};
        r.indicators.forEach((ind) => { byKey[ind.key] = ind; });

        const rsi = byKey['rsi'];
        const macd = byKey['macd'];
        const bbands = byKey['bbands'];
        const ema = byKey['ema50'];
        const stoch = byKey['stoch'];

        if (rsi && rsi.signal) {
            const v = rsi.value != null ? ` (${rsi.value})` : '';
            if (rsi.detail && rsi.detail.includes('30')) parts.push(`RSI${v} asiri satim bolgesinden cikis`);
            else parts.push(`RSI${v} yukselis sinyali verdi`);
        }
        if (macd && macd.signal) parts.push('MACD alim sinyali verdi');
        if (bbands && bbands.signal) parts.push('Bollinger alt bandından donus');
        if (ema && ema.signal) parts.push('fiyat EMA50 uzerinde');
        if (stoch && stoch.signal) parts.push('Stokastik al sinyali olustu');
        if (r.volume_spike) parts.push('hacim patlamasi var');
        if (r.near_peak) parts.push('dikkat: zirveye yakin');

        if (!parts.length) return r.score === 0 ? 'Aktif teknik sinyal bulunmuyor.' : '';
        const sentence = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
        const rest = parts.slice(1);
        if (!rest.length) return sentence + '.';
        return sentence + ', ' + rest.join(', ') + '.';
    }

    // --- USD/TRY kur toggle ---
    async function fetchExchangeRate() {
        try {
            const data = await API.exchangeRate();
            if (data.rate) state.usdRate = data.rate;
        } catch (_) {}
        updateCurrencyToggle();
    }

    function updateCurrencyToggle() {
        if (!els.currencyToggleWrap) return;
        if (state.market !== 'bist' || !state.usdRate) {
            els.currencyToggleWrap.innerHTML = '';
            return;
        }
        if (els.currencyToggleWrap.querySelector('.currency-toggle')) {
            els.currencyToggleWrap.querySelector('.currency-toggle').classList.toggle('active', state.showUsd);
            return;
        }
        const btn = document.createElement('button');
        btn.className = 'currency-toggle' + (state.showUsd ? ' active' : '');
        btn.title = 'TRY fiyatlarını USD cinsinden goster';
        btn.innerHTML = `<span>&#8378; &rarr; $</span>`;
        btn.addEventListener('click', () => {
            state.showUsd = !state.showUsd;
            btn.classList.toggle('active', state.showUsd);
            renderResults();
        });
        els.currencyToggleWrap.appendChild(btn);
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

    // --- modal ---
    async function openStockModal(symbol) {
        els.modal.classList.remove('hidden');
        els.modalContent.innerHTML = '<div class="empty">Yukleniyor...</div>';
        try {
            // Misafir hisse detayına tıklayınca login modal açılır
            if (!_currentUser) {
                els.modal.classList.add('hidden');
                openAuthModal('signup');
                return;
            }
            const [data, newsData] = await Promise.all([
                API.stock(symbol),
                API.stockNews(symbol).catch(() => ({ items: [] })),
            ]);
            if (data.error === 'auth_required') {
                els.modal.classList.add('hidden');
                openAuthModal('signup');
                return;
            }
            if (data.error) throw new Error(data.error);
            els.modalContent.innerHTML = renderStockDetail(data, newsData);
            drawDetailChart(data.history || [], data.supports || [], data.resistances || [], data.stop_loss, data.take_profit);
            wireModalWatchToggle(data.symbol);
            wireModalPortfolioForm(data);
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
            renderResults();
        });
    }

    function renderStockDetail(d, newsData) {
        const display = d.symbol.replace('.IS', '');
        const change = Number(d.change_pct || 0);
        const isWatched = state.watchlist.has(d.symbol);
        const spikeHtml = d.volume_spike
            ? `<span class="badge volume-spike" style="margin-left:8px;">&#128640; Hacim Patlamasi</span>`
            : '';
        const nearPeakHtml = d.near_peak
            ? `<span class="badge near-peak" style="margin-left:8px;" title="Fiyat 52 haftalik zirveye %5 icinde">&#9650; Tepeye Yakin</span>`
            : '';
        const reason = buildScoreReason(d);

        const price = d.price;
        const ccy = state.currency;

        // --- Support / Resistance ---
        const sups = (d.supports || []).filter(s => s < price * 1.05).slice(-4).reverse();
        const ress = (d.resistances || []).filter(r => r > price * 0.95).slice(0, 4);

        const srHtml = (sups.length || ress.length) ? `
            <div style="margin-top:20px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:10px;">Destek / Direnc Seviyeleri</div>
                <div style="display:flex;gap:12px;flex-wrap:wrap;">
                    <div style="flex:1;min-width:120px;">
                        <div style="font-size:10px;color:var(--neon);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;font-weight:700;">&#9650; Destek</div>
                        ${sups.length ? sups.map(s => {
                            const pct = ((s / price - 1) * 100).toFixed(1);
                            return `<div class="sr-level sup">${fmtPrice(s, ccy)} <span class="sr-pct">${pct}%</span></div>`;
                        }).join('') : '<div style="color:var(--text-3);font-size:12px;">Bulunamadi</div>'}
                    </div>
                    <div style="flex:1;min-width:120px;">
                        <div style="font-size:10px;color:var(--danger);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;font-weight:700;">&#9650; Direnc</div>
                        ${ress.length ? ress.map(r => {
                            const pct = ((r / price - 1) * 100).toFixed(1);
                            return `<div class="sr-level res">${fmtPrice(r, ccy)} <span class="sr-pct">+${pct}%</span></div>`;
                        }).join('') : '<div style="color:var(--text-3);font-size:12px;">Bulunamadi</div>'}
                    </div>
                </div>
            </div>` : '';

        // --- Stop Loss / Take Profit ---
        const sl = d.stop_loss;
        const tp = d.take_profit;
        const rr = d.risk_reward;
        const slPct = sl ? ((sl / price - 1) * 100).toFixed(2) : null;
        const tpPct = tp ? ((tp / price - 1) * 100).toFixed(2) : null;

        const slTpHtml = (sl || tp) ? `
            <div style="margin-top:14px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:10px;">Stop Loss / Kar Al</div>
                <div class="sl-tp-box">
                    ${sl ? `<div class="sl-tp-item stop-loss">
                        <span class="sl-tp-label">Stop Loss</span>
                        <span class="sl-tp-value">${fmtPrice(sl, ccy)}</span>
                        <span class="sl-tp-pct">${slPct}%</span>
                    </div>` : ''}
                    ${tp ? `<div class="sl-tp-item take-profit">
                        <span class="sl-tp-label">Kar Al</span>
                        <span class="sl-tp-value">${fmtPrice(tp, ccy)}</span>
                        <span class="sl-tp-pct">+${tpPct}%</span>
                    </div>` : ''}
                    ${rr ? `<div class="sl-tp-item rr">
                        <span class="sl-tp-label">Risk / Odul</span>
                        <span class="sl-tp-value">1 : ${rr}</span>
                    </div>` : ''}
                </div>
            </div>` : '';

        // --- News ---
        const newsItems = (newsData && newsData.items && newsData.items.length)
            ? newsData.items.map((n) => {
                const sentCls = n.sentiment === 'positive' ? 'sent-positive'
                    : n.sentiment === 'negative' ? 'sent-negative' : 'sent-neutral';
                const dateStr = n.published
                    ? new Date(n.published * 1000).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric' })
                    : '';
                return `<a class="stock-news-item ${sentCls}" href="${escapeAttr(n.link)}" target="_blank" rel="noopener noreferrer">
                    <span class="sn-source">${escapeHtml(n.publisher || 'Kaynak')}</span>
                    <span class="sn-title">${escapeHtml(n.title)}</span>
                    <span class="sn-meta">${dateStr}</span>
                </a>`;
            }).join('')
            : `<div style="color:var(--text-3);font-size:13px;padding:10px 0;">Bu hisse icin guncel haber bulunamadi.</div>`;

        return `
            <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
                <div>
                    <h2 style="margin:0;font-family:'Outfit';font-size:28px;">${display}</h2>
                    <div style="color:var(--text-3);font-size:12px;letter-spacing:1px;text-transform:uppercase;">${d.symbol}</div>
                </div>
                <button id="modalStar" class="star-toggle ${isWatched ? 'active' : ''}" style="position:static;font-size:22px;" title="Favorilere ekle">&#9733;</button>
                <div style="margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    ${spikeHtml}${nearPeakHtml}
                    <div class="score-chip" data-score="${d.score}"><span class="star">&#9733;</span> ${d.score}/5</div>
                </div>
            </div>
            ${reason ? `<div style="margin-top:12px;padding:10px 14px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid var(--glass-brd-soft);font-size:13px;color:var(--text-2);line-height:1.6;">${escapeHtml(reason)}</div>` : ''}
            <canvas id="detailChart" class="mini-chart" style="margin-top:18px;"></canvas>
            <div class="detail-row"><span class="k">Fiyat</span><span>${fmtPrice(d.price, ccy)}</span></div>
            <div class="detail-row"><span class="k">Gunluk Degisim</span><span style="color:${change >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(change)}</span></div>
            <div class="detail-row"><span class="k">Haftalik Degisim</span><span style="color:${(d.change_week_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(d.change_week_pct)}</span></div>
            <div class="detail-row"><span class="k">Aylik Degisim</span><span style="color:${(d.change_month_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)'}">${fmtChange(d.change_month_pct)}</span></div>
            <div class="detail-row"><span class="k">52 Hafta Yuksek</span><span>${fmtPrice(d.high_52w, ccy)}</span></div>
            <div class="detail-row"><span class="k">52 Hafta Dusuk</span><span>${fmtPrice(d.low_52w, ccy)}</span></div>
            <div class="detail-row"><span class="k">20g Ort. Hacim</span><span>${fmtVolume(d.avg_volume_20d || 0)}</span></div>
            ${slTpHtml}
            ${srHtml}
            <div style="margin-top:18px;">
                ${d.indicators.map((ind) => `
                    <div class="detail-ind">
                        <div class="di-head">
                            <span class="di-name">${ind.name} ${ind.value != null ? `<span style="color:var(--text-3);font-weight:500">(${ind.value})</span>` : ''}</span>
                            <span class="badge ${ind.signal ? 'on' : ''}">${ind.signal ? 'AL' : '-'}</span>
                        </div>
                        <div class="di-reason">${ind.detail || ''}</div>
                    </div>`).join('')}
            </div>
            <div style="margin-top:22px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:10px;">Son Haberler</div>
                <div class="stock-news-list">${newsItems}</div>
            </div>
            <div id="addPosSection" class="add-pos-section">
                <button class="btn add-pos-toggle">&#128204; Portf&ouml;ye Ekle</button>
                <div class="add-pos-form hidden">
                    <div class="add-pos-fields">
                        <label class="add-pos-field">
                            <span>Al&#305;&#351; Tarihi</span>
                            <input type="date" id="posDate" />
                        </label>
                        <label class="add-pos-field">
                            <span>Al&#305;&#351; Fiyat&#305;</span>
                            <input type="number" id="posPrice" step="0.01" min="0.01" />
                        </label>
                        <label class="add-pos-field">
                            <span>Adet</span>
                            <input type="number" id="posQty" min="1" step="1" value="1" />
                        </label>
                    </div>
                    <div class="add-pos-btns">
                        <button class="btn btn-primary" id="posConfirmBtn">Portf&ouml;ye Ekle</button>
                        <button class="btn" id="posCancelBtn">&#304;ptal</button>
                    </div>
                </div>
            </div>
        `;
    }

    function drawDetailChart(history, supports, resistances, stopLoss, takeProfit) {
        const canvas = document.getElementById('detailChart');
        if (!canvas || !history.length) return;

        const closes = history.map((p) => p.close);
        const last = closes[closes.length - 1];
        const first = closes[0];
        const isUp = last >= first;

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const w = Math.max(1, rect.width);
        const h = Math.max(1, rect.height);
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, w, h);

        // Price range: include S/R and SL/TP levels
        const allPrices = [...closes];
        if (stopLoss && stopLoss > 0) allPrices.push(stopLoss);
        if (takeProfit && takeProfit > 0) allPrices.push(takeProfit);

        const rawMin = Math.min(...allPrices);
        const rawMax = Math.max(...allPrices);
        const pad5 = (rawMax - rawMin) * 0.05 || rawMin * 0.02;
        const minP = rawMin - pad5;
        const maxP = rawMax + pad5;
        const range = maxP - minP || 1;
        const pad = 12;

        const priceToY = (p) => h - ((p - minP) / range) * (h - pad * 2) - pad;

        // Draw horizontal level lines
        const drawHLine = (price, color, dash, alpha) => {
            if (price == null || price <= 0) return;
            const y = priceToY(price);
            if (y < 0 || y > h) return;
            ctx.save();
            ctx.beginPath();
            ctx.setLineDash(dash || [4, 4]);
            ctx.lineWidth = 1;
            ctx.strokeStyle = color;
            ctx.globalAlpha = alpha || 0.45;
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
            ctx.stroke();
            ctx.restore();
        };

        // Nearest 2 supports below price and 2 resistances above
        const nearSups = (supports || []).filter(s => s < last).slice(-2);
        const nearRess = (resistances || []).filter(r => r > last).slice(0, 2);
        nearSups.forEach(s => drawHLine(s, '#34f5a8', [3, 4], 0.4));
        nearRess.forEach(r => drawHLine(r, '#ff5370', [3, 4], 0.4));
        if (stopLoss) drawHLine(stopLoss, '#ff5370', [8, 4], 0.7);
        if (takeProfit) drawHLine(takeProfit, '#34f5a8', [8, 4], 0.7);

        // Draw price line
        const color = isUp ? '#34f5a8' : '#ff5370';
        const shadowCol = isUp ? 'rgba(52,245,168,.45)' : 'rgba(255,83,112,.45)';
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, isUp ? 'rgba(52,245,168,0.35)' : 'rgba(255,83,112,0.3)');
        grad.addColorStop(1, isUp ? 'rgba(52,245,168,0)' : 'rgba(255,83,112,0)');

        const step = w / Math.max(1, closes.length - 1);
        ctx.beginPath();
        closes.forEach((v, i) => {
            const x = i * step;
            const y = priceToY(v);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.lineWidth = 2;
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

    function closeModal() { els.modal.classList.add('hidden'); }

    // --- portfolio ---
    const PORTFOLIO_KEY = 'nebula.portfolio.v2';
    const port = { positions: [], details: {}, loading: new Set(), displayCurrency: 'TRY' };

    async function loadPortfolio() {
        if (_currentUser) {
            try {
                const d = await API.portfolioGet();
                port.positions = (d.portfolio || []).map(p => ({
                    id: p.id,
                    symbol: p.symbol,
                    market: p.currency === 'TRY' ? 'bist' : 'us',
                    buyDate: '',
                    buyPrice: p.avg_price,
                    qty: p.qty,
                }));
            } catch (_) { port.positions = []; }
        } else {
            try {
                const raw = localStorage.getItem(PORTFOLIO_KEY);
                if (raw) port.positions = JSON.parse(raw);
            } catch (_) { port.positions = []; }
        }
        updatePortBadge();
    }

    function savePortfolio() {
        if (_currentUser) { updatePortBadge(); return; }
        try { localStorage.setItem(PORTFOLIO_KEY, JSON.stringify(port.positions)); } catch (_) {}
        updatePortBadge();
    }

    function updatePortBadge() {
        const badge = document.getElementById('portBadge');
        if (!badge) return;
        const n = port.positions.length;
        badge.textContent = n;
        badge.classList.toggle('hidden', n === 0);
    }

    async function addPosition(symbol, market, buyDate, buyPrice, qty) {
        if (_currentUser) {
            try {
                const currency = market === 'bist' ? 'TRY' : 'USD';
                const d = await API.portfolioAdd({
                    symbol: symbol.toUpperCase(),
                    qty: parseFloat(qty) || 1,
                    avg_price: parseFloat(buyPrice),
                    currency,
                });
                if (d.ok && d.position) {
                    port.positions.push({
                        id: d.position.id,
                        symbol: d.position.symbol,
                        market,
                        buyDate,
                        buyPrice: d.position.avg_price,
                        qty: d.position.qty,
                    });
                }
            } catch (_) {}
        } else {
            port.positions.push({
                id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
                symbol: symbol.toUpperCase(),
                market: market || 'us',
                buyDate,
                buyPrice: parseFloat(buyPrice),
                qty: parseFloat(qty) || 1,
            });
            savePortfolio();
        }
        updatePortBadge();
    }

    async function removePosition(id) {
        port.positions = port.positions.filter(p => p.id !== id);
        if (_currentUser) {
            API.portfolioRemove(id).catch(() => {});
        } else {
            savePortfolio();
        }
        updatePortBadge();
    }

    async function fetchPortfolioDetails(force = false) {
        const symbols = [...new Set(port.positions.map(p => p.symbol))];
        const toFetch = force ? symbols : symbols.filter(s => !port.details[s] && !port.loading.has(s));
        if (!toFetch.length) return;
        await Promise.all(toFetch.map(async (sym) => {
            if (port.loading.has(sym)) return;
            port.loading.add(sym);
            try {
                const d = await API.stock(sym);
                if (!d.error) port.details[sym] = d;
            } catch (_) {}
            finally { port.loading.delete(sym); }
        }));
    }

    function detectTrend(history) {
        if (!history || history.length < 10) return 'neutral';
        const closes = history.map(h => h.close);
        const recent = closes.slice(-10);
        const older = closes.slice(-20, -10);
        if (older.length < 5) return 'neutral';
        const ra = recent.reduce((a, b) => a + b, 0) / recent.length;
        const oa = older.reduce((a, b) => a + b, 0) / older.length;
        const diff = (ra - oa) / oa * 100;
        if (diff > 2.5) return 'up';
        if (diff < -2.5) return 'down';
        return 'neutral';
    }

    function detectWedge(history) {
        if (!history || history.length < 20) return null;
        const closes = history.map(h => h.close).slice(-20);
        const mid = Math.floor(closes.length / 2);
        const early = closes.slice(0, mid);
        const late = closes.slice(mid);
        const earlyRange = Math.max(...early) - Math.min(...early);
        const lateRange = Math.max(...late) - Math.min(...late);
        if (earlyRange === 0 || lateRange / earlyRange > 0.60) return null;
        const earlyAvg = early.reduce((a, b) => a + b, 0) / early.length;
        const lateAvg = late.reduce((a, b) => a + b, 0) / late.length;
        return lateAvg > earlyAvg ? 'rising' : 'falling';
    }

    function buildSellRecommendation(d, pos) {
        const price = d.price;
        const pnlPct = (price - pos.buyPrice) / pos.buyPrice * 100;
        const sl = d.stop_loss;
        const tp = d.take_profit;
        const score = d.score || 0;
        const weekPct = d.change_week_pct || 0;
        const trend = detectTrend(d.history || []);
        const wedge = detectWedge(d.history || []);
        const reasons = [];

        // ── Hemen Sat ────────────────────────────────────────────────────────
        if (sl && price <= sl) {
            reasons.push('Stop loss seviyesi kırıldı, kayıpları sınırla');
            if (weekPct < -5) reasons.push(`Bu hafta %${Math.abs(weekPct).toFixed(1)} düşüş`);
            return { level: 'sat_hemen', label: 'Hemen Sat', reasons };
        }
        // Büyük zarar + zayıf sinyal + düşüş trendi (score=0-1 yeterli, score===0 gerekmez)
        if (pnlPct < -15 && score <= 1 && trend === 'down') {
            reasons.push(`%${Math.abs(pnlPct).toFixed(1)} zarar, al sinyali çok zayıf`);
            reasons.push('Düşüş trendi devam ediyor');
            return { level: 'sat_hemen', label: 'Hemen Sat', reasons };
        }

        // ── Kar Al (yalnızca gerçek karda) ───────────────────────────────────
        // TP hedefi direnç bölgesidir; kullanıcı zarardayken "Kar Al" göstermek yanlış
        if (tp && price >= tp * 0.98 && pnlPct > 3) {
            reasons.push('Kar al hedefine (direnç bölgesi) ulaşıldı');
            if (d.near_peak) reasons.push('52 haftalık zirveye çok yakın');
            return { level: 'kar_al', label: 'Kar Al', reasons };
        }
        if (d.near_peak && pnlPct > 15) {
            reasons.push(`%${pnlPct.toFixed(1)} kar var, zirve bölgesine girildi`);
            reasons.push('Kısmi kar almayı değerlendirin');
            return { level: 'kar_al', label: 'Kar Al', reasons };
        }
        if (pnlPct > 30 && score <= 1) {
            reasons.push(`%${pnlPct.toFixed(1)} büyük kar elde edildi`);
            reasons.push('Sinyaller zayıfladı, karı koruma zamanı');
            return { level: 'kar_al', label: 'Kar Al', reasons };
        }

        // ── Satışı Düşün ─────────────────────────────────────────────────────
        let bearish = 0;
        if (sl && price < sl * 1.035) { reasons.push("Stop loss'a %3'ten az mesafe kaldı"); bearish += 2; }
        // Orta-büyük zarar + düşüş trendi: score fark etmeksizin uyar
        if (pnlPct < -10 && trend === 'down') {
            reasons.push(`%${Math.abs(pnlPct).toFixed(1)} zararda ve düşüş trendi`);
            bearish += 2;
        }
        if (score <= 1 && weekPct < -3) { reasons.push(`${score}/5 sinyal, haftalık %${weekPct.toFixed(1)}`); bearish++; }
        // Karda ama tüm sinyaller söndü
        if (pnlPct > 18 && score === 0) { reasons.push(`%${pnlPct.toFixed(1)} karda ama tüm sinyaller söndü`); bearish += 2; }
        if (wedge === 'rising' && score <= 2) { reasons.push('Yükselen kama kırılım riski (bearish)'); bearish++; }
        if (trend === 'down' && score <= 1 && pnlPct < 0) { reasons.push('Düşüş trendi + zararda pozisyon'); bearish++; }
        if (bearish >= 2) return { level: 'sat_dusun', label: 'Satışı Düşün', reasons: reasons.slice(0, 3) };

        // ── Tut ──────────────────────────────────────────────────────────────
        let bullish = 0;
        const bullReasons = [];
        if (score >= 4) { bullReasons.push(`${score}/5 güçlü al sinyali`); bullish += 2; }
        else if (score === 3) { bullReasons.push('3/5 iyi sinyal seviyesi'); bullish++; }
        if (trend === 'up') { bullReasons.push('Yukarı trend devam ediyor'); bullish++; }
        if (d.volume_spike) { bullReasons.push('Hacim patlaması güç göstergesi'); bullish++; }
        if (wedge === 'falling') { bullReasons.push('Düşen kama — yukarı kırılım beklentisi'); bullish++; }
        if (weekPct > 3 && score >= 2) { bullReasons.push(`Haftalık +%${weekPct.toFixed(1)} güçlü ivme`); bullish++; }
        if (bullish >= 3) return { level: 'tut', label: 'Tut', reasons: bullReasons.slice(0, 3) };

        // ── İzle ─────────────────────────────────────────────────────────────
        const watchReasons = [];
        if (score >= 2) watchReasons.push(`${score}/5 sinyal var, güçlenme bekleniyor`);
        if (Math.abs(weekPct) <= 2) watchReasons.push('Yatay seyir, net yön bekleniyor');
        else if (weekPct > 0) watchReasons.push(`Haftalık +%${weekPct.toFixed(1)} pozitif seyir`);
        if (wedge) watchReasons.push(wedge === 'rising' ? 'Yükselen kama: kırılımı izle' : 'Düşen kama: yukarı kırılım beklentisi');
        if (!watchReasons.length) watchReasons.push('Karma sinyaller, izlemeye devam');
        return { level: 'izle', label: 'İzle', reasons: watchReasons.slice(0, 2) };
    }

    function fmtPortPrice(price, market) {
        if (market === 'bist') {
            return '₺' + price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        return '$' + price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Portföy toplam K/Z'yi seçili para birimine göre formatlar (TRY normalize edilmiş değer alır)
    function fmtPortTotal(tryAmount) {
        if (port.displayCurrency === 'USD' && state.usdRate)
            return '$' + (tryAmount / state.usdRate).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return '₺' + tryAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function renderPortfolioTab() {
        const overview = document.getElementById('portOverview');
        const list = document.getElementById('portList');
        if (!overview || !list) return;

        if (!port.positions.length) {
            overview.innerHTML = '';
            list.innerHTML = `
                <div class="empty glass" style="text-align:center;padding:50px 20px;">
                    <div style="font-size:48px;margin-bottom:16px;">💼</div>
                    <div style="font-size:17px;font-weight:600;margin-bottom:8px;">Portföyünüz henüz boş</div>
                    <div style="font-size:13px;color:var(--text-3);max-width:300px;margin:0 auto;line-height:1.6;">
                        Tarama sekmesinden bir hisseye tıklayın ve "Portföye Ekle" butonunu kullanın.
                    </div>
                </div>`;
            return;
        }

        // Tüm değerleri TRY'ye normalize ederek topla (USD pozisyonlar kur ile çarpılır)
        const rate = state.usdRate || 1;
        let totalInvestedTRY = 0, totalCurrentTRY = 0, loadedCount = 0;
        const hasMixed = port.positions.some(p => p.market === 'us') && port.positions.some(p => p.market === 'bist');
        for (const pos of port.positions) {
            const d = port.details[pos.symbol];
            const posRate = pos.market === 'us' ? rate : 1;
            totalInvestedTRY += pos.buyPrice * pos.qty * posRate;
            if (d) { totalCurrentTRY += d.price * pos.qty * posRate; loadedCount++; }
        }
        const totalPnlTRY = totalCurrentTRY - totalInvestedTRY;
        const totalPnlPct = totalInvestedTRY > 0 ? totalPnlTRY / totalInvestedTRY * 100 : 0;
        const pnlColor = totalPnlTRY >= 0 ? 'var(--neon)' : 'var(--danger)';

        const currencyLabel = port.displayCurrency === 'USD' ? 'USD' : 'TRY';
        const otherCurrency = port.displayCurrency === 'USD' ? 'TRY' : 'USD';
        const currencyToggleHtml = state.usdRate ? `
            <div class="port-currency-toggle">
                <span style="font-size:12px;color:var(--text-3);">Göster:</span>
                <button class="port-ccy-btn ${port.displayCurrency === 'TRY' ? 'active' : ''}" data-ccy="TRY">₺ TRY</button>
                <button class="port-ccy-btn ${port.displayCurrency === 'USD' ? 'active' : ''}" data-ccy="USD">$ USD</button>
                ${hasMixed ? '<span class="port-ccy-note">Kur dahil</span>' : ''}
            </div>` : '';

        overview.innerHTML = `
            <div class="port-overview glass">
                <div class="port-ov-item">
                    <span class="s-label">Toplam Yatırım</span>
                    <span class="s-value">${fmtPortTotal(totalInvestedTRY)}</span>
                </div>
                <div class="port-ov-item">
                    <span class="s-label">Güncel Değer</span>
                    <span class="s-value">${loadedCount ? fmtPortTotal(totalCurrentTRY) : '...'}</span>
                </div>
                <div class="port-ov-item">
                    <span class="s-label">Toplam K/Z</span>
                    <span class="s-value" style="color:${pnlColor}">
                        ${loadedCount
                            ? (totalPnlTRY >= 0 ? '+' : '') + fmtPortTotal(Math.abs(totalPnlTRY)) +
                              ' (' + (totalPnlPct >= 0 ? '+' : '') + totalPnlPct.toFixed(2) + '%)'
                            : '...'}
                    </span>
                </div>
                <div class="port-ov-item">
                    <span class="s-label">Açık Pozisyon</span>
                    <span class="s-value">${port.positions.length}</span>
                </div>
            </div>
            ${currencyToggleHtml}`;

        overview.querySelectorAll('.port-ccy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                port.displayCurrency = btn.dataset.ccy;
                renderPortfolioTab();
            });
        });

        const frag = document.createDocumentFragment();
        [...port.positions].reverse().forEach(pos => {
            frag.appendChild(buildPositionCard(pos, port.details[pos.symbol]));
        });
        list.innerHTML = '';
        list.appendChild(frag);
    }

    function buildPositionCard(pos, d) {
        const card = document.createElement('div');
        card.className = 'port-card glass';
        const displaySym = pos.symbol.replace('.IS', '');

        const headerHtml = `
            <div class="port-card-top">
                <div class="port-sym-block">
                    <span class="port-sym">${displaySym}</span>
                    <span class="port-sym-full">${pos.symbol}</span>
                </div>
                <div class="port-buy-info">
                    <span>${fmtPortPrice(pos.buyPrice, pos.market)} &times; ${pos.qty} adet</span>
                    <span class="port-buy-date">${pos.buyDate}</span>
                </div>
                <button class="port-remove-btn" data-id="${pos.id}" title="Pozisyonu kaldır">&times;</button>
            </div>`;

        if (!d) {
            card.innerHTML = headerHtml + `
                <div class="port-loading">
                    <span class="port-loading-dot"></span>
                    <span class="port-loading-dot"></span>
                    <span class="port-loading-dot"></span>
                    Güncel fiyat yükleniyor...
                </div>`;
        } else {
            const price = d.price;
            const pnlRaw = (price - pos.buyPrice) * pos.qty;
            const pnlPct = (price - pos.buyPrice) / pos.buyPrice * 100;
            const pnlColor = pnlRaw >= 0 ? 'var(--neon)' : 'var(--danger)';
            const pnlSign = pnlRaw >= 0 ? '+' : '';
            const rec = buildSellRecommendation(d, pos);
            const recClass = { sat_hemen: 'rec-danger', kar_al: 'rec-take', sat_dusun: 'rec-warn', tut: 'rec-hold', izle: 'rec-watch' }[rec.level] || 'rec-watch';
            const sl = d.stop_loss, tp = d.take_profit, rr = d.risk_reward;

            card.innerHTML = headerHtml + `
                <div class="port-card-body">
                    <div class="port-current-row">
                        <div>
                            <div class="port-price-label">G&uuml;ncel Fiyat</div>
                            <div class="port-current-price">${fmtPortPrice(price, pos.market)}</div>
                            <div style="font-size:12px;color:var(--text-3);margin-top:2px;">${(d.change_pct || 0) >= 0 ? '+' : ''}${(d.change_pct || 0).toFixed(2)}% bug&uuml;n</div>
                        </div>
                        <div class="port-pnl" style="color:${pnlColor}">
                            <div class="port-pnl-main">${pnlSign}${fmtPortPrice(Math.abs(pnlRaw), pos.market)}</div>
                            <div class="port-pnl-pct">${pnlSign}${pnlPct.toFixed(2)}%</div>
                        </div>
                    </div>
                    <div class="port-levels-row">
                        ${sl ? `<span class="port-level port-sl">SL: ${fmtPortPrice(sl, pos.market)}</span>` : ''}
                        ${tp ? `<span class="port-level port-tp">TP: ${fmtPortPrice(tp, pos.market)}</span>` : ''}
                        ${rr ? `<span class="port-level port-rr">R/R 1:${rr}</span>` : ''}
                        <span class="port-level port-score">${d.score}/5 sinyal</span>
                    </div>
                    <div class="port-rec ${recClass}">
                        <span class="rec-badge">${escapeHtml(rec.label)}</span>
                        <div class="rec-reasons">${rec.reasons.map(r => `<span>&middot; ${escapeHtml(r)}</span>`).join('')}</div>
                    </div>
                    <div class="port-card-footer">
                        <button class="btn btn-sm port-detail-btn" data-sym="${pos.symbol}">Grafik &amp; Detay</button>
                        <button class="port-remove-link" data-id="${pos.id}">Kaldır</button>
                    </div>
                </div>`;
        }

        card.querySelectorAll('.port-remove-btn, .port-remove-link').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                removePosition(btn.dataset.id);
                renderPortfolioTab();
            });
        });
        const detBtn = card.querySelector('.port-detail-btn');
        if (detBtn) detBtn.addEventListener('click', (e) => { e.stopPropagation(); openPortfolioChart(pos); });
        return card;
    }

    function wireModalPortfolioForm(data) {
        const section = document.getElementById('addPosSection');
        if (!section) return;
        const toggle = section.querySelector('.add-pos-toggle');
        const form = section.querySelector('.add-pos-form');
        const priceInput = document.getElementById('posPrice');
        const dateInput = document.getElementById('posDate');
        const qtyInput = document.getElementById('posQty');

        if (priceInput) priceInput.value = data.price;
        if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];
        if (qtyInput) qtyInput.value = 1;

        const existing = port.positions.filter(p => p.symbol === data.symbol);
        if (toggle && existing.length > 0)
            toggle.innerHTML = `&#128204; Portf&ouml;ye Ekle <span style="opacity:.6;font-size:11px;">(${existing.length} mevcut)</span>`;

        toggle?.addEventListener('click', () => form?.classList.toggle('hidden'));
        document.getElementById('posCancelBtn')?.addEventListener('click', () => form?.classList.add('hidden'));
        document.getElementById('posConfirmBtn')?.addEventListener('click', () => {
            const date = dateInput?.value;
            const price = parseFloat(priceInput?.value);
            const qty = parseFloat(qtyInput?.value) || 1;
            if (!date || !price || isNaN(price) || price <= 0) { priceInput?.focus(); return; }
            addPosition(data.symbol, state.market, date, price, qty);
            form?.classList.add('hidden');
            if (toggle) {
                const n = port.positions.filter(p => p.symbol === data.symbol).length;
                toggle.innerHTML = `&#10003; Portf&ouml;ye Eklendi (${n} pozisyon)`;
                toggle.style.cssText = 'background:rgba(52,245,168,.12);color:var(--neon);border-color:rgba(52,245,168,.4);pointer-events:none;';
            }
        });
    }

    // --- grafik analizi (portföy + tarama) ---
    async function openPortfolioChart(pos) {
        const modal = document.getElementById('portChartModal');
        const headerEl = document.getElementById('portChartHeader');
        const chartEl = document.getElementById('portChartContainer');
        const patternEl = document.getElementById('portPatternCards');
        if (!modal) return;

        modal.classList.remove('hidden');
        if (headerEl) headerEl.innerHTML = `<div style="color:var(--text-3);padding:4px 0 8px;">Grafik yükleniyor...</div>`;
        if (chartEl) chartEl.innerHTML = '';
        if (patternEl) patternEl.innerHTML = '';

        if (!port.details[pos.symbol]) {
            try {
                const d = await API.stock(pos.symbol);
                if (!d.error) port.details[pos.symbol] = d;
            } catch (_) {}
        }
        renderChartModal(port.details[pos.symbol], pos);
    }

    async function openScanChart(r) {
        const modal = document.getElementById('portChartModal');
        const headerEl = document.getElementById('portChartHeader');
        const chartEl = document.getElementById('portChartContainer');
        const patternEl = document.getElementById('portPatternCards');
        if (!modal) return;

        modal.classList.remove('hidden');
        if (headerEl) headerEl.innerHTML = `<div style="color:var(--text-3);padding:4px 0 8px;">Grafik yükleniyor...</div>`;
        if (chartEl) chartEl.innerHTML = '';
        if (patternEl) patternEl.innerHTML = '';

        let d = null;
        try {
            d = await API.stock(r.symbol);
            if (d.error === 'auth_required') {
                modal.classList.add('hidden');
                openAuthModal('signup');
                return;
            }
            if (d.error) throw new Error(d.error);
        } catch (err) {
            if (headerEl) headerEl.innerHTML = `<div style="color:var(--danger);padding:8px;">Veri yüklenemedi: ${escapeHtml(err.message)}</div>`;
            return;
        }
        renderChartModal(d, null);
    }

    function renderChartModal(d, pos) {
        const headerEl = document.getElementById('portChartHeader');
        const chartEl = document.getElementById('portChartContainer');
        const patternEl = document.getElementById('portPatternCards');
        if (!headerEl || !chartEl) return;

        if (chartEl._lwChart) { try { chartEl._lwChart.remove(); } catch (_) {} chartEl._lwChart = null; }
        if (chartEl._resizeObs) { chartEl._resizeObs.disconnect(); chartEl._resizeObs = null; }

        const symbol = d ? d.symbol : (pos ? pos.symbol : '?');
        const displaySym = symbol.replace('.IS', '');
        const market = pos ? pos.market : state.market;
        const price = d ? d.price : null;

        let contextHtml = '';
        let recHtml = '';
        if (pos) {
            const pnlPct = (price !== null) ? (price - pos.buyPrice) / pos.buyPrice * 100 : null;
            const pnlColor = (pnlPct !== null && pnlPct >= 0) ? 'var(--neon)' : 'var(--danger)';
            const pnlSign = (pnlPct !== null && pnlPct >= 0) ? '+' : '';
            const rec = d ? buildSellRecommendation(d, pos) : null;
            const recClass = rec ? ({ sat_hemen: 'rec-danger', kar_al: 'rec-take', sat_dusun: 'rec-warn', tut: 'rec-hold', izle: 'rec-watch' }[rec.level] || 'rec-watch') : '';
            contextHtml = `
                <div class="chart-pos-context">
                    <span>Alış: <strong>${fmtPortPrice(pos.buyPrice, pos.market)}</strong> &times; ${pos.qty} adet</span>
                    <span>${pos.buyDate}</span>
                    ${price !== null ? `<span>Güncel: <strong>${fmtPortPrice(price, pos.market)}</strong></span>` : ''}
                    ${pnlPct !== null ? `<span class="pnl-pos" style="color:${pnlColor}">${pnlSign}${pnlPct.toFixed(2)}%</span>` : ''}
                </div>`;
            recHtml = rec ? `<div class="port-rec ${recClass}" style="margin-top:0;flex-shrink:0;"><span class="rec-badge">${escapeHtml(rec.label)}</span></div>` : '';
        } else {
            const reason = d ? buildScoreReason(d) : '';
            const spikeHtml = d && d.volume_spike ? `<span class="badge volume-spike">&#128640; Hacim Patlamasi</span>` : '';
            const nearPeakHtml = d && d.near_peak ? `<span class="badge near-peak">&#9650; Tepe</span>` : '';
            contextHtml = `
                <div class="chart-pos-context" style="align-items:center;gap:8px;">
                    ${spikeHtml}${nearPeakHtml}
                    ${reason ? `<span style="font-size:12px;color:var(--text-2);font-style:italic;">${escapeHtml(reason)}</span>` : ''}
                </div>`;
        }

        headerEl.innerHTML = `
            <div class="chart-modal-hdr">
                <div>
                    <div class="chart-sym-row">
                        <span class="chart-sym">${displaySym}</span>
                        <span class="chart-market-badge">${market.toUpperCase()}</span>
                        ${d && d.score != null ? `<span class="score-chip" data-score="${d.score}" style="font-size:12px;padding:3px 10px;"><span class="star">&#9733;</span> ${d.score}/5</span>` : ''}
                    </div>
                    ${contextHtml}
                </div>
                ${recHtml}
            </div>
            <div class="chart-legend">
                ${pos ? `<span class="chart-legend-item"><span class="chart-legend-line" style="background:#a78bfa;"></span>Alış</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:#ff5370;border-top:2px dashed #ff5370;height:0;"></span>SL</span>` : ''}
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:#34f5a8;border-top:2px dashed #34f5a8;height:0;"></span>TP</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(52,245,168,.4);"></span>Destek</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(255,83,112,.4);"></span>Direnç</span>
            </div>`;

        if (!d || !d.ohlcv || !d.ohlcv.length) {
            chartEl.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-3);font-size:13px;">Grafik verisi yüklenemedi.</div>';
            return;
        }

        if (typeof LightweightCharts === 'undefined') {
            chartEl.innerHTML = '<div style="padding:20px;color:var(--text-3);font-size:13px;">Grafik kütüphanesi yüklenemedi. İnternet bağlantısını kontrol edin.</div>';
            return;
        }

        const chart = LightweightCharts.createChart(chartEl, {
            width: chartEl.clientWidth,
            height: chartEl.clientHeight || 400,
            layout: {
                background: { type: LightweightCharts.ColorType ? LightweightCharts.ColorType.Solid : 'solid', color: '#07080f' },
                textColor: '#8a8fb5',
                fontSize: 11,
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,.04)' },
                horzLines: { color: 'rgba(255,255,255,.04)' },
            },
            crosshair: { mode: 1 },
            rightPriceScale: { borderColor: 'rgba(255,255,255,.08)' },
            timeScale: { borderColor: 'rgba(255,255,255,.08)', timeVisible: true, secondsVisible: false },
        });
        chartEl._lwChart = chart;

        const candleSeries = chart.addCandlestickSeries({
            upColor: '#34f5a8', downColor: '#ff5370',
            borderUpColor: '#34f5a8', borderDownColor: '#ff5370',
            wickUpColor: '#34f5a8', wickDownColor: '#ff5370',
        });
        candleSeries.setData(d.ohlcv.map(b => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c })));

        const volSeries = chart.addHistogramSeries({
            color: 'rgba(52,245,168,.3)',
            priceFormat: { type: 'volume' },
            priceScaleId: '',
        });
        volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
        volSeries.setData(d.ohlcv.map(b => ({
            time: b.t, value: b.v || 0,
            color: b.c >= b.o ? 'rgba(52,245,168,.28)' : 'rgba(255,83,112,.28)',
        })));

        if (pos) {
            candleSeries.createPriceLine({ price: pos.buyPrice, color: 'rgba(167,139,250,.9)', lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: 'Alış' });
            if (d.stop_loss)   candleSeries.createPriceLine({ price: d.stop_loss,   color: '#ff5370', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
            if (d.take_profit) candleSeries.createPriceLine({ price: d.take_profit, color: '#34f5a8', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP' });
        } else {
            if (d.stop_loss)   candleSeries.createPriceLine({ price: d.stop_loss,   color: 'rgba(255,83,112,.7)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
            if (d.take_profit) candleSeries.createPriceLine({ price: d.take_profit, color: 'rgba(52,245,168,.7)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP' });
        }

        const curPrice = d.price;
        (d.supports || []).filter(s => s < curPrice).slice(-3).forEach(s =>
            candleSeries.createPriceLine({ price: s, color: 'rgba(52,245,168,.45)', lineWidth: 1, lineStyle: 4, axisLabelVisible: false, title: '' })
        );
        (d.resistances || []).filter(r => r > curPrice).slice(0, 3).forEach(r =>
            candleSeries.createPriceLine({ price: r, color: 'rgba(255,83,112,.45)', lineWidth: 1, lineStyle: 4, axisLabelVisible: false, title: '' })
        );

        const patterns = d.patterns || [];
        const allMarkers = [];
        patterns.forEach(pat => {
            (pat.markers || []).forEach(m => {
                if (!m.t) return;
                allMarkers.push({ time: m.t, position: m.pos, color: m.color, shape: m.shape, text: m.label || '' });
            });
            (pat.trendlines || []).forEach(line => {
                if (!line || line.length < 2 || !line[0].t || !line[1].t) return;
                const col = pat.direction === 'bullish' ? 'rgba(52,245,168,.55)' :
                            pat.direction === 'bearish' ? 'rgba(255,83,112,.55)' : 'rgba(251,191,36,.55)';
                try {
                    const ls = chart.addLineSeries({ color: col, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
                    ls.setData([{ time: line[0].t, value: line[0].v }, { time: line[1].t, value: line[1].v }]);
                } catch (_) {}
            });
        });
        if (allMarkers.length) {
            try { candleSeries.setMarkers(allMarkers.sort((a, b) => (a.time < b.time ? -1 : 1))); } catch (_) {}
        }

        chart.timeScale().fitContent();

        const ro = new ResizeObserver(() => { try { chart.applyOptions({ width: chartEl.clientWidth }); } catch (_) {} });
        ro.observe(chartEl);
        chartEl._resizeObs = ro;

        if (patternEl) {
            if (!patterns.length) {
                patternEl.innerHTML = `
                    <div class="pattern-empty">
                        <span>Aktif formasyon tespit edilmedi</span>
                        <small>Son 90 barda bilinen bir grafik formasyonu bulunamadı.</small>
                    </div>`;
            } else {
                patternEl.innerHTML = `
                    <div class="pattern-section-title">Tespit Edilen Formasyonlar &mdash; ${patterns.length} adet</div>
                    <div class="pattern-grid">
                        ${patterns.map(p => `
                            <div class="pattern-card ${escapeHtml(p.direction)}">
                                <div class="pattern-card-hdr">
                                    <span class="pattern-emoji">${p.emoji || '📊'}</span>
                                    <span class="pattern-name">${escapeHtml(p.name)}</span>
                                    <span class="pattern-strength">${escapeHtml(p.strength)}</span>
                                </div>
                                <div class="pattern-desc">${escapeHtml(p.description)}</div>
                                <div class="pattern-signal">${escapeHtml(p.signal)}</div>
                            </div>`).join('')}
                    </div>`;
            }
        }
    }

    function closePortChartModal() {
        const modal = document.getElementById('portChartModal');
        if (!modal) return;
        modal.classList.add('hidden');
        const chartEl = document.getElementById('portChartContainer');
        if (chartEl) {
            if (chartEl._lwChart) { try { chartEl._lwChart.remove(); } catch (_) {} chartEl._lwChart = null; }
            if (chartEl._resizeObs) { chartEl._resizeObs.disconnect(); chartEl._resizeObs = null; }
            chartEl.innerHTML = '';
        }
    }

    document.getElementById('portChartClose')?.addEventListener('click', closePortChartModal);
    document.getElementById('portChartModal')?.querySelector('.modal-backdrop')?.addEventListener('click', closePortChartModal);

    function switchTab(tab) {
        const scanSec = document.getElementById('tab-scan');
        const portSec = document.getElementById('tab-portfolio');
        const alertSec = document.getElementById('tab-alerts');
        if (scanSec) scanSec.classList.toggle('hidden', tab !== 'scan');
        if (portSec) portSec.classList.toggle('hidden', tab !== 'portfolio');
        if (alertSec) alertSec.classList.toggle('hidden', tab !== 'alerts');
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
        if (tab === 'portfolio') {
            const rateP = state.usdRate ? Promise.resolve() : fetchExchangeRate();
            rateP.then(() => fetchPortfolioDetails()).then(() => renderPortfolioTab());
        }
        if (tab === 'alerts') loadAlerts();
    }
    document.querySelectorAll('.tab-btn').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

    // --- events ---
    els.refreshBtn.addEventListener('click', () => loadScan(true));

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
        const m = ms();
        if (m.hasMore && m.loadedOnce) {
            state.byMarket[state.market] = newMarketState();
            loadScan();
        } else {
            renderResults();
        }
    });

    els.modalClose.addEventListener('click', closeModal);
    els.modal.querySelector('.modal-backdrop').addEventListener('click', closeModal);

    document.addEventListener('keydown', (e) => {
        const isTyping = ['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target && e.target.tagName) || '');
        if (e.key === 'Escape') { closeModal(); closePortChartModal(); return; }
        if (isTyping) return;
        if (e.key === '/') { e.preventDefault(); els.searchInput.focus(); return; }
        if (e.key.toLowerCase() === 'r') loadScan(true);
    });

    window.addEventListener('resize', () => {
        if (ms().results.length) renderResults();
    });

    // bootstrap — Auth.me() önce beklenir, sonra watchlist/portfolio API'den çekilir

    // ── Toast bildirimleri ────────────────────────────────────────────────────

    function showToast(message, type = 'info', duration = 5000) {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        const icons = { info: 'ℹ️', success: '✅', warning: '🔔', danger: '🚨' };
        toast.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ️'}</span><span class="toast-msg">${escapeHtml(message)}</span><button class="toast-close">&times;</button>`;
        toast.querySelector('.toast-close').addEventListener('click', () => toast.remove());
        container.appendChild(toast);
        setTimeout(() => toast.classList.add('toast-show'), 10);
        if (duration > 0) setTimeout(() => { toast.classList.remove('toast-show'); setTimeout(() => toast.remove(), 400); }, duration);
    }

    // ── Alarm sekmesi ─────────────────────────────────────────────────────────

    let alertConditions = [];

    async function loadAlerts() {
        const triggered = document.getElementById('triggeredAlerts');
        const active = document.getElementById('activeAlerts');
        const status = document.getElementById('alertsStatus');
        if (!triggered || !active) return;

        try {
            const [condData, alertData] = await Promise.all([
                alertConditions.length ? Promise.resolve({ conditions: alertConditions }) : API.alertsConditions(),
                API.alertsList(),
            ]);
            if (condData.conditions) alertConditions = condData.conditions;

            const alerts = alertData.alerts || [];
            const badge = document.getElementById('alertBadge');
            const triggeredList = alerts.filter(a => a.triggered_at && !a.dismissed);
            const activePending = alerts.filter(a => a.is_active && !a.triggered_at);

            if (badge) {
                if (triggeredList.length > 0) { badge.textContent = triggeredList.length; badge.classList.remove('hidden'); }
                else badge.classList.add('hidden');
            }
            if (status) status.textContent = `${activePending.length} aktif, ${triggeredList.length} tetiklendi`;

            triggered.innerHTML = triggeredList.length ? `
                <div class="alerts-section-title">🔔 Tetiklenen Alarmlar</div>
                ${triggeredList.map(renderAlertCard).join('')}
            ` : '';

            active.innerHTML = `
                <div class="alerts-section-title">📋 Aktif Alarmlar${activePending.length ? ` (${activePending.length})` : ''}</div>
                ${activePending.length
                    ? activePending.map(renderAlertCard).join('')
                    : '<div class="alerts-empty">Henüz aktif alarm yok. "Yeni Alarm" ile ekle.</div>'
                }
            `;

            document.querySelectorAll('.alert-dismiss-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const id = e.currentTarget.dataset.id;
                    await API.alertsDismiss(id);
                    loadAlerts();
                });
            });
            document.querySelectorAll('.alert-delete-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const id = e.currentTarget.dataset.id;
                    await API.alertsDelete(id);
                    loadAlerts();
                });
            });
        } catch (err) {
            if (active) active.innerHTML = `<div style="color:var(--danger);padding:16px;">Yüklenemedi: ${escapeHtml(err.message)}</div>`;
        }
    }

    function renderAlertCard(a) {
        const fired = !!a.triggered_at;
        const firedStr = fired ? new Date(a.triggered_at * 1000).toLocaleString('tr-TR') : '';
        const createdStr = new Date(a.created_at * 1000).toLocaleString('tr-TR');
        return `
        <div class="alert-card glass ${fired ? 'alert-fired' : ''}">
            <div class="alert-card-top">
                <span class="alert-sym">${escapeHtml(a.symbol)}</span>
                <span class="alert-label">${escapeHtml(a.label)}</span>
                ${fired ? '<span class="alert-badge-fired">Tetiklendi</span>' : '<span class="alert-badge-active">Aktif</span>'}
            </div>
            <div class="alert-card-meta">
                ${fired ? `<span>⏰ ${escapeHtml(firedStr)}</span>` : `<span>Oluşturuldu: ${escapeHtml(createdStr)}</span>`}
            </div>
            <div class="alert-card-actions">
                ${fired ? `<button class="btn btn-sm alert-dismiss-btn" data-id="${a.id}">Kapat</button>` : ''}
                <button class="btn btn-sm alert-delete-btn" data-id="${a.id}" style="color:var(--danger);border-color:rgba(255,83,112,.3);">Sil</button>
            </div>
        </div>`;
    }

    // Yeni alarm modal
    function openAlertModal() {
        const modal = document.getElementById('alertModal');
        const sel = document.getElementById('af-condition');
        if (!modal || !sel) return;

        const needsValue = ['rsi_below','rsi_above','score_above','price_below','price_above'];

        if (alertConditions.length && sel.options.length <= 1) {
            alertConditions.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.type; opt.textContent = c.label;
                sel.appendChild(opt);
            });
        }

        sel.onchange = () => {
            const wrap = document.getElementById('af-value-wrap');
            const lbl = document.getElementById('af-value-label');
            if (needsValue.includes(sel.value)) {
                wrap.classList.remove('hidden');
                const c = alertConditions.find(x => x.type === sel.value);
                if (lbl && c) lbl.textContent = c.label + ' (eşik değeri)';
            } else {
                wrap.classList.add('hidden');
            }
        };

        document.getElementById('af-symbol').value = '';
        document.getElementById('af-value').value = '';
        document.getElementById('af-condition').value = '';
        document.getElementById('af-value-wrap').classList.add('hidden');
        const errEl = document.getElementById('af-error');
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

        modal.classList.remove('hidden');
        document.getElementById('af-symbol').focus();
    }

    function closeAlertModal() {
        const modal = document.getElementById('alertModal');
        if (modal) modal.classList.add('hidden');
    }

    document.getElementById('newAlertBtn')?.addEventListener('click', () => {
        if (alertConditions.length === 0) {
            API.alertsConditions().then(d => { alertConditions = d.conditions || []; openAlertModal(); });
        } else {
            openAlertModal();
        }
    });
    document.getElementById('alertModalClose')?.addEventListener('click', closeAlertModal);
    document.getElementById('alertModalBackdrop')?.addEventListener('click', closeAlertModal);

    document.getElementById('af-submit')?.addEventListener('click', async () => {
        const symbol = (document.getElementById('af-symbol')?.value || '').trim().toUpperCase();
        const condition_type = document.getElementById('af-condition')?.value || '';
        const valueStr = document.getElementById('af-value')?.value || '';
        const needsValue = ['rsi_below','rsi_above','score_above','price_below','price_above'];
        const errEl = document.getElementById('af-error');

        if (!symbol || !condition_type) {
            if (errEl) { errEl.textContent = 'Hisse sembolü ve kriter zorunludur.'; errEl.style.display = 'block'; }
            return;
        }
        if (needsValue.includes(condition_type) && !valueStr) {
            if (errEl) { errEl.textContent = 'Bu kriter için eşik değeri girilmeli.'; errEl.style.display = 'block'; }
            return;
        }

        const body = { symbol, condition_type };
        if (valueStr) body.condition_value = parseFloat(valueStr);

        const btn = document.getElementById('af-submit');
        if (btn) btn.disabled = true;
        try {
            const res = await API.alertsCreate(body);
            if (res.ok) {
                closeAlertModal();
                showToast(`Alarm kuruldu: ${symbol} – ${res.alert.label}`, 'success');
                loadAlerts();
            } else {
                if (errEl) { errEl.textContent = res.error || 'Hata oluştu.'; errEl.style.display = 'block'; }
            }
        } catch (e) {
            if (errEl) { errEl.textContent = 'Sunucu hatası.'; errEl.style.display = 'block'; }
        } finally {
            if (btn) btn.disabled = false;
        }
    });

    // Tetiklenen alarmları periyodik kontrol (30 saniyede bir)
    async function pollTriggeredAlerts() {
        try {
            const data = await API.alertsTriggered();
            const list = data.triggered || [];
            list.forEach(a => {
                showToast(`🔔 ${a.symbol} – ${a.label}`, 'warning', 8000);
            });
            const badge = document.getElementById('alertBadge');
            if (badge && list.length > 0) { badge.textContent = list.length; badge.classList.remove('hidden'); }
        } catch (_) {}
    }
    setInterval(pollTriggeredAlerts, 30000);

    // ── Auth module ──────────────────────────────────────────────────────
    const Auth = {
        async me() {
            try {
                const d = await fetch('/api/auth/me', { credentials: 'include' }).then(r => r.json());
                return d;
            } catch { return { authenticated: false }; }
        },
        async _safeJson(r) {
            const ct = r.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                throw new Error(`Sunucu hatası (HTTP ${r.status}). Lütfen daha sonra tekrar deneyin.`);
            }
            return r.json();
        },
        async login(email, password) {
            const r = await fetch('/api/auth/login', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password }),
            });
            return this._safeJson(r);
        },
        async signup(email, password, kvkk_consent, marketing_consent) {
            const r = await fetch('/api/auth/signup', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password, kvkk_consent, marketing_consent }),
            });
            return this._safeJson(r);
        },
        async logout() {
            const r = await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
            return this._safeJson(r);
        },
        async forgot(email) {
            const r = await fetch('/api/auth/forgot', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email }),
            });
            return this._safeJson(r);
        },
    };

    let _currentUser = null;

    function applyUserState(user) {
        _currentUser = user;
        const authArea = document.getElementById('authArea');
        const userArea = document.getElementById('userArea');
        const upgradeBtn = document.getElementById('upgradeBtn');
        const planBadge = document.getElementById('planBadge');
        const userEmailEl = document.getElementById('userEmail');

        if (user) {
            authArea.classList.add('hidden');
            userArea.classList.remove('hidden');
            userEmailEl.textContent = user.email;
            if (planBadge) planBadge.classList.add('hidden');
            if (upgradeBtn) upgradeBtn.classList.add('hidden');
        } else {
            authArea.classList.remove('hidden');
            userArea.classList.add('hidden');
        }
    }

    // Bootstrap: önce auth durumunu öğren, sonra watchlist/portfolio yükle
    Auth.me().then(async d => {
        if (d.authenticated && d.user) {
            applyUserState(d.user);
        } else {
            applyUserState(null);
        }
        await Promise.all([loadWatchlist(), loadPortfolio()]);
        await loadMarkets();
        fetchExchangeRate();
        loadScan();
    });

    // Auth modal
    const authModal = document.getElementById('authModal');
    function showMarketGate() {
        // Misafir ABD sekmesine geçmeye çalışınca kayıt modalı açılır
        openAuthModal('signup');
    }

    function openAuthModal(tab) {
        authModal.classList.remove('hidden');
        const isReset = tab === 'reset';
        document.querySelector('.auth-tabs').style.display = isReset ? 'none' : '';
        document.querySelectorAll('.auth-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.auth === tab);
        });
        document.getElementById('authFormLogin').classList.toggle('hidden', tab !== 'login');
        document.getElementById('authFormSignup').classList.toggle('hidden', tab !== 'signup');
        document.getElementById('authFormForgot').classList.add('hidden');
        document.getElementById('authFormReset').classList.toggle('hidden', tab !== 'reset');
    }
    function closeAuthModal() { authModal.classList.add('hidden'); }

    document.getElementById('loginBtn')?.addEventListener('click', () => openAuthModal('login'));
    document.getElementById('signupBtn')?.addEventListener('click', () => openAuthModal('signup'));
    document.getElementById('authModalClose')?.addEventListener('click', closeAuthModal);
    document.getElementById('authModalBackdrop')?.addEventListener('click', closeAuthModal);
    document.getElementById('upgradeBtn')?.addEventListener('click', () => openPricingModal());

    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const which = tab.dataset.auth;
            openAuthModal(which);
        });
    });

    document.getElementById('forgotPasswordLink')?.addEventListener('click', e => {
        e.preventDefault();
        document.getElementById('authFormLogin').classList.add('hidden');
        document.getElementById('authFormForgot').classList.remove('hidden');
    });
    document.getElementById('backToLoginLink')?.addEventListener('click', e => {
        e.preventDefault();
        document.getElementById('authFormForgot').classList.add('hidden');
        document.getElementById('authFormLogin').classList.remove('hidden');
    });

    // Login submit
    document.getElementById('loginSubmit')?.addEventListener('click', async () => {
        const email = document.getElementById('loginEmail').value.trim();
        const password = document.getElementById('loginPassword').value;
        const errEl = document.getElementById('loginError');
        const btn = document.getElementById('loginSubmit');
        errEl.classList.add('hidden');
        btn.disabled = true;
        btn.textContent = 'Giriş yapılıyor...';
        try {
            const d = await Auth.login(email, password);
            if (d.ok && d.user) {
                applyUserState(d.user);
                closeAuthModal();
                showToast('Giriş yapıldı.', 'success');
            } else {
                errEl.textContent = d.message || 'E-posta veya şifre hatalı.';
                errEl.classList.remove('hidden');
            }
        } catch (err) {
            errEl.textContent = 'Bağlantı hatası: ' + err.message;
            errEl.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Giriş Yap';
        }
    });

    // Signup submit
    document.getElementById('signupSubmit')?.addEventListener('click', async () => {
        const email = document.getElementById('signupEmail').value.trim();
        const password = document.getElementById('signupPassword').value;
        const kvkk = document.getElementById('kvkkConsent').checked;
        const marketing = document.getElementById('marketingConsent').checked;
        const errEl = document.getElementById('signupError');
        const btn = document.getElementById('signupSubmit');
        errEl.classList.add('hidden');
        if (!kvkk) {
            errEl.textContent = 'KVKK onayı zorunludur.';
            errEl.classList.remove('hidden');
            return;
        }
        btn.disabled = true;
        btn.textContent = 'Hesap oluşturuluyor...';
        try {
            const d = await Auth.signup(email, password, kvkk, marketing);
            if (d.ok && d.user) {
                applyUserState(d.user);
                closeAuthModal();
                showToast('Hesabınız oluşturuldu! Doğrulama e-postası gönderildi.', 'success', 6000);
            } else {
                errEl.textContent = d.message || 'Kayıt başarısız.';
                errEl.classList.remove('hidden');
            }
        } catch (err) {
            errEl.textContent = 'Bağlantı hatası: ' + err.message;
            errEl.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Hesap Oluştur';
        }
    });

    // Forgot submit
    document.getElementById('forgotSubmit')?.addEventListener('click', async () => {
        const email = document.getElementById('forgotEmail').value.trim();
        await Auth.forgot(email);
        document.getElementById('forgotMsg').style.display = 'block';
    });

    // Reset password submit
    let _pendingResetToken = '';
    document.getElementById('resetSubmit')?.addEventListener('click', async () => {
        const password = document.getElementById('resetPassword').value;
        const msgEl = document.getElementById('resetMsg');
        const btn = document.getElementById('resetSubmit');
        msgEl.style.display = 'none';
        btn.disabled = true;
        btn.textContent = 'Güncelleniyor...';
        try {
            const d = await fetch('/api/auth/reset', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: _pendingResetToken, password }),
            }).then(r => r.json());
            if (d.ok) {
                msgEl.textContent = 'Şifreniz güncellendi! Giriş yapabilirsiniz.';
                msgEl.style.color = 'var(--success)';
                msgEl.style.display = 'block';
                setTimeout(() => openAuthModal('login'), 2000);
            } else {
                msgEl.textContent = d.message || 'Geçersiz veya süresi dolmuş bağlantı.';
                msgEl.style.color = 'var(--danger)';
                msgEl.style.display = 'block';
            }
        } catch {
            msgEl.textContent = 'Bağlantı hatası.';
            msgEl.style.color = 'var(--danger)';
            msgEl.style.display = 'block';
        } finally {
            btn.disabled = false;
            btn.textContent = 'Şifremi Güncelle';
        }
    });

    // Logout
    document.getElementById('logoutBtn')?.addEventListener('click', async () => {
        await Auth.logout();
        applyUserState(null);
        showToast('Çıkış yapıldı.', 'info');
    });

    // ── Hesap Paneli ─────────────────────────────────────────────────────
    const accountPanel = document.getElementById('accountPanel');
    const userPill = document.getElementById('userPill');

    userPill?.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!accountPanel) return;
        const isHidden = accountPanel.classList.contains('hidden');
        accountPanel.classList.toggle('hidden', !isHidden);
        if (!isHidden) return;
        // E-postayı güncelle
        const panelEmail = document.getElementById('accountPanelEmail');
        if (panelEmail && _currentUser) panelEmail.textContent = _currentUser.email;
    });
    // Panel dışına tıklayınca kapat
    document.addEventListener('click', (e) => {
        if (accountPanel && !accountPanel.contains(e.target) && e.target !== userPill) {
            accountPanel.classList.add('hidden');
        }
    });

    // Veri indirme (KVKK export)
    document.getElementById('exportDataBtn')?.addEventListener('click', async () => {
        accountPanel?.classList.add('hidden');
        try {
            const r = await fetch('/api/auth/export');
            if (!r.ok) { showToast('Veriler alınamadı.', 'error'); return; }
            const data = await r.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'nebula_verilerim.json'; a.click();
            URL.revokeObjectURL(url);
            showToast('Verileriniz indirildi.', 'success');
        } catch { showToast('İndirme başarısız.', 'error'); }
    });

    // Hesap silme
    const confirmDeleteModal = document.getElementById('confirmDeleteModal');
    document.getElementById('deleteAccountBtn')?.addEventListener('click', () => {
        accountPanel?.classList.add('hidden');
        confirmDeleteModal?.classList.remove('hidden');
        const errEl = document.getElementById('confirmDeleteError');
        if (errEl) errEl.style.display = 'none';
    });
    document.getElementById('confirmDeleteCancel')?.addEventListener('click', () => {
        confirmDeleteModal?.classList.add('hidden');
    });
    document.getElementById('confirmDeleteBackdrop')?.addEventListener('click', () => {
        confirmDeleteModal?.classList.add('hidden');
    });
    document.getElementById('confirmDeleteOk')?.addEventListener('click', async () => {
        const btn = document.getElementById('confirmDeleteOk');
        const errEl = document.getElementById('confirmDeleteError');
        btn.disabled = true;
        btn.textContent = 'Siliniyor...';
        try {
            const r = await fetch('/api/auth/me', { method: 'DELETE' });
            if (r.ok) {
                confirmDeleteModal?.classList.add('hidden');
                applyUserState(null);
                port.positions = [];
                state.watchlist = new Set();
                showToast('Hesabınız silindi. Görüşmek üzere.', 'info');
            } else {
                const d = await r.json().catch(() => ({}));
                if (errEl) { errEl.textContent = d.error || 'Bir hata oluştu.'; errEl.style.display = 'block'; }
                btn.disabled = false; btn.textContent = 'Evet, Hesabımı Sil';
            }
        } catch {
            if (errEl) { errEl.textContent = 'Bağlantı hatası.'; errEl.style.display = 'block'; }
            btn.disabled = false; btn.textContent = 'Evet, Hesabımı Sil';
        }
    });

    // ── Pricing modal ────────────────────────────────────────────────────
    const pricingModal = document.getElementById('pricingModal');
    function openPricingModal() { pricingModal.classList.remove('hidden'); }
    function closePricingModal() { pricingModal.classList.add('hidden'); }
    document.getElementById('pricingModalClose')?.addEventListener('click', closePricingModal);
    document.getElementById('pricingModalBackdrop')?.addEventListener('click', closePricingModal);

    window.openCheckout = async function(period) {
        if (!_currentUser) { openAuthModal('signup'); return; }
        try {
            const d = await fetch('/api/billing/checkout', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ period }),
            }).then(r => r.json());
            if (d.url) { window.location.href = d.url; }
            else { showToast('Ödeme sayfası açılamadı.', 'danger'); }
        } catch { showToast('Bağlantı hatası.', 'danger'); }
    };

    // Handle URL query params from email links
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('verify') === 'ok') {
        showToast('E-posta adresiniz doğrulandı!', 'success', 6000);
        history.replaceState({}, '', '/');
    } else if (urlParams.get('verify')) {
        showToast('Doğrulama bağlantısı geçersiz veya süresi dolmuş.', 'danger', 6000);
        history.replaceState({}, '', '/');
    } else if (urlParams.get('checkout') === 'success') {
        showToast('Premium aboneliğiniz aktif edildi!', 'success', 8000);
        history.replaceState({}, '', '/');
        Auth.me().then(d => { if (d.user) applyUserState(d.user); });
    } else if (urlParams.get('reset_token')) {
        _pendingResetToken = urlParams.get('reset_token');
        history.replaceState({}, '', '/');
        openAuthModal('reset');
    }

    // GA4 — dinamik yükleme (Railway'de GA_MEASUREMENT_ID set edilince otomatik aktif)
    fetch('/api/config').then(r => r.json()).then(cfg => {
        if (cfg.ga_measurement_id) {
            const s = document.createElement('script');
            s.async = true;
            s.src = `https://www.googletagmanager.com/gtag/js?id=${cfg.ga_measurement_id}`;
            document.head.appendChild(s);
            window.dataLayer = window.dataLayer || [];
            window.gtag = function(){ window.dataLayer.push(arguments); };
            window.gtag('js', new Date());
            window.gtag('config', cfg.ga_measurement_id);
        }
    }).catch(() => {});

    // ── Cookie banner ────────────────────────────────────────────────────
    if (!localStorage.getItem('nebula.cookieConsent')) {
        const banner = document.getElementById('cookieBanner');
        if (banner) banner.classList.remove('hidden');
        document.getElementById('cookieAccept')?.addEventListener('click', () => {
            localStorage.setItem('nebula.cookieConsent', '1');
            banner.classList.add('hidden');
        });
    }

    // ── Destek Chatbot ───────────────────────────────────────────────────
    (function initSupportChat() {
        const fab    = document.getElementById('supportFab');
        const chat   = document.getElementById('supportChat');
        const closeBtn = document.getElementById('supportClose');
        const messages = document.getElementById('supportMessages');
        const input  = document.getElementById('supportInput');
        const sendBtn = document.getElementById('supportSend');
        const escalate = document.getElementById('supportEscalate');
        if (!fab || !chat) return;

        let history = [];
        let isOpen = false;
        let isSending = false;

        function toggleChat() {
            isOpen = !isOpen;
            chat.classList.toggle('hidden', !isOpen);
            if (isOpen && messages.children.length === 0) {
                appendMessage('assistant', 'Merhaba! Size nasıl yardımcı olabilirim? Kayıt, tarama, alarmlar veya teknik bir sorun için buradayım.');
            }
            if (isOpen) input.focus();
        }

        function appendMessage(role, text) {
            const div = document.createElement('div');
            div.className = `support-msg support-msg-${role}`;
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        function appendTyping() {
            const div = document.createElement('div');
            div.className = 'support-msg support-msg-assistant support-typing';
            div.id = 'supportTyping';
            div.textContent = '...';
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        async function sendMessage() {
            const text = input.value.trim();
            if (!text || isSending) return;
            isSending = true;
            input.value = '';
            sendBtn.disabled = true;
            appendMessage('user', text);
            appendTyping();
            try {
                const res = await fetch('/api/support/chat', {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, history }),
                });
                document.getElementById('supportTyping')?.remove();
                const ct = res.headers.get('content-type') || '';
                if (!ct.includes('application/json')) throw new Error('server');
                const data = await res.json();
                const reply = data.reply || 'Şu an yanıt veremiyorum, lütfen daha sonra tekrar deneyin.';
                appendMessage('assistant', reply);
                history.push({ role: 'user', content: text });
                history.push({ role: 'assistant', content: reply });
                if (data.needs_escalation) {
                    escalate.classList.remove('hidden');
                }
            } catch {
                document.getElementById('supportTyping')?.remove();
                appendMessage('assistant', 'Bağlantı hatası. Lütfen daha sonra tekrar deneyin.');
                escalate.classList.remove('hidden');
            } finally {
                isSending = false;
                sendBtn.disabled = false;
                input.focus();
            }
        }

        fab.addEventListener('click', toggleChat);
        closeBtn.addEventListener('click', toggleChat);
        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    })();

})();
