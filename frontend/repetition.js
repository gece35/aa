/**
 * Tekrar Sistemi - Spaced Repetition frontend module
 */
(function () {
    'use strict';

    const API = {
        lessons: '/api/repetition/lessons',
        upcoming: (days) => `/api/repetition/upcoming?days=${days}`,
        calendarStatus: '/api/repetition/calendar-status',
        lesson: (id) => `/api/repetition/lessons/${id}`,
    };

    const REP_COLORS = ['#8b5cf6', '#22d3ee', '#f59e0b', '#ef4444'];
    const REP_LABELS = ['1 gun sonra', '1 hafta sonra', '1 ay sonra', '3 ay sonra'];

    let state = {
        lessons: [],
        upcoming: [],
        upcomingDays: 7,
        calendarConfigured: false,
    };

    // ── DOM helpers ──────────────────────────────────────────────────────────

    const $ = (id) => document.getElementById(id);

    function formatDate(isoDate) {
        const d = new Date(isoDate + 'T00:00:00');
        return d.toLocaleDateString('tr-TR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    }

    function formatDateTime(isoStr) {
        const d = new Date(isoStr);
        return d.toLocaleString('tr-TR', {
            weekday: 'short', day: 'numeric', month: 'short',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function todayISO() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    function addDays(isoDate, n) {
        const d = new Date(isoDate + 'T00:00:00');
        d.setDate(d.getDate() + n);
        return d.toISOString().slice(0, 10);
    }

    function isWeekend(isoDate) {
        const day = new Date(isoDate + 'T00:00:00').getDay();
        return day === 0 || day === 6;
    }

    function repTime(isoDate) {
        return isWeekend(isoDate) ? '14:00' : '17:00';
    }

    function buildLocalSchedule(topic, subject, studyDate) {
        const offsets = [1, 7, 30, 90];
        return offsets.map((off, i) => {
            const date = addDays(studyDate, off);
            return {
                rep_num: i + 1,
                date,
                title: `Tekrar ${i + 1}/4: ${subject ? '[' + subject + '] ' : ''}${topic}`,
                start_time: `${date}T${repTime(date)}:00`,
                display_time: repTime(date),
                interval_label: REP_LABELS[i],
                color: REP_COLORS[i],
            };
        });
    }

    // ── Preview ───────────────────────────────────────────────────────────────

    function renderPreview() {
        const topic = $('repTopic').value.trim();
        const subject = $('repSubject').value.trim();
        const studyDate = $('repDate').value || todayISO();

        if (!topic) {
            $('repPreview').classList.add('hidden');
            return;
        }

        const schedule = buildLocalSchedule(topic, subject, studyDate);
        const previewEl = $('repPreview');
        const listEl = $('repPreviewList');

        listEl.innerHTML = schedule.map((rep) => `
            <div class="rep-preview-item" style="--rep-color:${rep.color}">
                <span class="rp-badge">${rep.rep_num}/4</span>
                <span class="rp-interval">${rep.interval_label}</span>
                <span class="rp-date">${formatDate(rep.date)}</span>
                <span class="rp-time">${rep.display_time}</span>
            </div>
        `).join('');

        previewEl.classList.remove('hidden');
    }

    // ── Upcoming list ─────────────────────────────────────────────────────────

    function renderUpcoming() {
        const el = $('repUpcomingList');
        if (!state.upcoming.length) {
            el.innerHTML = '<div class="empty">Bu aralikta tekrar yok.</div>';
            return;
        }

        el.innerHTML = state.upcoming.map((rep) => `
            <div class="rep-upcoming-item glass-inner" style="--rep-color:${REP_COLORS[(rep.rep_num || 1) - 1]}">
                <div class="rui-left">
                    <span class="rui-badge">Tekrar ${rep.rep_num}/4</span>
                    <span class="rui-topic">${escHtml(rep.topic)}</span>
                    ${rep.subject ? `<span class="rui-subject">${escHtml(rep.subject)}</span>` : ''}
                </div>
                <div class="rui-right">
                    <span class="rui-date">${formatDate(rep.date)}</span>
                    <span class="rui-time">${repTime(rep.date)}</span>
                </div>
            </div>
        `).join('');
    }

    // ── Lessons list ──────────────────────────────────────────────────────────

    function renderLessons() {
        const el = $('repLessonsList');
        if (!state.lessons.length) {
            el.innerHTML = '<div class="empty">Henuz konu eklenmedi.</div>';
            return;
        }

        el.innerHTML = state.lessons.slice().reverse().map((lesson) => {
            const syncBadge = lesson.synced_event_ids && lesson.synced_event_ids.length
                ? '<span class="rep-synced-badge">Takvimde</span>'
                : '';
            return `
                <div class="rep-lesson-item glass-inner" data-id="${lesson.id}">
                    <div class="rli-header">
                        <div class="rli-meta">
                            <span class="rli-topic">${escHtml(lesson.topic)}</span>
                            ${lesson.subject ? `<span class="rli-subject">${escHtml(lesson.subject)}</span>` : ''}
                            ${syncBadge}
                        </div>
                        <div class="rli-actions">
                            <span class="rli-date">${formatDate(lesson.study_date)}</span>
                            <button class="rep-del-btn" data-id="${lesson.id}" title="Sil">&times;</button>
                        </div>
                    </div>
                    <div class="rli-schedule">
                        ${lesson.schedule.map((rep) => `
                            <span class="rli-rep-dot" style="background:${REP_COLORS[rep.rep_num - 1]}" title="Tekrar ${rep.rep_num}: ${formatDate(rep.date)}">
                                ${rep.rep_num}
                            </span>
                        `).join('')}
                    </div>
                </div>
            `;
        }).join('');

        el.querySelectorAll('.rep-del-btn').forEach((btn) => {
            btn.addEventListener('click', () => deleteLesson(btn.dataset.id));
        });
    }

    function escHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ── API calls ─────────────────────────────────────────────────────────────

    async function loadLessons() {
        try {
            const res = await fetch(API.lessons);
            const data = await res.json();
            state.lessons = data.lessons || [];
            renderLessons();
        } catch (e) {
            console.error('Dersler yuklenemedi', e);
        }
    }

    async function loadUpcoming() {
        try {
            const res = await fetch(API.upcoming(state.upcomingDays));
            const data = await res.json();
            state.upcoming = data.upcoming || [];
            renderUpcoming();
        } catch (e) {
            console.error('Yaklasan tekrarlar yuklenemedi', e);
        }
    }

    async function checkCalendarStatus() {
        try {
            const res = await fetch(API.calendarStatus);
            const data = await res.json();
            state.calendarConfigured = data.configured;
            const statusEl = $('repCalendarStatus');
            if (data.configured) {
                statusEl.textContent = 'Bagli';
                statusEl.className = 'rep-cal-status rep-cal-ok';
            } else {
                statusEl.textContent = 'Bagli degil (GOOGLE_CALENDAR_CREDENTIALS gerekli)';
                statusEl.className = 'rep-cal-status rep-cal-warn';
            }
        } catch (e) {
            console.error('Takvim durumu kontrol edilemedi', e);
        }
    }

    async function addLesson() {
        const topic = $('repTopic').value.trim();
        const subject = $('repSubject').value.trim();
        const studyDate = $('repDate').value || todayISO();
        const syncCalendar = $('repSyncCalendar').checked;

        if (!topic) {
            $('repTopic').focus();
            return;
        }

        const btn = $('repAddBtn');
        btn.disabled = true;
        btn.textContent = 'Ekleniyor...';

        try {
            const res = await fetch(API.lessons, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic, subject, study_date: studyDate, sync_calendar: syncCalendar }),
            });

            if (!res.ok) {
                const err = await res.json();
                alert('Hata: ' + (err.error || 'Bilinmeyen hata'));
                return;
            }

            const data = await res.json();

            if (syncCalendar && data.calendar_sync) {
                const sync = data.calendar_sync;
                if (sync.synced) {
                    alert(`Konu eklendi! ${sync.event_ids.length} takvim etkinligi olusturuldu.`);
                } else if (sync.error) {
                    alert(`Konu eklendi fakat takvim hatasi: ${sync.error}`);
                }
            }

            $('repTopic').value = '';
            $('repSubject').value = '';
            $('repDate').value = todayISO();
            $('repPreview').classList.add('hidden');

            await loadLessons();
            await loadUpcoming();
        } catch (e) {
            alert('Istek basarisiz: ' + e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Ekle ve Takvim Olustur';
        }
    }

    async function deleteLesson(id) {
        if (!confirm('Bu konuyu ve tekrar planini silmek istiyor musunuz?')) return;
        try {
            await fetch(API.lesson(id), { method: 'DELETE' });
            await loadLessons();
            await loadUpcoming();
        } catch (e) {
            console.error('Silme hatasi', e);
        }
    }

    // ── Init ──────────────────────────────────────────────────────────────────

    function initRepetitionTab() {
        $('repDate').value = todayISO();

        $('repTopic').addEventListener('input', renderPreview);
        $('repSubject').addEventListener('input', renderPreview);
        $('repDate').addEventListener('change', renderPreview);
        $('repAddBtn').addEventListener('click', addLesson);

        document.querySelectorAll('.rep-days-filter .chip').forEach((btn) => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.rep-days-filter .chip').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                state.upcomingDays = parseInt(btn.dataset.days, 10);
                loadUpcoming();
            });
        });

        checkCalendarStatus();
        loadLessons();
        loadUpcoming();
    }

    // Run when the repetition tab becomes active
    const tabBtn = document.querySelector('[data-tab="repetition"]');
    if (tabBtn) {
        tabBtn.addEventListener('click', () => {
            // Small delay to ensure tab is visible
            setTimeout(() => {
                loadLessons();
                loadUpcoming();
            }, 50);
        });
    }

    // Initialize immediately if DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRepetitionTab);
    } else {
        initRepetitionTab();
    }
})();
