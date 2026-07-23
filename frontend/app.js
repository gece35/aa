/* Nebula Scanner - frontend mantigi */
(function () {
    const API = {
        markets: () => fetch('/api/markets').then((r) => r.json()),
        index: (market) => fetch(`/api/index/${market}`).then((r) => r.json()),
        scanChunk: (market, offset, limit, force = false, sort = 'score') =>
            fetch(`/api/scan?market=${market}&offset=${offset}&limit=${limit}&force=${force ? 1 : 0}&sort=${sort}`).then((r) => r.json()),
        stock: (symbol) => fetch(`/api/stock/${encodeURIComponent(symbol)}`).then((r) => r.json()),
        stockNews: (symbol) => fetch(`/api/news/stock/${encodeURIComponent(symbol)}`).then((r) => r.json()),
        stockFundamentals: (symbol) => fetch(`/api/stock/${encodeURIComponent(symbol)}/fundamentals`).then((r) => r.json()),
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
        backtest: (market, force = false) => fetch(`/api/backtest?market=${market}&force=${force ? 1 : 0}`).then((r) => r.json()),
        signalStudy: (market, force = false) => fetch(`/api/signal-study?market=${market}&force=${force ? 1 : 0}`).then((r) => r.json()),
        commentsList: (symbol) => fetch(`/api/comments/${encodeURIComponent(symbol)}`).then((r) => r.json()),
        commentsAdd: (symbol, body) => fetch(`/api/comments/${encodeURIComponent(symbol)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body }) }).then((r) => r.json()),
        commentsDelete: (id) => fetch(`/api/comments/${id}`, { method: 'DELETE' }).then((r) => r.json()),
    };

    // ── Admin: Kullanıcı listesi modalı ──────────────────────────────────────
    let _adminUsersPage = 1;
    let _adminUsersQuery = '';

    function openAdminUsers(page, q) {
        page = page || 1;
        q = (q !== undefined) ? q : _adminUsersQuery;
        _adminUsersPage = page;
        _adminUsersQuery = q;

        const modal = document.getElementById('adminUsersModal');
        if (!modal) return;
        modal.classList.remove('hidden');

        const tbody = document.getElementById('adminUsersTbody');
        const empty = document.getElementById('adminUsersEmpty');
        const pager = document.getElementById('adminUsersPager');
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--text-3);">Yükleniyor…</td></tr>';
        empty.style.display = 'none';
        pager.innerHTML = '';

        const url = `/api/admin/users?page=${page}&q=${encodeURIComponent(q)}`;
        fetch(url).then(r => r.json()).then(data => {
            tbody.innerHTML = '';
            if (!data.users || data.users.length === 0) {
                tbody.innerHTML = '';
                empty.style.display = '';
                return;
            }
            data.users.forEach(u => {
                const planBadge = u.plan === 'premium'
                    ? '<span style="color:#a78bfa;font-weight:600;">Premium</span>'
                    : '<span style="color:var(--text-3);">Ücretsiz</span>';
                const adminBadge = u.is_admin ? ' <span style="background:#7c3aed;color:#fff;border-radius:4px;font-size:10px;padding:1px 5px;">Admin</span>' : '';
                const verifiedBadge = u.email_verified
                    ? '<span style="color:#4ade80;">&#10003;</span>'
                    : '<span style="color:var(--danger);">&#10007;</span>';
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid var(--glass-brd)';
                tr.innerHTML = `
                    <td style="padding:7px 8px;"></td>
                    <td style="text-align:center;padding:7px 8px;">${planBadge}</td>
                    <td style="text-align:center;padding:7px 8px;color:var(--text-2);font-size:12px;">${u.subscription_status}</td>
                    <td style="text-align:center;padding:7px 8px;">${verifiedBadge}</td>
                    <td style="text-align:center;padding:7px 8px;color:var(--text-3);font-size:12px;">${u.created_at}</td>
                    <td style="text-align:center;padding:7px 8px;color:var(--text-3);font-size:12px;">${u.last_login_at}</td>
                `;
                // Email textContent ile set et (XSS önlemi)
                const emailTd = tr.querySelector('td:first-child');
                emailTd.textContent = u.email;
                if (u.is_admin) emailTd.insertAdjacentHTML('beforeend', adminBadge);
                tbody.appendChild(tr);
            });

            // Sayfalandırma
            const prevDisabled = page <= 1;
            const nextDisabled = page >= data.pages;
            pager.innerHTML = `
                <span>${data.total} kullanıcı &bull; Sayfa ${data.page}/${data.pages || 1}</span>
                <div style="display:flex;gap:6px;">
                    <button class="btn btn-ghost" style="font-size:12px;padding:3px 10px;" ${prevDisabled ? 'disabled' : ''} id="adminPagePrev">&#8592; Önceki</button>
                    <button class="btn btn-ghost" style="font-size:12px;padding:3px 10px;" ${nextDisabled ? 'disabled' : ''} id="adminPageNext">Sonraki &#8594;</button>
                </div>
            `;
            if (!prevDisabled) {
                document.getElementById('adminPagePrev').addEventListener('click', () => openAdminUsers(page - 1));
            }
            if (!nextDisabled) {
                document.getElementById('adminPageNext').addEventListener('click', () => openAdminUsers(page + 1));
            }
        }).catch(() => {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--danger);">Veriler yüklenemedi.</td></tr>';
        });

        // Kapat
        document.getElementById('adminUsersClose').onclick = () => modal.classList.add('hidden');
        document.getElementById('adminUsersBackdrop').onclick = () => modal.classList.add('hidden');

        // Arama
        const searchBtn = document.getElementById('adminUsersSearchBtn');
        const searchInput = document.getElementById('adminUsersSearch');
        if (searchInput) searchInput.value = q;
        if (searchBtn) {
            searchBtn.onclick = () => openAdminUsers(1, (searchInput ? searchInput.value.trim() : ''));
        }
        if (searchInput) {
            searchInput.onkeydown = (e) => { if (e.key === 'Enter') openAdminUsers(1, searchInput.value.trim()); };
        }
    }
    // ─────────────────────────────────────────────────────────────────────────

    const WATCHLIST_KEY = 'nebula.watchlist.v1';
    const MARKET_KEY = 'nebula.market.v1';
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
        market: localStorage.getItem(MARKET_KEY) || 'bist',
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
        marketTickerCount: {},
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
                API.watchlistAdd(symbol).then(d => {
                    if (d && d.error === 'email_not_verified') {
                        state.watchlist.delete(symbol);
                        showToast('İzleme listesini kullanmak için önce e-posta adresinizi doğrulayın.', 'warning');
                    } else if (d && d.error) {
                        state.watchlist.delete(symbol);
                    }
                }).catch(() => state.watchlist.delete(symbol));
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
            state.marketTickerCount[m.code] = m.ticker_count;
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
                try { localStorage.setItem(MARKET_KEY, m.code); } catch (_) {}
                updateCurrencyToggle();
                if (m.code === 'bist') fetchExchangeRate();
                loadScan();
            });
            els.marketButtons.appendChild(btn);
            if (m.code === state.market) state.currency = m.currency;
        });
    }

    // --- endeks mini grafikleri (BIST 100 / S&P 500) ---
    function renderIndexCard(market, d) {
        const priceEl  = document.getElementById(`indexPrice-${market}`);
        const chEl     = document.getElementById(`indexChange-${market}`);
        const regimeEl = document.getElementById(`indexRegime-${market}`);
        const canvas   = document.getElementById(`indexSpark-${market}`);
        if (!priceEl) return;

        if (!d || d.error) {
            priceEl.textContent = '-';
            if (chEl) chEl.textContent = '';
            if (regimeEl) regimeEl.textContent = '';
            return;
        }

        const isUp = (d.change_pct || 0) >= 0;
        priceEl.textContent = d.price != null
            ? d.price.toLocaleString('tr-TR', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
            : '-';
        if (chEl) {
            chEl.textContent = fmtChange(d.change_pct);
            chEl.className = 'index-change ' + (isUp ? 'up' : 'down');
        }
        if (regimeEl) {
            regimeEl.textContent = d.regime_ok ? '🟢 Rejim Olumlu' : '🔴 Rejim Zayıf';
            regimeEl.title = d.regime_ok
                ? 'Endeks 200 günlük ortalamanın üzerinde — TDOV Eşleşti rozeti gösterilebilir.'
                : 'Endeks 200 günlük ortalamanın altında — bu piyasada hiçbir hissede TDOV Eşleşti rozeti gösterilmez.';
            regimeEl.className = 'index-regime ' + (d.regime_ok ? 'regime-ok' : 'regime-bad');
        }
        if (canvas) drawSparkline(canvas, d.sparkline || [], isUp);
    }

    async function loadIndices() {
        ['bist', 'us'].forEach(async (market) => {
            try {
                const d = await API.index(market);
                renderIndexCard(market, d);
            } catch (_) {
                renderIndexCard(market, null);
            }
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
        els.resultsArea.querySelectorAll('.stock-card, .empty, .loader-sentinel, .plan-gate-banner, .guest-teaser-banner').forEach((x) => x.remove());

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
            m.fullTotal = data.full_total || m.fullTotal || m.total;
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
        els.statTotal.textContent = state.marketTickerCount[state.market] || m.total || '-';
        els.statScored.textContent = m.results.length || '-';
        const avg = m.results.length ? (m.results.reduce((s, r) => s + r.score, 0) / m.results.length) : 0;
        els.statAvg.textContent = avg ? avg.toFixed(2) : '-';
        els.statPerfect.textContent = m.results.filter((r) => r.score >= 9).length;
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

        els.resultsArea.querySelectorAll('.stock-card, .empty, .loader-sentinel, .plan-gate-banner, .guest-teaser-banner').forEach((x) => x.remove());

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
                if (!_currentUser && idx === 4 && filtered.length > 5) {
                    const remaining = (state.marketTickerCount[state.market] || m.fullTotal || m.total || filtered.length) - 5;
                    const teaser = document.createElement('div');
                    teaser.className = 'guest-teaser-banner';
                    teaser.innerHTML = `
                        <span class="teaser-lock">🔒</span>
                        <span class="teaser-msg">Geri kalan <strong>${remaining} hisseyi</strong> görmek için</span>
                        <button class="teaser-cta" onclick="openAuthModal('signup')">Ücretsiz Üye Ol →</button>
                    `;
                    frag.appendChild(teaser);
                }
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
        const isGuestLocked = !_currentUser && idx >= 5;
        const card = document.createElement('div');
        card.className = 'stock-card glass' + (isGuestLocked ? ' guest-locked' : '') + (r.entry_signal ? ' has-entry-signal' : '');
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
        const entryBadge = r.entry_signal
            ? `<span class="badge entry-signal" title="Bu hisse TDOV'un geçmiş test verisinde gözlemlenen koşul setiyle eşleşiyor: taze kesişim + trend onayı + yeterli hacim + 52 haftalık zirveye yakınlık (bkz. Rehber → Basit Anlatım). Bu bir alım tavsiyesi değildir, yalnızca geçmiş veri modeline dayalı bir eşleşme bilgisidir.">&#127919; TDOV Eşleşti</span>`
            : '';
        const reason = buildScoreReason(r);

        const chartBtnHtml = r.score >= 3
            ? `<button class="scan-chart-btn btn btn-sm" data-sym="${r.symbol}" title="Candlestick grafik ve formasyon analizi">&#128202; Grafik</button>`
            : '';

        card.innerHTML = `
            <div class="card-content-inner">
            <button class="star-toggle ${isWatched ? 'active' : ''}" data-sym="${r.symbol}" title="${isWatched ? 'Favorilerden çıkar' : 'Favorilere ekle'}">&#9733;</button>
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
                ${entryBadge}
                ${r.indicators.map((ind) => {
                    const cls = ind.score > 0 ? 'on' : (ind.score < 0 ? 'penalty' : '');
                    const sign = ind.score > 0 ? '+' : '';
                    const scoreLabel = ind.max_score > 0 ? ` ${sign}${ind.score}` : '';
                    return `<span class="badge ${cls}" title="${escapeAttr(ind.detail || '')}">${escapeHtml(ind.name)}${scoreLabel}</span>`;
                }).join('')}
                ${spikeBadge}${nearPeakBadge}
            </div>
            <div class="score-chip" data-score="${r.score}">
                <span class="star">&#9733;</span> ${r.score}/10
            </div>
            ${reason ? `<div class="score-reason">${escapeHtml(reason)}</div>` : ''}
            ${chartBtnHtml}
            </div>
        `;

        if (isGuestLocked) {
            const overlay = document.createElement('div');
            overlay.className = 'guest-lock-overlay';
            overlay.innerHTML = `
                <span class="lock-icon">🔒</span>
                <span class="lock-msg">Tüm sonuçları görmek için<br>ücretsiz üye olun</span>
                <button class="lock-cta">Üye Ol →</button>
            `;
            overlay.querySelector('.lock-cta').addEventListener('click', () => openAuthModal('signup'));
            card.appendChild(overlay);
            return card;
        }

        card.addEventListener('click', (e) => {
            if (e.target.closest('.star-toggle') || e.target.closest('.scan-chart-btn')) return;
            openStockModal(r.symbol);
        });

        const starBtn = card.querySelector('.star-toggle');
        starBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleWatch(r.symbol);
            const nowWatched = state.watchlist.has(r.symbol);
            starBtn.classList.toggle('active', nowWatched);
            starBtn.title = nowWatched ? 'Favorilerden çıkar' : 'Favorilere ekle';
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

    // Normalize oran ≥ 0.5 ise aktif sayılır.
    const REASON_PHRASE = {
        trend:     'EMA\'lar tam hizalı — güçlü trend yapısı',
        momentum:  'MACD sinyal üstünde ve pozitif bölgede',
        rsi:       'RSI sağlıklı momentum bölgesinde',
        bbands:    'Bollinger alt band bölgesinde — giriş fırsatı',
        macd_zero: 'MACD histogramı pozitif ve yükselen momentum',
        adx:       'ADX güçlü trend teyidi veriyor',
        volume:    'hacim ortalamanın belirgin üzerinde',
    };

    function buildScoreReason(r) {
        if (!r || !r.indicators) return '';
        const byKey = {};
        r.indicators.forEach((ind) => { byKey[ind.key] = ind; });

        // Aktif kesişim sinyalleri: normalize oran ≥ 0.5
        const positives = r.indicators
            .filter((ind) => ind.max_score > 0 && REASON_PHRASE[ind.key]
                && (ind.score / ind.max_score) >= 0.5)
            .sort((a, b) => (b.score / b.max_score) - (a.score / a.max_score))
            .map((ind) => REASON_PHRASE[ind.key]);

        // Uyarılar
        const warnings = [];
        const rsi = byKey['rsi'];
        if (rsi && rsi.value != null && rsi.value > 70) warnings.push('dikkat: RSI aşırı alım bölgesinde');
        const ext = byKey['extension'];
        if (ext && ext.score != null && ext.score < -1.5) warnings.push('dikkat: fiyat 52-haftalık zirvede — geri çekilme riski yüksek');
        else if (ext && ext.score != null && ext.score < -0.5) warnings.push('dikkat: fiyat uzamış / 52-haftalık zirveye yakın');
        if (r.near_peak) warnings.push('dikkat: zirveye yakın');

        const parts = positives.concat(warnings);
        if (!parts.length) return r.score === 0 ? 'Aktif kesişim sinyali bulunmuyor.' : '';
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
            wireDetailTabs(data);
            wireFundamentalsTab(data.symbol);
            wireModalWatchToggle(data.symbol);
            wireModalShare(data.symbol, data.score);
            wireModalPortfolioForm(data);
            loadAndWireComments(data.symbol);
        } catch (err) {
            els.modalContent.innerHTML = `<div class="empty">Detay yuklenemedi: ${err.message}</div>`;
        }
    }

    function wireModalWatchToggle(symbol) {
        const btn = document.getElementById('modalStar');
        if (!btn) return;
        btn.addEventListener('click', () => {
            toggleWatch(symbol);
            const nowWatched = state.watchlist.has(symbol);
            btn.classList.toggle('active', nowWatched);
            btn.title = nowWatched ? 'Favorilerden çıkar' : 'Favorilere ekle';
            renderResults();
        });
    }

    function wireModalShare(symbol, score) {
        const btn = document.getElementById('modalShare');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const display = symbol.replace('.IS', '');
            const text = `${display} şu an Nebula Scanner'da ${score}/10 puan aldı 🌌`;
            const url = `${location.origin}/?s=${encodeURIComponent(symbol)}`;
            const fullText = `${text}\n${url}`;
            if (navigator.share) {
                navigator.share({ title: `${display} — Nebula Scanner`, text, url }).catch(() => {});
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(fullText).then(() => {
                    btn.textContent = '✓ Kopyalandı';
                    setTimeout(() => { btn.textContent = '🔗 Paylaş'; }, 2000);
                });
            } else {
                const ta = document.createElement('textarea');
                ta.value = fullText;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                btn.textContent = '✓ Kopyalandı';
                setTimeout(() => { btn.textContent = '🔗 Paylaş'; }, 2000);
            }
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
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:10px;">Kritik Destek / Direnç Hedefi</div>
                <div class="sl-tp-box">
                    ${sl ? `<div class="sl-tp-item stop-loss">
                        <span class="sl-tp-label">Kritik Destek</span>
                        <span class="sl-tp-value">${fmtPrice(sl, ccy)}</span>
                        <span class="sl-tp-pct">${slPct}%</span>
                    </div>` : ''}
                    ${tp ? `<div class="sl-tp-item take-profit">
                        <span class="sl-tp-label">Direnç</span>
                        <span class="sl-tp-value">${fmtPrice(tp, ccy)}</span>
                        <span class="sl-tp-pct">+${tpPct}%</span>
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
                    <h2 style="margin:0;font-family:'Outfit';font-size:28px;">${escapeHtml(display)}</h2>
                    <div style="color:var(--text-3);font-size:12px;letter-spacing:1px;text-transform:uppercase;">${escapeHtml(d.symbol)}</div>
                </div>
                <button id="modalStar" class="star-toggle ${isWatched ? 'active' : ''}" style="position:static;font-size:22px;" title="${isWatched ? 'Favorilerden çıkar' : 'Favorilere ekle'}">&#9733;</button>
                <button id="modalShare" class="btn btn-ghost" style="font-size:13px;padding:6px 12px;" title="Paylaş">🔗 Paylaş</button>
                <div style="margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    ${spikeHtml}${nearPeakHtml}
                    <div class="score-chip" data-score="${d.score}"><span class="star">&#9733;</span> ${d.score}/10</div>
                </div>
            </div>
            ${reason ? `<div style="margin-top:12px;padding:10px 14px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid var(--glass-brd-soft);font-size:13px;color:var(--text-2);line-height:1.6;">${escapeHtml(reason)}</div>` : ''}

            <!-- Sekme çubuğu -->
            <div style="display:flex;gap:0;margin-top:18px;border-bottom:1px solid var(--glass-brd);">
                <button class="detail-modal-tab active" data-dtab="ozet" style="padding:8px 18px;font-size:13px;font-weight:500;background:none;border:none;border-bottom:2px solid var(--accent);color:var(--text-1);cursor:pointer;">Özet</button>
                <button class="detail-modal-tab" data-dtab="bilanco" style="padding:8px 18px;font-size:13px;font-weight:500;background:none;border:none;border-bottom:2px solid transparent;color:var(--text-3);cursor:pointer;">Bilanço Analizi</button>
                <button class="detail-modal-tab" data-dtab="haberler" style="padding:8px 18px;font-size:13px;font-weight:500;background:none;border:none;border-bottom:2px solid transparent;color:var(--text-3);cursor:pointer;">Haberler</button>
            </div>

            <!-- ÖZET paneli -->
            <div id="dtab-ozet" class="dtab-panel" style="padding-top:14px;">
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
                    ${d.indicators.map((ind) => {
                        const cls = ind.score > 0 ? 'on' : (ind.score < 0 ? 'penalty' : '');
                        const sign = ind.score > 0 ? '+' : '';
                        const scoreLabel = ind.max_score > 0
                            ? `${sign}${ind.score} / ${ind.max_score}`
                            : (ind.score < 0 ? `${ind.score}` : '—');
                        return `
                        <div class="detail-ind">
                            <div class="di-head">
                                <span class="di-name">${escapeHtml(ind.name)} ${ind.value != null ? `<span style="color:var(--text-3);font-weight:500">(${ind.value})</span>` : ''}</span>
                                <span class="badge ${cls}">${scoreLabel}</span>
                            </div>
                            <div class="di-reason">${escapeHtml(ind.detail || '')}</div>
                        </div>`;
                    }).join('')}
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
            </div>

            <!-- BİLANÇO ANALİZİ paneli -->
            <div id="dtab-bilanco" class="dtab-panel" style="display:none;padding-top:14px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:6px;">Yapay Zeka Bilanço Analizi</div>
                <div style="font-size:12px;color:var(--text-3);line-height:1.5;margin-bottom:14px;">
                    Hissenin son bilanço ve gelir tablosu verileri yapay zeka ile değerlendirilir ve
                    finansal sağlık <b>pozitif / nötr / negatif</b> olarak sınıflandırılır.
                </div>
                <button id="fundAnalyzeBtn" class="btn btn-primary" style="font-size:13px;padding:8px 18px;">&#129504; Analiz Et</button>
                <div id="fundResult" style="margin-top:16px;"></div>
                <div style="margin-top:16px;font-size:11px;color:var(--text-3);line-height:1.5;">
                    &#9888; Bu analiz eğitim amaçlıdır ve yatırım tavsiyesi değildir.
                </div>
            </div>

            <!-- HABERLER paneli -->
            <div id="dtab-haberler" class="dtab-panel" style="display:none;padding-top:14px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:10px;">Son Haberler</div>
                <div class="stock-news-list">${newsItems}</div>
                <div id="commentsSection" style="margin-top:28px;">
                    <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:12px;">Topluluk Yorumlar&#305;</div>
                    <div class="comment-form">
                        <textarea id="commentInput" class="comment-textarea" maxlength="500" placeholder="Bu hisse hakk&#305;nda d&#252;&#351;&#252;ncelerinizi payla&#351;&#305;n... (maks. 500 karakter)"></textarea>
                        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:6px;">
                            <span id="commentCharCount" style="font-size:11px;color:var(--text-3);align-self:center;">0/500</span>
                            <button class="btn btn-primary" id="commentSubmitBtn" style="font-size:13px;padding:6px 16px;">Yorum Yap</button>
                        </div>
                    </div>
                    <div id="commentsList" style="margin-top:12px;">
                        <div class="empty" style="font-size:13px;">Yorumlar y&#252;kleniyor...</div>
                    </div>
                </div>
            </div>
        `;
    }

    // --- Detail modal sekme yönetimi ---
    function wireDetailTabs(data) {
        const tabs = document.querySelectorAll('.detail-modal-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const target = tab.dataset.dtab;
                tabs.forEach(t => {
                    const isActive = t.dataset.dtab === target;
                    t.style.color = isActive ? 'var(--text-1)' : 'var(--text-3)';
                    t.style.borderBottom = isActive ? '2px solid var(--accent)' : '2px solid transparent';
                    t.classList.toggle('active', isActive);
                });
                document.querySelectorAll('.dtab-panel').forEach(p => {
                    p.style.display = p.id === `dtab-${target}` ? '' : 'none';
                });
            });
        });
    }

    // --- Bilanço analizi sekmesi ---
    function wireFundamentalsTab(symbol) {
        const btn = document.getElementById('fundAnalyzeBtn');
        const result = document.getElementById('fundResult');
        if (!btn || !result) return;
        let loaded = false;
        btn.addEventListener('click', async () => {
            if (loaded) return;
            btn.disabled = true;
            const original = btn.innerHTML;
            btn.innerHTML = 'Analiz ediliyor...';
            result.innerHTML = '<div class="empty" style="font-size:13px;">Bilanço yapay zeka ile analiz ediliyor, bu birkaç saniye sürebilir...</div>';
            try {
                const data = await API.stockFundamentals(symbol);
                if (data.error === 'config_error') {
                    result.innerHTML = '<div class="empty" style="font-size:13px;">Bilanço analizi servisi şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin.</div>';
                    btn.innerHTML = original; btn.disabled = false;
                    return;
                }
                if (!data.available) {
                    result.innerHTML = '<div class="empty" style="font-size:13px;">Bu hisse için bilanço verisi bulunamadı. (BIST hisselerinde temel veri çoğu zaman eksik olabilir.)</div>';
                    btn.innerHTML = original; btn.disabled = false;
                    return;
                }
                result.innerHTML = renderFundamentals(data);
                loaded = true;
                btn.style.display = 'none';
            } catch (err) {
                result.innerHTML = `<div class="empty" style="font-size:13px;">Analiz yapılamadı: ${escapeHtml(err.message)}</div>`;
                btn.innerHTML = original; btn.disabled = false;
            }
        });
    }

    function renderFundamentals(d) {
        const verdictMap = {
            positive: { label: 'Pozitif', color: 'var(--neon)', icon: '&#9650;' },
            neutral:  { label: 'Nötr',    color: 'var(--text-3)', icon: '&#9644;' },
            negative: { label: 'Negatif', color: 'var(--danger)', icon: '&#9660;' },
        };
        const v = verdictMap[d.verdict] || verdictMap.neutral;
        const m = d.metrics || {};

        const fmtMoney = (val) => {
            if (val == null) return '—';
            const abs = Math.abs(val);
            if (abs >= 1e9) return (val / 1e9).toFixed(2) + ' Mlr';
            if (abs >= 1e6) return (val / 1e6).toFixed(2) + ' Mn';
            return val.toFixed(2);
        };
        const fmtRatio = (val) => (val == null ? '—' : val.toFixed(2));
        const fmtPct = (val) => {
            if (val == null) return '—';
            const sign = val >= 0 ? '+' : '';
            const color = val >= 0 ? 'var(--neon)' : 'var(--danger)';
            return `<span style="color:${color}">${sign}${val.toFixed(1)}%</span>`;
        };

        const rows = [
            ['Hasılat', fmtMoney(m.revenue)],
            ['Net Kar', fmtMoney(m.net_income)],
            ['Özkaynak', fmtMoney(m.equity)],
            ['Toplam Borç', fmtMoney(m.total_debt)],
            ['Borç / Özkaynak', fmtRatio(m.debt_to_equity)],
            ['Cari Oran', fmtRatio(m.current_ratio)],
            ['Net Kar Marjı', m.net_margin_pct == null ? '—' : fmtPct(m.net_margin_pct)],
            ['Hasılat (YoY)', fmtPct(m.revenue_yoy_pct)],
            ['Net Kar (YoY)', fmtPct(m.net_income_yoy_pct)],
        ];

        const listHtml = (items, color) => (items && items.length)
            ? `<ul style="margin:6px 0 0;padding-left:18px;color:var(--text-2);font-size:13px;line-height:1.7;">${items.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul>`
            : '';

        return `
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
                <span style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;font-weight:700;font-size:14px;color:${v.color};border:1.5px solid ${v.color};">${v.icon} ${v.label}</span>
                ${m.period ? `<span style="font-size:11px;color:var(--text-3);">Dönem: ${escapeHtml(m.period)}</span>` : ''}
            </div>
            ${d.summary ? `<div style="padding:12px 14px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid var(--glass-brd-soft);font-size:13px;color:var(--text-2);line-height:1.6;">${escapeHtml(d.summary)}</div>` : ''}
            <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;">
                ${(d.strengths && d.strengths.length) ? `<div style="flex:1;min-width:160px;">
                    <div style="font-size:10px;color:var(--neon);letter-spacing:1.5px;text-transform:uppercase;font-weight:700;">Güçlü Yönler</div>
                    ${listHtml(d.strengths)}
                </div>` : ''}
                ${(d.risks && d.risks.length) ? `<div style="flex:1;min-width:160px;">
                    <div style="font-size:10px;color:var(--danger);letter-spacing:1.5px;text-transform:uppercase;font-weight:700;">Riskler</div>
                    ${listHtml(d.risks)}
                </div>` : ''}
            </div>
            <div style="margin-top:18px;">
                <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-3);margin-bottom:8px;">Temel Metrikler</div>
                ${rows.map(([k, val]) => `<div class="detail-row"><span class="k">${k}</span><span>${val}</span></div>`).join('')}
            </div>
        `;
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
        if (!confirm('Bu pozisyonu portföyden kaldırmak istiyor musunuz?')) return;
        port.positions = port.positions.filter(p => String(p.id) !== String(id));
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

        // ── Yüksek Risk ───────────────────────────────────────────────────
        if (sl && price <= sl) {
            reasons.push('Kritik destek kırıldı');
            if (weekPct < -5) reasons.push(`Bu hafta %${Math.abs(weekPct).toFixed(1)} düşüş`);
            return { level: 'sat_hemen', label: 'Yüksek Risk', reasons };
        }
        if (pnlPct < -15 && score <= 2 && trend === 'down') {
            reasons.push(`%${Math.abs(pnlPct).toFixed(1)} zarar, trend sağlığı zayıf`);
            reasons.push('Düşüş trendi devam ediyor');
            return { level: 'sat_hemen', label: 'Yüksek Risk', reasons };
        }

        // ── Direnç Bölgesinde ─────────────────────────────────────────────
        if (tp && price >= tp * 0.98 && pnlPct > 3) {
            reasons.push('Direnç bölgesine ulaşıldı');
            if (d.near_peak) reasons.push('52 haftalık zirveye çok yakın');
            return { level: 'kar_al', label: 'Direnç Bölgesinde', reasons };
        }
        if (d.near_peak && pnlPct > 15) {
            reasons.push(`%${pnlPct.toFixed(1)} kar, zirve bölgesinde`);
            reasons.push('Direnç seviyesi yakınında');
            return { level: 'kar_al', label: 'Direnç Bölgesinde', reasons };
        }
        if (pnlPct > 30 && score <= 3) {
            reasons.push(`%${pnlPct.toFixed(1)} kar mevcut`);
            reasons.push('Trend sağlığı zayıfladı');
            return { level: 'kar_al', label: 'Direnç Bölgesinde', reasons };
        }

        // ── Zayıflama Sinyalleri ──────────────────────────────────────────
        let bearish = 0;
        if (sl && price < sl * 1.035 && pnlPct < -2) { reasons.push("Kritik desteğe %3'ten az mesafe kaldı"); bearish += 2; }
        if (pnlPct < -10 && trend === 'down') {
            reasons.push(`%${Math.abs(pnlPct).toFixed(1)} zararda ve düşüş trendi`);
            bearish += 2;
        }
        if (score <= 3 && weekPct < -3) { reasons.push(`${score}/10 sağlık, haftalık %${weekPct.toFixed(1)}`); bearish++; }
        if (pnlPct > 18 && score <= 1) { reasons.push(`%${pnlPct.toFixed(1)} kar var ama trend bozuldu`); bearish += 2; }
        if (wedge === 'rising' && score <= 4) { reasons.push('Yükselen kama kırılım riski'); bearish++; }
        if (trend === 'down' && score <= 2 && pnlPct < 0) { reasons.push('Düşüş trendi + zararda pozisyon'); bearish++; }
        const bearishThreshold = score >= 6 ? 3 : 2;
        if (bearish >= bearishThreshold) return { level: 'sat_dusun', label: 'Zayıflama Belirtileri', reasons: reasons.slice(0, 3) };

        // ── Trend Sağlıklı ────────────────────────────────────────────────
        let bullish = 0;
        const bullReasons = [];
        if (score >= 8) { bullReasons.push(`${score}/10 güçlü trend sağlığı`); bullish += 2; }
        else if (score >= 6) { bullReasons.push(`${score}/10 sağlıklı trend seviyesi`); bullish++; }
        if (trend === 'up') { bullReasons.push('Yukarı trend devam ediyor'); bullish++; }
        if (d.volume_spike) { bullReasons.push('Hacim ortalamanın üzerinde'); bullish++; }
        if (wedge === 'falling') { bullReasons.push('Düşen kama — yukarı kırılım potansiyeli'); bullish++; }
        if (weekPct > 3 && score >= 4) { bullReasons.push(`Haftalık +%${weekPct.toFixed(1)} pozitif ivme`); bullish++; }
        if (bullish >= 3) return { level: 'tut', label: 'Trend Sağlıklı', reasons: bullReasons.slice(0, 3) };

        // ── İzlemede ──────────────────────────────────────────────────────
        const watchReasons = [];
        if (score >= 4) watchReasons.push(`${score}/10 sağlık, gelişim bekleniyor`);
        if (Math.abs(weekPct) <= 2) watchReasons.push('Yatay seyir, net yön bekleniyor');
        else if (weekPct > 0) watchReasons.push(`Haftalık +%${weekPct.toFixed(1)} pozitif seyir`);
        if (wedge) watchReasons.push(wedge === 'rising' ? 'Yükselen kama: kırılımı izle' : 'Düşen kama: yukarı kırılım beklentisi');
        if (!watchReasons.length) watchReasons.push('Karma göstergeler, izlemede');
        return { level: 'izle', label: 'İzlemede', reasons: watchReasons.slice(0, 2) };
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

    // ── Backtest UI ───────────────────────────────────────────────────────────
    const _btState = { market: 'bist', data: null, loading: false, expanded: new Set(),
                       study: null, studyLoading: false };

    function renderBacktestTab() {
        const el = document.getElementById('backtestContent');
        if (!el) return;

        const marketBtns = ['bist', 'us'].map(m => `
            <button class="bt-market-btn ${_btState.market === m ? 'active' : ''}" data-market="${m}">
                ${m === 'bist' ? '🇹🇷 BIST' : '🇺🇸 US'}
            </button>`).join('');

        el.innerHTML = `
            <div class="bt-toolbar glass">
                <div class="bt-market-group">${marketBtns}</div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <button id="btRunBtn" class="btn btn-primary" ${_btState.loading ? 'disabled' : ''}>
                        ${_btState.loading ? '<span class="bt-spinner"></span> Hesaplanıyor...' : '▶ Çalıştır'}
                    </button>
                    <button id="btForceBtn" class="btn btn-ghost" title="Cache'i temizle ve yeniden çalıştır" ${_btState.loading ? 'disabled' : ''}>
                        ↺ Yenile
                    </button>
                    <button id="btStudyBtn" class="btn btn-ghost" title="Kesişim sinyallerinin tarihsel ileri getiri etüdü" ${_btState.studyLoading ? 'disabled' : ''}>
                        ${_btState.studyLoading ? '<span class="bt-spinner"></span> Etüt…' : '🔬 Sinyal Etüdü'}
                    </button>
                </div>
            </div>
            <div id="btStudyResults"></div>
            <div id="btResults"></div>`;

        el.querySelectorAll('.bt-market-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                _btState.market = btn.dataset.market;
                _btState.data = null;
                _btState.study = null;
                _btState.expanded = new Set();
                renderBacktestTab();
            });
        });

        document.getElementById('btRunBtn')?.addEventListener('click', () => runBacktest(false));
        document.getElementById('btForceBtn')?.addEventListener('click', () => runBacktest(true));
        document.getElementById('btStudyBtn')?.addEventListener('click', () => runSignalStudy(false));

        if (_btState.study) renderSignalStudy(_btState.study);
        if (_btState.data) renderBacktestResults(_btState.data);
        else {
            document.getElementById('btResults').innerHTML = `
                <div class="bt-empty glass">
                    <div style="font-size:36px;margin-bottom:12px;">📊</div>
                    <div style="font-size:15px;font-weight:600;margin-bottom:6px;">Backtest henüz çalıştırılmadı</div>
                    <div style="font-size:13px;color:var(--text-3)">Market seçip "Çalıştır" butonuna tıklayın. İlk çalıştırma 1-2 dakika sürebilir.</div>
                </div>`;
        }
    }

    async function runBacktest(force) {
        if (_btState.loading) return;
        _btState.loading = true;
        _btState.data = null;
        renderBacktestTab();
        document.getElementById('btResults').innerHTML = `
            <div class="bt-empty glass">
                <div class="bt-spinner-lg"></div>
                <div style="font-size:14px;margin-top:16px;color:var(--text-2)">
                    Tüm hisseler analiz ediliyor, lütfen bekleyin…
                </div>
            </div>`;
        try {
            const data = await API.backtest(_btState.market, force);
            _btState.data = data;
        } catch (e) {
            _btState.data = { hata: 'Bağlantı hatası' };
        }
        _btState.loading = false;
        renderBacktestTab();
    }

    async function runSignalStudy(force) {
        if (_btState.studyLoading) return;
        _btState.studyLoading = true;
        renderBacktestTab();
        const box = document.getElementById('btStudyResults');
        if (box) box.innerHTML = `
            <div class="bt-empty glass">
                <div class="bt-spinner-lg"></div>
                <div style="font-size:14px;margin-top:16px;color:var(--text-2)">
                    Kesişim sinyalleri taranıyor…
                </div>
            </div>`;
        try {
            _btState.study = await API.signalStudy(_btState.market, force);
        } catch (e) {
            _btState.study = { hata: 'Bağlantı hatası' };
        }
        _btState.studyLoading = false;
        renderBacktestTab();
    }

    function renderSignalStudy(data) {
        const el = document.getElementById('btStudyResults');
        if (!el || !data) return;
        if (data.hata) {
            el.innerHTML = `<div class="bt-empty glass" style="color:var(--danger)">⚠ ${escapeHtml(data.hata)}</div>`;
            return;
        }
        const o = data.ozet || {};
        const rows = (data.tetikleyiciler || []).map(t => {
            const hit = t.isabet_pct_10g;
            const hitColor = hit == null ? 'var(--text-3)' : (hit >= 50 ? 'var(--neon)' : 'var(--warn)');
            const fmt = (v) => (v == null ? '-' : (v >= 0 ? '+' : '') + v + '%');
            const col = (v) => (v == null ? 'var(--text-3)' : (v >= 0 ? 'var(--neon)' : 'var(--danger)'));
            return `
                <tr>
                    <td class="bt-symbol">${escapeHtml(t.ad || t.key)}</td>
                    <td class="num">${t.olay_sayisi ?? 0}</td>
                    <td class="num" style="color:${hitColor}">${hit != null ? hit + '%' : '-'}</td>
                    <td class="num" style="color:${col(t.ort_getiri_pct_5g)}">${fmt(t.ort_getiri_pct_5g)}</td>
                    <td class="num" style="color:${col(t.ort_getiri_pct_10g)}">${fmt(t.ort_getiri_pct_10g)}</td>
                    <td class="num" style="color:${col(t.ort_getiri_pct_20g)}">${fmt(t.ort_getiri_pct_20g)}</td>
                    <td class="num">${t.profit_factor_10g ?? '-'}</td>
                </tr>`;
        }).join('');

        el.innerHTML = `
            <div class="bt-table-wrap glass" style="margin-bottom:16px;">
                <div class="bt-exits-title" style="padding:12px 14px 4px;">🔬 Sinyal İsabet Etüdü</div>
                <div style="padding:0 14px 8px;font-size:12px;color:var(--text-3);">
                    ${escapeHtml(data.aciklama || '')}
                    ${o.toplam_olay != null ? ` — Toplam <strong>${o.toplam_olay}</strong> olay, ${o.test_edilen_hisse ?? '-'} hisse${o.isabet_pct_10g != null ? `, genel 10g isabet <strong>${o.isabet_pct_10g}%</strong>` : ''}.` : ''}
                </div>
                <table class="bt-table">
                    <thead>
                        <tr>
                            <th>Tetikleyici Kesişim (trend onaylı)</th>
                            <th class="num">Olay</th>
                            <th class="num">İsabet (10g)</th>
                            <th class="num">Ort. 5g</th>
                            <th class="num">Ort. 10g</th>
                            <th class="num">Ort. 20g</th>
                            <th class="num">PF (10g)</th>
                        </tr>
                    </thead>
                    <tbody>${rows || `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-3)">Olay bulunamadı.</td></tr>`}</tbody>
                </table>
            </div>`;
    }

    function renderBacktestResults(data) {
        const el = document.getElementById('btResults');
        if (!el) return;
        if (data.hata) {
            el.innerHTML = `<div class="bt-empty glass" style="color:var(--danger)">⚠ ${escapeHtml(data.hata)}</div>`;
            return;
        }
        const o = data.ozet || {};
        const params = data.parametreler || {};
        const stocks = data.hisseler || [];

        const exitDist = o.cikis_dagilimlari || {};
        const exitLabels = {
            trailing_stop: 'Trailing Stop (güvenlik ağı)',
            sinyal_kirilim: 'Sinyal Kırılımı',
            kismi_tp: 'Kısmi TP',
            score_3bar: 'Skor (3 gün)',
            score_crash: 'Skor Crash',
            dead_money: 'Dead Money',
            time_exit: 'Süre Doldu',
            time_extended: 'Süre Uzatma',
            dd_halt: 'DD Halt',
            acik_pozisyon: 'Açık',
            // eski stratejilerin geriye uyumluluğu
            take_profit: 'Take Profit', stop_loss: 'Kritik Destek',
            skor_dustu: 'Skor Düştü', sure_doldu: 'Süre Doldu', kismi_cikis: 'Kısmi'
        };
        const exitHtml = Object.entries(exitDist).map(([k, v]) =>
            `<span class="bt-exit-pill">${exitLabels[k] || k}: <strong>${v}</strong></span>`).join('');

        const winColor = (o.kazanma_orani_pct || 0) >= 50 ? 'var(--neon)' : 'var(--warn)';
        const retColor = (o.ortalama_getiri_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)';
        const pfColor = (o.profit_factor || 0) >= 1.5 ? 'var(--neon)' : ((o.profit_factor || 0) >= 1 ? 'var(--warn)' : 'var(--danger)');
        const ddColor = (o.max_drawdown_pct || 0) <= 12 ? 'var(--neon)' : ((o.max_drawdown_pct || 0) <= 20 ? 'var(--warn)' : 'var(--danger)');
        const portColor = (o.portfoy_getiri_pct || 0) >= 0 ? 'var(--neon)' : 'var(--danger)';

        el.innerHTML = `
            <div class="bt-summary-grid">
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Toplam İşlem</span>
                    <span class="bt-stat-value">${o.toplam_islem ?? '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Kazanma Oranı</span>
                    <span class="bt-stat-value" style="color:${winColor}">${o.kazanma_orani_pct != null ? o.kazanma_orani_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Ort. Getiri</span>
                    <span class="bt-stat-value" style="color:${retColor}">${o.ortalama_getiri_pct != null ? (o.ortalama_getiri_pct >= 0 ? '+' : '') + o.ortalama_getiri_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Ort. Kazanç</span>
                    <span class="bt-stat-value" style="color:var(--neon)">${o.ortalama_kazanc_pct != null ? '+' + o.ortalama_kazanc_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Ort. Kayıp</span>
                    <span class="bt-stat-value" style="color:var(--danger)">${o.ortalama_kayip_pct != null ? o.ortalama_kayip_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">En İyi İşlem</span>
                    <span class="bt-stat-value" style="color:var(--neon)">${o.en_iyi_islem_pct != null ? '+' + o.en_iyi_islem_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">En Kötü İşlem</span>
                    <span class="bt-stat-value" style="color:var(--danger)">${o.en_kotu_islem_pct != null ? o.en_kotu_islem_pct + '%' : '-'}</span>
                </div>
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Sinyal Veren Hisse</span>
                    <span class="bt-stat-value">${o.sinyal_veren_hisse ?? '-'} / ${o.test_edilen_hisse ?? '-'}</span>
                </div>
                ${o.profit_factor != null ? `
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Profit Factor</span>
                    <span class="bt-stat-value" style="color:${pfColor}">${o.profit_factor}</span>
                </div>` : ''}
                ${o.max_drawdown_pct != null ? `
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Max Drawdown</span>
                    <span class="bt-stat-value" style="color:${ddColor}">-${o.max_drawdown_pct}%</span>
                </div>` : ''}
                ${o.portfoy_getiri_pct != null ? `
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Portföy Getirisi</span>
                    <span class="bt-stat-value" style="color:${portColor}">${o.portfoy_getiri_pct >= 0 ? '+' : ''}${o.portfoy_getiri_pct}%</span>
                </div>` : ''}
                ${o.sharpe_approx != null ? `
                <div class="bt-stat glass">
                    <span class="bt-stat-label">Sharpe (~)</span>
                    <span class="bt-stat-value">${o.sharpe_approx}</span>
                </div>` : ''}
            </div>

            <div class="bt-meta glass">
                <span class="bt-meta-item">📅 ${escapeHtml(data.donem || '')}</span>
                ${data.strateji ? `<span class="bt-meta-item">🧭 ${escapeHtml(data.strateji)}</span>` : ''}
                ${params.giris_yontemi ? `<span class="bt-meta-item">🎯 Giriş: <strong>${escapeHtml(params.giris_yontemi)}</strong></span>` : ''}
                ${params.cikis_yontemi ? `<span class="bt-meta-item">🔻 Çıkış: <strong>${escapeHtml(params.cikis_yontemi)}</strong></span>` : ''}
                <span class="bt-meta-item">🎯 Min skor: <strong>${params.giris_skoru ?? '-'}</strong>${params.tetik_penceresi_bar ? ` (tetik ${params.tetik_penceresi_bar} bar)` : ''}</span>
                <span class="bt-meta-item">📊 Trend alt-skoru: <strong>≥${params.min_trend_alt ?? '-'}</strong></span>
                <span class="bt-meta-item">🛑 ATR stop: <strong>×${params.atr_initial_mult ?? '-'}</strong></span>
                <span class="bt-meta-item">🎢 Trail: <strong>×${params.atr_trail_mult ?? '-'}</strong></span>
                <span class="bt-meta-item">✅ Kısmi TP: <strong>${params.kismi_tp_pct ?? '-'}%</strong></span>
                <span class="bt-meta-item">⏱ Maks süre: <strong>${params.max_sure_gun ?? '-'} gün${params.uzatma_gun ? ' (+' + params.uzatma_gun + ')' : ''}</strong></span>
                <span class="bt-meta-item">👥 Max poz: <strong>${params.max_pozisyon ?? '-'}</strong> (sektör ${params.max_sektor ?? '-'})</span>
                <span class="bt-meta-item">⚠ DD halt: <strong>${params.dd_halt_pct ?? '-'}%</strong></span>
                ${params.rejim_filtresi ? `<span class="bt-meta-item">📈 Rejim: <strong>${escapeHtml(params.rejim_filtresi)}${params.dual_rejim ? ' (dual)' : ''}</strong></span>` : ''}
            </div>

            ${exitHtml ? `<div class="bt-exits glass"><span class="bt-exits-title">Çıkış Dağılımı</span>${exitHtml}</div>` : ''}

            <div class="bt-table-wrap glass">
                <table class="bt-table">
                    <thead>
                        <tr>
                            <th>Sembol</th>
                            <th class="num">İşlem</th>
                            <th class="num">Kazanma %</th>
                            <th class="num">Toplam Getiri</th>
                            <th class="num">Ort. Süre</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody id="btTableBody"></tbody>
                </table>
            </div>`;

        const tbody = document.getElementById('btTableBody');
        stocks.forEach(s => {
            const isExpanded = _btState.expanded.has(s.sembol);
            const winRate = s.kazanma_orani_pct;
            const totalRet = s.toplam_getiri_pct;
            const winColor2 = winRate >= 50 ? 'var(--neon)' : 'var(--warn)';
            const retColor2 = totalRet >= 0 ? 'var(--neon)' : 'var(--danger)';
            const trades = s.islemler || [];
            const avgDays = trades.length ? Math.round(trades.reduce((a, t) => a + t.sure_gun, 0) / trades.length) : '-';

            const row = document.createElement('tr');
            row.className = 'bt-stock-row';
            row.dataset.symbol = s.sembol;
            row.innerHTML = `
                <td class="bt-symbol">${escapeHtml(s.sembol)}</td>
                <td class="num">${s.islem_sayisi}</td>
                <td class="num" style="color:${winColor2}">${winRate}%</td>
                <td class="num" style="color:${retColor2}">${totalRet >= 0 ? '+' : ''}${totalRet}%</td>
                <td class="num">${avgDays} gün</td>
                <td class="num"><button class="bt-expand-btn">${isExpanded ? '▲ Kapat' : '▼ Detay'}</button></td>`;
            tbody.appendChild(row);

            if (isExpanded) {
                const detailRow = document.createElement('tr');
                detailRow.className = 'bt-detail-row';
                detailRow.innerHTML = `<td colspan="6">${buildTradeDetailHtml(trades)}</td>`;
                tbody.appendChild(detailRow);
            }

            row.querySelector('.bt-expand-btn').addEventListener('click', () => {
                if (_btState.expanded.has(s.sembol)) _btState.expanded.delete(s.sembol);
                else _btState.expanded.add(s.sembol);
                renderBacktestResults(_btState.data);
            });
        });

        if (!stocks.length) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--text-3)">Bu market için işlem fırsatı bulunamadı.</td></tr>`;
        }
    }

    function buildTradeDetailHtml(trades) {
        const exitLabels = {
            trailing_stop: '🛑 Trail',
            sinyal_kirilim: '🔻 Sinyal Kırılımı',
            kismi_tp: '✅ Kısmi TP',
            score_3bar: '📉 Skor 3g',
            score_crash: '📉 Skor↓',
            dead_money: '💤 Dead',
            time_exit: '⏱ Süre',
            time_extended: '⏱ Süre+',
            dd_halt: '🚨 DD Halt',
            acik_pozisyon: '📂 Açık',
            // eski stratejilerin geriye uyumluluğu
            take_profit: '✅ TP', stop_loss: '🛑 KD',
            skor_dustu: '📉 Skor', sure_doldu: '⏱ Süre', kismi_cikis: '📉 Kısmi'
        };
        const rows = trades.map(t => {
            const retColor = t.getiri_pct >= 0 ? 'var(--neon)' : 'var(--danger)';
            return `<tr>
                <td>${escapeHtml(t.giris_tarihi)}</td>
                <td>${escapeHtml(t.cikis_tarihi)}</td>
                <td class="num">${t.giris_fiyati}</td>
                <td class="num">${t.cikis_fiyati}</td>
                <td class="num" style="color:${retColor}">${t.getiri_pct >= 0 ? '+' : ''}${t.getiri_pct}%</td>
                <td class="num">${t.sure_gun}g</td>
                <td>${exitLabels[t.cikis_nedeni] || escapeHtml(t.cikis_nedeni)}</td>
            </tr>`;
        }).join('');
        return `<div class="bt-detail-inner">
            <table class="bt-trade-table">
                <thead><tr>
                    <th>Giriş</th><th>Çıkış</th>
                    <th class="num">Giriş Fiyatı</th><th class="num">Çıkış Fiyatı</th>
                    <th class="num">Getiri</th><th class="num">Süre</th><th>Neden</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
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
            ${currencyToggleHtml}
`;

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
                        <span class="port-level port-score">${d.score}/10 sağlık</span>
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
            const qty = parseFloat(qtyInput?.value);
            if (!date || !price || isNaN(price) || price <= 0) { priceInput?.focus(); return; }
            if (!qty || isNaN(qty) || qty <= 0) { qtyInput?.focus(); return; }
            addPosition(data.symbol, state.market, date, price, qty);
            form?.classList.add('hidden');
            if (toggle) {
                const n = port.positions.filter(p => p.symbol === data.symbol).length;
                toggle.innerHTML = `&#10003; Portf&ouml;ye Eklendi (${n} pozisyon)`;
                toggle.style.cssText = 'background:rgba(52,245,168,.12);color:var(--neon);border-color:rgba(52,245,168,.4);pointer-events:none;';
            }
        });
    }

    // --- yorumlar ---
    async function loadAndWireComments(symbol) {
        const listEl = document.getElementById('commentsList');
        const input = document.getElementById('commentInput');
        const submitBtn = document.getElementById('commentSubmitBtn');
        const charCount = document.getElementById('commentCharCount');
        if (!listEl) return;

        function renderComments(comments) {
            if (!comments.length) {
                listEl.innerHTML = `<div style="color:var(--text-3);font-size:13px;padding:8px 0;">Henüz yorum yok. İlk yorumu sen yap!</div>`;
                return;
            }
            listEl.innerHTML = comments.map((c) => {
                const date = c.created_at ? new Date(c.created_at * 1000).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
                const isOwn = _currentUser && c.user_id === _currentUser.id;
                return `<div class="comment-item" data-id="${c.id}">
                    <div class="comment-meta">
                        <span class="comment-author">${escapeHtml(c.user_email)}</span>
                        <span class="comment-date">${date}</span>
                        ${isOwn ? `<button class="comment-delete-btn" data-id="${c.id}" title="Yorumu sil">✕</button>` : ''}
                    </div>
                    <div class="comment-body">${escapeHtml(c.body)}</div>
                </div>`;
            }).join('');
            listEl.querySelectorAll('.comment-delete-btn').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    const id = parseInt(btn.dataset.id);
                    await API.commentsDelete(id);
                    btn.closest('.comment-item').remove();
                    if (!listEl.querySelector('.comment-item')) {
                        listEl.innerHTML = `<div style="color:var(--text-3);font-size:13px;padding:8px 0;">Henüz yorum yok. İlk yorumu sen yap!</div>`;
                    }
                });
            });
        }

        try {
            const data = await API.commentsList(symbol);
            renderComments(data.comments || []);
        } catch (_) {
            listEl.innerHTML = `<div style="color:var(--text-3);font-size:13px;">Yorumlar yüklenemedi.</div>`;
        }

        if (input && charCount) {
            input.addEventListener('input', () => {
                charCount.textContent = `${input.value.length}/500`;
            });
        }

        if (submitBtn && input) {
            submitBtn.addEventListener('click', async () => {
                const body = input.value.trim();
                if (!body) return;
                submitBtn.disabled = true;
                submitBtn.textContent = 'Gönderiliyor...';
                try {
                    const res = await API.commentsAdd(symbol, body);
                    if (res.ok) {
                        input.value = '';
                        if (charCount) charCount.textContent = '0/500';
                        const existing = Array.from(listEl.querySelectorAll('.comment-item'));
                        const newHtml = document.createElement('div');
                        const c = res.comment;
                        const date = c.created_at ? new Date(c.created_at * 1000).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
                        newHtml.innerHTML = `<div class="comment-item" data-id="${c.id}">
                            <div class="comment-meta">
                                <span class="comment-author">${escapeHtml(c.user_email)}</span>
                                <span class="comment-date">${date}</span>
                                <button class="comment-delete-btn" data-id="${c.id}" title="Yorumu sil">✕</button>
                            </div>
                            <div class="comment-body">${escapeHtml(c.body)}</div>
                        </div>`;
                        const item = newHtml.firstChild;
                        item.querySelector('.comment-delete-btn').addEventListener('click', async () => {
                            await API.commentsDelete(c.id);
                            item.remove();
                        });
                        if (!existing.length) listEl.innerHTML = '';
                        listEl.insertBefore(item, listEl.firstChild);
                    }
                } catch (_) {}
                submitBtn.disabled = false;
                submitBtn.textContent = 'Yorum Yap';
            });
        }
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
            contextHtml = `
                <div class="chart-pos-context" style="align-items:center;gap:8px;">
                    ${spikeHtml}
                    ${reason ? `<span style="font-size:12px;color:var(--text-2);font-style:italic;">${escapeHtml(reason)}</span>` : ''}
                </div>`;
        }

        headerEl.innerHTML = `
            <div class="chart-modal-hdr">
                <div>
                    <div class="chart-sym-row">
                        <span class="chart-sym">${displaySym}</span>
                        <span class="chart-market-badge">${market.toUpperCase()}</span>
                        ${d && d.score != null ? `<span class="score-chip" data-score="${d.score}" style="font-size:12px;padding:3px 10px;"><span class="star">&#9733;</span> ${d.score}/10</span>` : ''}
                    </div>
                    ${contextHtml}
                </div>
                ${recHtml}
            </div>
            <div class="chart-legend">
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(52,245,168,.75);height:2px;"></span>K.Vadeli Destek</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(255,83,112,.75);height:2px;"></span>K.Vadeli Direnç</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(52,245,168,.4);height:1px;border-top:1px dashed rgba(52,245,168,.4);"></span>U.Vadeli Destek</span>
                <span class="chart-legend-item"><span class="chart-legend-line" style="background:rgba(255,83,112,.4);height:1px;border-top:1px dashed rgba(255,83,112,.4);"></span>U.Vadeli Direnç</span>
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
            // mode: 0 (Normal) — imleç en yakın muma "yapışmaz" (Magnet=1),
            // sadece fare imlecinin gerçek konumunu takip eder.
            crosshair: { mode: 0 },
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


        const curPrice = d.price;

        // ── Otomatik trend çizgileri ──────────────────────────────────────────
        // Kısa vadeli: solid çizgi  |  Uzun vadeli: kesik çizgi
        const autoTL = d.auto_trendlines || {};
        const autoTLDefs = [
            // [timeframe_key, role_key, renk, lineStyle (0=solid,2=dashed), lineWidth]
            ["short", "support",    "rgba(52,245,168,0.75)",  0, 1.5],
            ["short", "resistance", "rgba(255,83,112,0.75)",  0, 1.5],
            ["long",  "support",    "rgba(52,245,168,0.40)",  2, 1.5],
            ["long",  "resistance", "rgba(255,83,112,0.40)",  2, 1.5],
        ];
        autoTLDefs.forEach(([tf, role, color, lineStyle, lineWidth]) => {
            const line = (autoTL[tf] || {})[role];
            if (!line || line.length < 2 || !line[0].t || !line[1].t) return;
            try {
                const ls = chart.addLineSeries({
                    color, lineWidth, lineStyle,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                    title: '',
                });
                ls.setData([
                    { time: line[0].t, value: line[0].v },
                    { time: line[1].t, value: line[1].v },
                ]);
            } catch (_) {}
        });

        // ── Formasyon pattern çizgileri & marker'lar ──────────────────────────
        const patterns = d.patterns || [];
        const allMarkers = [];
        patterns.forEach(pat => {
            (pat.markers || []).forEach(m => {
                if (!m.t) return;
                allMarkers.push({ time: m.t, position: m.pos, color: m.color, shape: m.shape, text: m.label || '' });
            });
        });
        if (allMarkers.length) {
            try { candleSeries.setMarkers(allMarkers.sort((a, b) => (a.time < b.time ? -1 : 1))); } catch (_) {}
        }

        chart.timeScale().fitContent();

        // Overlay canvas — kullanıcı piksel koordinatında serbestçe çizer
        chartEl.style.position = 'relative';
        const overlayCanvas = document.createElement('canvas');
        overlayCanvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:5;';
        chartEl.appendChild(overlayCanvas);
        overlayCanvas.width = chartEl.clientWidth;
        overlayCanvas.height = chartEl.clientHeight || 400;

        const trendLines = [];
        let _trendPending = null;
        let _trendHintEl = null;
        let _mousePos = null;   // anl\u0131k mouse konumu (piksel, canvas'a g\u00F6re)

        // Trend noktalar\u0131 grafi\u011Fin veri uzay\u0131nda (logical index + fiyat) saklan\u0131r,
        // b\u00F6ylece b\u00FCy\u00FCtme/k\u00FC\u00E7\u00FCltme veya kayd\u0131rma/yak\u0131nla\u015Ft\u0131rmada ger\u00E7ek zaman/fiyat
        // konumuna g\u00F6re yeniden \u00E7izilirler (sabit piksel oran\u0131na g\u00F6re de\u011Fil).
        function pixelToData(x, y) {
            const logical = chart.timeScale().coordinateToLogical(x);
            const price = candleSeries.coordinateToPrice(y);
            if (logical === null || price === null) return null;
            return { logical, price };
        }

        function dataToPixel(logical, price) {
            const x = chart.timeScale().logicalToCoordinate(logical);
            const y = candleSeries.priceToCoordinate(price);
            if (x === null || y === null) return null;
            return { x, y };
        }

        function redrawTrendOverlay() {
            const w = overlayCanvas.width;
            const h = overlayCanvas.height;
            const ctx = overlayCanvas.getContext('2d');
            ctx.clearRect(0, 0, w, h);

            // Tamamlanm\u0131\u015F \u00E7izgiler
            ctx.strokeStyle = 'rgba(251,191,36,0.9)';
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.setLineDash([]);
            trendLines.forEach(({ logical1, price1, logical2, price2 }) => {
                const p1 = dataToPixel(logical1, price1);
                const p2 = dataToPixel(logical2, price2);
                if (!p1 || !p2) return;
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
                // U\u00E7 noktalar
                [p1, p2].forEach(({ x, y }) => {
                    ctx.beginPath();
                    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(251,191,36,0.85)';
                    ctx.fill();
                });
            });

            const pendingPx = _trendPending ? dataToPixel(_trendPending.logical, _trendPending.price) : null;
            if (pendingPx) {
                const px = pendingPx.x;
                const py = pendingPx.y;

                // Mouse'a uzanan kesik \u00F6nizleme \u00E7izgisi
                if (_mousePos) {
                    const mx = _mousePos.x;
                    const my = _mousePos.y;
                    ctx.save();
                    ctx.setLineDash([7, 5]);
                    ctx.strokeStyle = 'rgba(251,191,36,0.55)';
                    ctx.lineWidth = 1.5;
                    ctx.lineCap = 'round';
                    ctx.beginPath();
                    ctx.moveTo(px, py);
                    ctx.lineTo(mx, my);
                    ctx.stroke();
                    ctx.restore();
                }

                // \u0130lk nokta: parlayan halka + dolu nokta
                ctx.save();
                ctx.beginPath();
                ctx.arc(px, py, 11, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(251,191,36,0.12)';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(px, py, 6, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(251,191,36,0.85)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(255,255,255,0.7)';
                ctx.lineWidth = 1.5;
                ctx.setLineDash([]);
                ctx.stroke();
                ctx.restore();
            }

            // Cursor crosshair + hedef noktas\u0131
            if (_mousePos) {
                const mx = _mousePos.x;
                const my = _mousePos.y;
                ctx.save();
                ctx.setLineDash([3, 4]);
                ctx.strokeStyle = 'rgba(251,191,36,0.3)';
                ctx.lineWidth = 1;
                ctx.beginPath(); ctx.moveTo(mx, 0); ctx.lineTo(mx, h); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(0, my); ctx.lineTo(w, my); ctx.stroke();
                ctx.setLineDash([]);
                ctx.beginPath();
                ctx.arc(mx, my, _trendPending ? 5 : 4, 0, Math.PI * 2);
                ctx.fillStyle = _trendPending ? 'rgba(251,191,36,0.75)' : 'rgba(251,191,36,0.5)';
                ctx.fill();
                ctx.strokeStyle = 'rgba(255,255,255,0.5)';
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.restore();
            }
        }

        overlayCanvas.addEventListener('mousemove', e => {
            const rect = overlayCanvas.getBoundingClientRect();
            _mousePos = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top,
            };
            redrawTrendOverlay();
        });

        overlayCanvas.addEventListener('mouseleave', () => {
            _mousePos = null;
            redrawTrendOverlay();
        });

        overlayCanvas.addEventListener('click', e => {
            const rect = overlayCanvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const data = pixelToData(x, y);
            if (!data) return;
            if (!_trendPending) {
                _trendPending = data;
                if (_trendHintEl) _trendHintEl.textContent = '2. noktas\u0131n\u0131 se\u00E7';
                redrawTrendOverlay();
            } else {
                trendLines.push({
                    logical1: _trendPending.logical, price1: _trendPending.price,
                    logical2: data.logical, price2: data.price,
                });
                _trendPending = null;
                redrawTrendOverlay();
                if (_trendHintEl) _trendHintEl.textContent = '\u00C7izildi \u2713';
                setTimeout(() => { if (_trendHintEl) _trendHintEl.textContent = '1. noktas\u0131n\u0131 se\u00E7'; }, 1200);
            }
        });

        // Trendline toolbar
        const toolbarEl = document.getElementById('portTrendToolbar');
        if (toolbarEl) {
            toolbarEl.style.display = 'flex';
            toolbarEl.style.gap = '8px';
            toolbarEl.style.alignItems = 'center';
            toolbarEl.style.margin = '8px 0 4px';
            toolbarEl.innerHTML = `
                <button id="portTrendBtn" class="btn btn-ghost" style="font-size:12px;padding:4px 10px;">&#x1F4C8; Trend \u00C7iz</button>
                <button id="portTrendUndoBtn" class="btn btn-ghost" style="font-size:12px;padding:4px 10px;" title="Son \u00E7izgiyi sil">&#x21A9; Geri Al</button>
                <button id="portTrendClearBtn" class="btn btn-ghost" style="font-size:12px;padding:4px 10px;" title="T\u00FCm\u00FCn\u00FC sil">&#x1F5D1; Temizle</button>
                <span id="portTrendHint" style="font-size:11px;color:var(--text-3);"></span>
            `;
            let trendMode = false;
            const trendBtn = document.getElementById('portTrendBtn');
            const undoBtn = document.getElementById('portTrendUndoBtn');
            const clearBtn = document.getElementById('portTrendClearBtn');
            _trendHintEl = document.getElementById('portTrendHint');

            trendBtn.addEventListener('click', () => {
                trendMode = !trendMode;
                _trendPending = null;
                _mousePos = null;
                trendBtn.style.color = trendMode ? 'var(--neon)' : '';
                trendBtn.textContent = trendMode ? '\u2715 Trend Modu' : '\uD83D\uDCC8 Trend \u00C7iz';
                _trendHintEl.textContent = trendMode ? '1. noktas\u0131n\u0131 se\u00E7' : '';
                overlayCanvas.style.pointerEvents = trendMode ? 'auto' : 'none';
                overlayCanvas.style.cursor = trendMode ? 'none' : '';
                redrawTrendOverlay();
            });

            undoBtn.addEventListener('click', () => {
                if (_trendPending) {
                    _trendPending = null;
                    redrawTrendOverlay();
                } else {
                    trendLines.pop();
                    redrawTrendOverlay();
                }
                _trendHintEl.textContent = trendMode ? '1. noktas\u0131n\u0131 se\u00E7' : '';
            });

            clearBtn.addEventListener('click', () => {
                trendLines.length = 0;
                _trendPending = null;
                _trendHintEl.textContent = '';
                redrawTrendOverlay();
            });
        }

        const ro = new ResizeObserver(() => {
            try {
                const w = chartEl.clientWidth;
                const h = chartEl.clientHeight || 400;
                chart.applyOptions({ width: w, height: h });
                overlayCanvas.width = w;
                overlayCanvas.height = h;
                redrawTrendOverlay();
            } catch (_) {}
        });
        ro.observe(chartEl);
        chartEl._resizeObs = ro;

        // Grafik kaydırılıp yakınlaştırıldığında (pan/zoom) trend çizgileri de
        // güncel zaman/fiyat eksenine göre yeniden konumlanmalı.
        chart.timeScale().subscribeVisibleLogicalRangeChange(() => redrawTrendOverlay());

        if (patternEl) {
            if (!patterns.length) {
                patternEl.innerHTML = `
                    <div class="pattern-empty">
                        <span>Aktif formasyon tespit edilmedi</span>
                        <small>Son 120 barda bilinen bir grafik formasyonu bulunamadı.</small>
                    </div>`;
            } else {
                const confIcon = { yüksek: '●●●', orta: '●●○', düşük: '●○○' };
                const confColor = { yüksek: 'var(--neon)', orta: '#fbbf24', düşük: 'var(--text-3)' };
                const multiple = patterns.length > 1;

                // Baskınlık analizi banner'ı (≥2 formasyon veya tek formasyon özeti)
                const an = d.pattern_analysis;
                const analysisHtml = (an && an.summary) ? `
                    <div style="display:flex;gap:9px;align-items:flex-start;padding:11px 13px;margin-bottom:11px;border-radius:10px;
                                background:${an.conflict ? 'rgba(251,191,36,.09)' : 'rgba(52,245,168,.08)'};
                                border:1px solid ${an.conflict ? 'rgba(251,191,36,.30)' : 'rgba(52,245,168,.25)'};">
                        <span style="font-size:15px;line-height:1.2;">${an.conflict ? '⚖️' : '🎯'}</span>
                        <div style="font-size:12.5px;line-height:1.5;color:var(--text-2);">
                            <strong style="color:${an.conflict ? '#fbbf24' : 'var(--neon)'};">
                                ${an.conflict ? 'Çelişen formasyonlar' : 'Baskınlık analizi'}</strong><br>
                            ${escapeHtml(an.summary)}
                        </div>
                    </div>` : '';

                patternEl.innerHTML = `
                    <div class="pattern-section-title">Tespit Edilen Formasyonlar &mdash; ${patterns.length} adet</div>
                    ${analysisHtml}
                    <div class="pattern-grid">
                        ${patterns.map(p => {
                            const conf = p.confidence || 'orta';
                            const isDom = multiple && p.dominant;
                            const domBadge = isDom
                                ? `<span style="font-size:9px;font-weight:700;letter-spacing:.5px;padding:2px 6px;border-radius:999px;background:rgba(52,245,168,.18);color:var(--neon);border:1px solid rgba(52,245,168,.4);">BASKIN</span>`
                                : '';
                            const domStyle = isDom ? 'box-shadow:0 0 0 1px rgba(52,245,168,.45);' : '';
                            return `
                            <div class="pattern-card ${escapeHtml(p.direction)}" style="${domStyle}">
                                <div class="pattern-card-hdr">
                                    <span class="pattern-emoji">${p.emoji || '📊'}</span>
                                    <span class="pattern-name">${escapeHtml(p.name)}</span>
                                    ${domBadge}
                                    <span class="pattern-strength">${escapeHtml(p.strength)}</span>
                                    <span style="margin-left:auto;font-size:10px;letter-spacing:1px;color:${confColor[conf] || 'var(--text-3)'};" title="Güvenilirlik: ${conf}">${confIcon[conf] || '●○○'}</span>
                                </div>
                                <div class="pattern-desc">${escapeHtml(p.description)}</div>
                                <div class="pattern-signal">${escapeHtml(p.signal)}</div>
                            </div>`;
                        }).join('')}
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
            chartEl.style.cursor = '';
        }
        const toolbarEl = document.getElementById('portTrendToolbar');
        if (toolbarEl) { toolbarEl.style.display = 'none'; toolbarEl.innerHTML = ''; }
    }

    document.getElementById('portChartClose')?.addEventListener('click', closePortChartModal);
    document.getElementById('portChartModal')?.querySelector('.modal-backdrop')?.addEventListener('click', closePortChartModal);

    function switchTab(tab) {
        const scanSec = document.getElementById('tab-scan');
        const portSec = document.getElementById('tab-portfolio');
        const alertSec = document.getElementById('tab-alerts');
        const btSec = document.getElementById('tab-backtest');
        if (scanSec) scanSec.classList.toggle('hidden', tab !== 'scan');
        if (portSec) portSec.classList.toggle('hidden', tab !== 'portfolio');
        if (alertSec) alertSec.classList.toggle('hidden', tab !== 'alerts');
        if (btSec) btSec.classList.toggle('hidden', tab !== 'backtest');
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
        if (tab === 'portfolio') {
            const rateP = state.usdRate ? Promise.resolve() : fetchExchangeRate();
            rateP.then(() => fetchPortfolioDetails()).then(() => renderPortfolioTab());
        }
        if (tab === 'alerts') loadAlerts();
        if (tab === 'backtest') renderBacktestTab();
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
        if (e.key === 'Escape') {
            closeModal();
            closePortChartModal();
            closeAuthModal();
            closeAlertModal();
            closePricingModal();
            confirmDeleteModal?.classList.add('hidden');
            accountPanel?.classList.add('hidden');
            return;
        }
        if (isTyping) return;
        if (e.key === '/') { e.preventDefault(); els.searchInput.focus(); return; }
        if (e.key === '?') { window.location.href = '/rehber.html'; return; }
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

    // Yeni alarm modal — sadece fiyat hedefi (üstüne çıkınca / altına düşünce)
    let _selectedDirection = '';

    function openAlertModal() {
        const modal = document.getElementById('alertModal');
        const dirGroup = document.getElementById('af-direction-group');
        if (!modal || !dirGroup) return;

        if (alertConditions.length && !dirGroup.children.length) {
            alertConditions.forEach(c => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'af-direction-btn';
                btn.dataset.type = c.type;
                btn.textContent = c.label;
                btn.addEventListener('click', () => {
                    _selectedDirection = c.type;
                    dirGroup.querySelectorAll('.af-direction-btn').forEach(b => {
                        b.classList.toggle('active', b.dataset.type === c.type);
                    });
                });
                dirGroup.appendChild(btn);
            });
        }

        _selectedDirection = '';
        dirGroup.querySelectorAll('.af-direction-btn').forEach(b => b.classList.remove('active'));
        document.getElementById('af-symbol').value = '';
        document.getElementById('af-value').value = '';
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
    document.getElementById('alertModal')?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.target?.tagName !== 'BUTTON') document.getElementById('af-submit')?.click();
    });

    document.getElementById('af-submit')?.addEventListener('click', async () => {
        const symbol = (document.getElementById('af-symbol')?.value || '').trim().toUpperCase();
        const condition_type = _selectedDirection;
        const valueStr = document.getElementById('af-value')?.value || '';
        const errEl = document.getElementById('af-error');

        if (!symbol || !condition_type) {
            if (errEl) { errEl.textContent = 'Hisse sembolü ve yön seçimi zorunludur.'; errEl.style.display = 'block'; }
            return;
        }
        if (!valueStr) {
            if (errEl) { errEl.textContent = 'Hedef fiyat girilmeli.'; errEl.style.display = 'block'; }
            return;
        }

        const body = { symbol, condition_type, condition_value: parseFloat(valueStr) };

        const btn = document.getElementById('af-submit');
        if (btn) btn.disabled = true;
        try {
            const res = await API.alertsCreate(body);
            if (res.ok) {
                closeAlertModal();
                showToast(`Alarm kuruldu: ${symbol} – ${res.alert.label}`, 'success');
                loadAlerts();
            } else {
                const msg = res.error === 'email_not_verified'
                    ? 'Alarm kurmak için önce e-posta adresinizi doğrulayın — gelen kutunuzu kontrol edin.'
                    : (res.error || 'Hata oluştu.');
                if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
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
        const backtestTab = document.getElementById('backtestTabBtn');

        const verifyBanner = document.getElementById('emailVerifyBanner');
        const betaBanner = document.getElementById('betaBanner');
        const adminBar = document.getElementById('adminBar');
        if (user) {
            authArea.classList.add('hidden');
            userArea.classList.remove('hidden');
            userEmailEl.textContent = user.email;
            if (planBadge) {
                planBadge.classList.remove('hidden');
                const isPremium = user.plan === 'premium';
                planBadge.textContent = isPremium
                    ? (user.is_lifetime ? '⭐ Premium (Ömür Boyu)' : '⭐ Premium')
                    : 'Üye';
                planBadge.classList.toggle('premium', isPremium);
            }
            if (upgradeBtn) upgradeBtn.classList.toggle('hidden', user.plan === 'premium');
            if (backtestTab) backtestTab.classList.toggle('hidden', !user.is_admin);
            if (verifyBanner) verifyBanner.classList.toggle('hidden', !!user.email_verified);
            if (betaBanner) betaBanner.classList.add('hidden');
            if (adminBar) {
                if (user.is_admin) {
                    adminBar.classList.remove('hidden');
                    fetch('/api/admin/stats').then(r => r.json()).then(s => {
                        adminBar.innerHTML = `<span>👤 Kullanıcı: <strong>${s.total_users}</strong></span><span>🎁 Lifetime: <strong>${s.lifetime_users}/100</strong> (${s.lifetime_slots_left} yer kaldı)</span><span>📬 Newsletter: <strong>${s.newsletter_subscribers}</strong></span><button id="adminUsersBtn" class="btn btn-ghost" style="font-size:12px;padding:3px 10px;margin-left:8px;">👥 Kullanıcılar</button>`;
                        const btn = document.getElementById('adminUsersBtn');
                        if (btn) btn.addEventListener('click', () => openAdminUsers());
                    }).catch(() => { adminBar.innerHTML = '<span>Admin verileri yüklenemedi.</span>'; });
                } else {
                    adminBar.classList.add('hidden');
                }
            }
        } else {
            authArea.classList.remove('hidden');
            userArea.classList.add('hidden');
            if (backtestTab) backtestTab.classList.add('hidden');
            if (verifyBanner) verifyBanner.classList.add('hidden');
            if (adminBar) adminBar.classList.add('hidden');
            // Kapatılmamışsa beta banner'ı göster
            if (betaBanner && !sessionStorage.getItem('betaBannerClosed')) {
                betaBanner.classList.remove('hidden');
            }
        }
    }

    document.getElementById('betaBannerClose')?.addEventListener('click', () => {
        document.getElementById('betaBanner')?.classList.add('hidden');
        sessionStorage.setItem('betaBannerClosed', '1');
    });
    document.getElementById('betaBannerCta')?.addEventListener('click', () => openAuthModal('signup'));

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
        loadIndices();
        // ?s=SYMBOL deeplink — paylaş butonu linklerini destekler
        const deepSym = new URLSearchParams(location.search).get('s');
        if (deepSym) openStockModal(deepSym.toUpperCase());
    });

    // Auth modal
    const authModal = document.getElementById('authModal');
    function showMarketGate() {
        // Misafir ABD sekmesine geçmeye çalışınca kayıt modalı açılır
        openAuthModal('signup');
    }

    window.openAuthModal = function openAuthModal(tab) {
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

    authModal?.addEventListener('keydown', e => {
        if (e.key !== 'Enter' || e.target?.tagName === 'BUTTON' || e.target?.tagName === 'A') return;
        if (!document.getElementById('authFormLogin')?.classList.contains('hidden')) {
            document.getElementById('loginSubmit')?.click();
        } else if (!document.getElementById('authFormSignup')?.classList.contains('hidden')) {
            document.getElementById('signupSubmit')?.click();
        } else if (!document.getElementById('authFormForgot')?.classList.contains('hidden')) {
            document.getElementById('forgotSubmit')?.click();
        } else if (!document.getElementById('authFormReset')?.classList.contains('hidden')) {
            document.getElementById('resetSubmit')?.click();
        }
    });

    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const which = tab.dataset.auth;
            openAuthModal(which);
        });
    });

    // Şifre göster/gizle toggle'ları
    const _EYE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    const _EYE_OFF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="1" y1="1" x2="23" y2="23"/><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/></svg>';
    document.querySelectorAll('.pw-toggle').forEach(btn => {
        btn.innerHTML = _EYE;
        btn.addEventListener('click', () => {
            const input = document.getElementById(btn.dataset.target);
            if (!input) return;
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            btn.innerHTML = show ? _EYE_OFF : _EYE;
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
            } else if (d.error === 'email_not_verified') {
                errEl.innerHTML = '';
                const msg = document.createTextNode('E-posta adresiniz henüz doğrulanmamış. ');
                const link = document.createElement('a');
                link.href = '#';
                link.style.color = 'var(--accent)';
                link.textContent = 'Doğrulama e-postası gönder';
                link.addEventListener('click', async (e) => {
                    e.preventDefault();
                    link.textContent = 'Gönderiliyor...';
                    await fetch('/api/auth/resend-verify-public', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email }),
                    });
                    errEl.textContent = 'Doğrulama e-postası gönderildi. Gelen kutunuzu kontrol edin.';
                });
                errEl.appendChild(msg);
                errEl.appendChild(link);
                errEl.classList.remove('hidden');
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
        const msgEl = document.getElementById('forgotMsg');
        const btn = document.getElementById('forgotSubmit');
        msgEl.style.display = 'none';
        btn.disabled = true;
        btn.textContent = 'Gönderiliyor...';
        try {
            const d = await Auth.forgot(email);
            if (d && d.ok === false && d.error === 'email_send_failed') {
                msgEl.textContent = 'E-posta gönderilemedi. Lütfen birkaç dakika sonra tekrar deneyin veya destek@nebulascanner.com adresine yazın.';
                msgEl.style.color = 'var(--danger)';
            } else {
                msgEl.textContent = 'Bağlantı gönderildi — gelen kutunuzu kontrol edin.';
                msgEl.style.color = 'var(--success)';
            }
            msgEl.style.display = 'block';
        } catch {
            msgEl.textContent = 'Bağlantı hatası. Lütfen tekrar deneyin.';
            msgEl.style.color = 'var(--danger)';
            msgEl.style.display = 'block';
        } finally {
            btn.disabled = false;
            btn.textContent = 'Sıfırlama Bağlantısı Gönder';
        }
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

    // Resend email verification
    document.getElementById('resendVerifyBtn')?.addEventListener('click', async function() {
        this.disabled = true;
        this.textContent = 'Gönderiliyor...';
        try {
            const d = await fetch('/api/auth/resend-verify', { method: 'POST', credentials: 'include' }).then(r => r.json());
            if (d.ok) showToast('Doğrulama e-postası gönderildi — gelen kutunuzu kontrol edin.', 'success');
            else showToast('E-posta gönderilemedi, lütfen tekrar deneyin.', 'danger');
        } catch {
            showToast('Bağlantı hatası.', 'danger');
        } finally {
            this.disabled = false;
            this.textContent = 'Tekrar gönder';
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

    // ── Ayarlar Modalı ────────────────────────────────────────────────────
    const settingsModal = document.getElementById('settingsModal');

    function openSettingsModal() {
        accountPanel?.classList.add('hidden');
        if (!settingsModal || !_currentUser) return;
        const u = _currentUser;

        const emailEl = document.getElementById('settingsEmail');
        if (emailEl) emailEl.textContent = u.email;

        const createdEl = document.getElementById('settingsCreatedAt');
        if (createdEl) {
            createdEl.textContent = u.created_at
                ? new Date(u.created_at).toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' })
                : '-';
        }

        const verifyEl = document.getElementById('settingsVerifyStatus');
        if (verifyEl) verifyEl.textContent = u.email_verified ? '✅ Doğrulandı' : '⚠ Doğrulanmadı';

        const planEl = document.getElementById('settingsPlanValue');
        const planActionsEl = document.getElementById('settingsPlanActions');
        if (planEl) {
            planEl.textContent = u.plan === 'premium'
                ? (u.is_lifetime ? 'Premium (Ömür Boyu)' : 'Premium')
                : 'Üye (Ücretsiz)';
        }
        if (planActionsEl) {
            planActionsEl.innerHTML = '';
            if (u.plan !== 'premium') {
                const btn = document.createElement('button');
                btn.className = 'btn btn-primary';
                btn.style.fontSize = '13px';
                btn.textContent = "⭐ Premium'a Geç";
                btn.addEventListener('click', () => { closeSettingsModal(); openPricingModal(); });
                planActionsEl.appendChild(btn);
            } else if (u.can_manage_billing) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-ghost';
                btn.style.fontSize = '13px';
                btn.textContent = 'Aboneliği Yönet';
                btn.addEventListener('click', async () => {
                    btn.disabled = true;
                    try {
                        const r = await fetch('/api/billing/portal', { method: 'POST', credentials: 'include' });
                        const d = await r.json();
                        if (d.url) window.location.href = d.url;
                        else showToast('Abonelik portalı açılamadı.', 'danger');
                    } catch { showToast('Bağlantı hatası.', 'danger'); }
                    btn.disabled = false;
                });
                planActionsEl.appendChild(btn);
            }
        }

        const marketingCb = document.getElementById('settingsMarketingConsent');
        if (marketingCb) marketingCb.checked = !!u.marketing_consent;

        const cookieStatusEl = document.getElementById('settingsCookieStatus');
        if (cookieStatusEl) {
            const pref = localStorage.getItem('nebula.cookieConsent');
            cookieStatusEl.textContent = pref === 'accepted' ? 'Kabul edildi' : (pref === 'rejected' ? 'Reddedildi' : 'Henüz seçilmedi');
        }

        const pwMsg = document.getElementById('settingsPasswordMsg');
        if (pwMsg) { pwMsg.style.display = 'none'; pwMsg.textContent = ''; }
        const curPw = document.getElementById('settingsCurrentPassword');
        const newPw = document.getElementById('settingsNewPassword');
        if (curPw) curPw.value = '';
        if (newPw) newPw.value = '';

        settingsModal.classList.remove('hidden');
    }

    function closeSettingsModal() {
        settingsModal?.classList.add('hidden');
    }

    document.getElementById('openSettingsBtn')?.addEventListener('click', openSettingsModal);
    document.getElementById('settingsModalClose')?.addEventListener('click', closeSettingsModal);
    document.getElementById('settingsModalBackdrop')?.addEventListener('click', closeSettingsModal);

    // Pazarlama e-postası izni
    document.getElementById('settingsMarketingConsent')?.addEventListener('change', async (e) => {
        const checked = e.target.checked;
        try {
            const r = await fetch('/api/auth/consent', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ marketing_consent: checked }),
            });
            if (r.ok) {
                showToast(checked ? 'Pazarlama e-postalarına izin verildi.' : 'Pazarlama e-postaları kapatıldı.', 'success');
            } else {
                e.target.checked = !checked;
                showToast('Tercih kaydedilemedi.', 'danger');
            }
        } catch {
            e.target.checked = !checked;
            showToast('Bağlantı hatası.', 'danger');
        }
    });

    // Çerez / analitik tercihini değiştir — tercih değişince GA4/Clarity yükleme
    // kararı sayfa açılışında yeniden değerlendirilsin diye sayfa yenilenir.
    document.getElementById('settingsCookiePref')?.addEventListener('click', () => {
        const cur = localStorage.getItem('nebula.cookieConsent');
        const next = cur === 'accepted' ? 'rejected' : 'accepted';
        localStorage.setItem('nebula.cookieConsent', next);
        showToast(next === 'accepted' ? 'Analiz çerezleri kabul edildi, sayfa yenileniyor…' : 'Analiz çerezleri reddedildi, sayfa yenileniyor…', 'info');
        setTimeout(() => location.reload(), 900);
    });

    // Şifre değiştir
    document.getElementById('settingsPasswordSubmit')?.addEventListener('click', async () => {
        const btn = document.getElementById('settingsPasswordSubmit');
        const msgEl = document.getElementById('settingsPasswordMsg');
        const current_password = document.getElementById('settingsCurrentPassword')?.value || '';
        const new_password = document.getElementById('settingsNewPassword')?.value || '';
        if (msgEl) msgEl.style.display = 'none';
        if (!current_password || !new_password) {
            if (msgEl) { msgEl.textContent = 'Her iki alan da zorunludur.'; msgEl.style.color = 'var(--danger)'; msgEl.style.display = 'block'; }
            return;
        }
        btn.disabled = true;
        try {
            const r = await fetch('/api/auth/password', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password, new_password }),
            });
            const d = await r.json().catch(() => ({}));
            if (r.ok) {
                if (msgEl) { msgEl.textContent = 'Şifreniz güncellendi.'; msgEl.style.color = 'var(--neon)'; msgEl.style.display = 'block'; }
                document.getElementById('settingsCurrentPassword').value = '';
                document.getElementById('settingsNewPassword').value = '';
            } else {
                if (msgEl) { msgEl.textContent = d.message || 'Şifre güncellenemedi.'; msgEl.style.color = 'var(--danger)'; msgEl.style.display = 'block'; }
            }
        } catch {
            if (msgEl) { msgEl.textContent = 'Bağlantı hatası.'; msgEl.style.color = 'var(--danger)'; msgEl.style.display = 'block'; }
        } finally {
            btn.disabled = false;
        }
    });

    // Veri indirme (KVKK export)
    document.getElementById('exportDataBtn')?.addEventListener('click', async () => {
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
        closeSettingsModal();
        confirmDeleteModal?.classList.remove('hidden');
        const errEl = document.getElementById('confirmDeleteError');
        if (errEl) errEl.style.display = 'none';
        const pwEl = document.getElementById('confirmDeletePassword');
        if (pwEl) pwEl.value = '';
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
        const password = document.getElementById('confirmDeletePassword')?.value || '';
        if (!password) {
            if (errEl) { errEl.textContent = 'Devam etmek için şifreni gir.'; errEl.style.display = 'block'; }
            return;
        }
        btn.disabled = true;
        btn.textContent = 'Siliniyor...';
        try {
            const r = await fetch('/api/auth/me', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password }),
            });
            if (r.ok) {
                confirmDeleteModal?.classList.add('hidden');
                applyUserState(null);
                port.positions = [];
                state.watchlist = new Set();
                showToast('Hesabınız silindi. Görüşmek üzere.', 'info');
            } else {
                const d = await r.json().catch(() => ({}));
                if (errEl) { errEl.textContent = d.message || d.error || 'Bir hata oluştu.'; errEl.style.display = 'block'; }
                btn.disabled = false; btn.textContent = 'Evet, Hesabımı Sil';
            }
        } catch {
            if (errEl) { errEl.textContent = 'Bağlantı hatası.'; errEl.style.display = 'block'; }
            btn.disabled = false; btn.textContent = 'Evet, Hesabımı Sil';
        }
    });

    // ── Pricing modal ────────────────────────────────────────────────────
    const pricingModal = document.getElementById('pricingModal');
    function openPricingModal() { if (pricingModal) pricingModal.classList.remove('hidden'); }
    function closePricingModal() { if (pricingModal) pricingModal.classList.add('hidden'); }
    document.getElementById('pricingModalClose')?.addEventListener('click', closePricingModal);
    document.getElementById('pricingModalBackdrop')?.addEventListener('click', closePricingModal);
    document.querySelectorAll('.pricing-cta').forEach(btn => {
        btn.addEventListener('click', () => window.openCheckout(btn.dataset.period || 'monthly'));
    });

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

    // GA4 — yalnızca kullanıcı onayı sonrası yüklenir
    function _loadGA4(id) {
        const s = document.createElement('script');
        s.async = true;
        s.src = `https://www.googletagmanager.com/gtag/js?id=${id}`;
        document.head.appendChild(s);
        window.dataLayer = window.dataLayer || [];
        window.gtag = function(){ window.dataLayer.push(arguments); };
        window.gtag('js', new Date());
        window.gtag('config', id);
    }

    // Microsoft Clarity — GA4 ile aynı kural: sadece rıza "accepted" ise yüklenir.
    // Önceden index.html <head>'inde koşulsuz yükleniyordu; "Reddet" seçilse bile
    // çalışmaya devam ediyordu — bu tutarsızlık burada giderildi.
    const CLARITY_ID = 'wmh101q9jz';
    function _loadClarity(id) {
        (function(c,l,a,r,i,t,y){
            c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
            t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
            y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
        })(window, document, "clarity", "script", id);
    }

    fetch('/api/config').then(r => r.json()).then(cfg => {
        if (!cfg.ga_measurement_id) return;
        window._gaMeasurementId = cfg.ga_measurement_id;
        if (localStorage.getItem('nebula.cookieConsent') === 'accepted') {
            _loadGA4(cfg.ga_measurement_id);
        }
    }).catch(() => {});

    if (localStorage.getItem('nebula.cookieConsent') === 'accepted') {
        _loadClarity(CLARITY_ID);
    }

    // ── Cookie banner ────────────────────────────────────────────────────
    if (!localStorage.getItem('nebula.cookieConsent')) {
        const banner = document.getElementById('cookieBanner');
        if (banner) banner.classList.remove('hidden');
        document.getElementById('cookieAccept')?.addEventListener('click', () => {
            localStorage.setItem('nebula.cookieConsent', 'accepted');
            if (window._gaMeasurementId) _loadGA4(window._gaMeasurementId);
            _loadClarity(CLARITY_ID);
            banner.classList.add('hidden');
        });
        document.getElementById('cookieReject')?.addEventListener('click', () => {
            localStorage.setItem('nebula.cookieConsent', 'rejected');
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

    // ── Geri Bildirim Modal ──────────────────────────────────────────────
    (function initFeedback() {
        const overlay  = document.getElementById('feedbackModal');
        const trigger  = document.getElementById('feedbackTrigger');
        const closeBtn = document.getElementById('feedbackClose');
        const textarea = document.getElementById('feedbackText');
        const counter  = document.getElementById('feedbackCharCount');
        const submitBtn = document.getElementById('feedbackSubmit');
        const success  = document.getElementById('feedbackSuccess');
        const select   = document.getElementById('feedbackCategory');
        if (!overlay || !trigger) return;

        const open  = () => { overlay.classList.remove('hidden'); textarea.focus(); };
        const close = () => { overlay.classList.add('hidden'); success.classList.add('hidden'); textarea.value = ''; counter.textContent = '0'; submitBtn.disabled = false; };

        trigger.addEventListener('click', open);
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
        textarea.addEventListener('input', () => { counter.textContent = textarea.value.length; });

        submitBtn.addEventListener('click', async () => {
            const message = textarea.value.trim();
            if (!message) { textarea.focus(); return; }
            submitBtn.disabled = true;
            try {
                await fetch('/api/feedback', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        category: select.value,
                        message,
                        email: state.user?.email || '',
                    }),
                });
                success.classList.remove('hidden');
                textarea.value = '';
                counter.textContent = '0';
                setTimeout(close, 2500);
            } catch {
                submitBtn.disabled = false;
            }
        });
    })();

    // Newsletter form
    (function initNewsletter() {
        const form = document.getElementById('newsletterForm');
        const emailInput = document.getElementById('newsletterEmail');
        const kvkkCheck = document.getElementById('newsletterKvkk');
        const submitBtn = document.getElementById('newsletterSubmit');
        const msg = document.getElementById('newsletterMsg');
        if (!form || !submitBtn) return;

        submitBtn.addEventListener('click', async () => {
            const email = (emailInput.value || '').trim();
            if (!email) { emailInput.focus(); return; }
            if (!kvkkCheck.checked) {
                msg.textContent = 'KVKK onayı zorunludur.';
                msg.classList.remove('hidden', 'newsletter-success');
                msg.classList.add('newsletter-error');
                return;
            }
            submitBtn.disabled = true;
            try {
                const res = await fetch('/api/newsletter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, kvkk_consent: true, source: 'footer' }),
                });
                const data = await res.json();
                msg.textContent = data.message || (data.ok ? 'Abone oldunuz!' : (data.error || 'Bir hata oluştu.'));
                msg.classList.remove('hidden', 'newsletter-error', 'newsletter-success');
                msg.classList.add(data.ok ? 'newsletter-success' : 'newsletter-error');
                if (data.ok) { emailInput.value = ''; kvkkCheck.checked = false; }
            } catch {
                msg.textContent = 'Bir hata oluştu, lütfen tekrar deneyin.';
                msg.classList.remove('hidden', 'newsletter-success');
                msg.classList.add('newsletter-error');
            } finally {
                submitBtn.disabled = false;
            }
        });
    })();


})();
