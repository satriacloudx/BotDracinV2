<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DramaBox - Download Drama Full Episode</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/FileSaver.js/2.0.5/FileSaver.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', sans-serif; }
        .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    
    <!-- Header -->
    <header class="sticky top-0 z-50 bg-gray-800 border-b border-gray-700">
        <div class="max-w-6xl mx-auto px-4 py-3">
            <div class="flex items-center gap-4">
                <h1 onclick="goHome()" class="text-xl font-bold text-purple-400 cursor-pointer flex items-center gap-2">
                    <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M4 8H2v12c0 1.1.9 2 2 2h12v-2H4V8zm16-6H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8 12.5v-9l6 4.5-6 4.5z"/></svg>
                    DramaBox
                </h1>
                <div class="flex-1 max-w-md relative">
                    <input type="text" id="searchInput" placeholder="Cari drama..." 
                        class="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-purple-500"
                        oninput="handleSearch(this.value)" onkeypress="if(event.key==='Enter') doSearch()">
                    <div id="suggestions" class="hidden absolute top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto"></div>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main id="app" class="max-w-6xl mx-auto px-4 py-6"></main>

    <!-- Download Modal -->
    <div id="downloadModal" class="fixed inset-0 z-[100] hidden">
        <div class="absolute inset-0 bg-black/80" onclick="closeDownloadModal()"></div>
        <div class="relative h-full flex items-center justify-center p-4">
            <div class="bg-gray-800 rounded-xl w-full max-w-lg overflow-hidden shadow-2xl">
                <div class="p-4 border-b border-gray-700 flex justify-between items-center">
                    <h3 class="font-bold text-lg">Download ZIP</h3>
                    <button onclick="closeDownloadModal()" class="text-gray-400 hover:text-white text-2xl">&times;</button>
                </div>
                <div class="p-4">
                    <div id="dlDramaInfo" class="flex items-center gap-3 mb-4 p-3 bg-gray-700 rounded-lg">
                        <img id="dlCover" src="" class="w-12 h-16 object-cover rounded">
                        <div>
                            <h4 id="dlTitle" class="font-bold"></h4>
                            <p id="dlEpCount" class="text-sm text-gray-400"></p>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <div class="flex justify-between text-sm mb-1">
                            <span id="dlStatus">Mempersiapkan...</span>
                            <span id="dlProgress">0%</span>
                        </div>
                        <div class="h-3 bg-gray-700 rounded-full overflow-hidden">
                            <div id="dlBar" class="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all duration-300" style="width:0%"></div>
                        </div>
                        <p id="dlDetail" class="text-xs text-gray-500 mt-2 text-center"></p>
                    </div>
                    
                    <div id="dlLog" class="max-h-40 overflow-y-auto text-xs space-y-1 mb-4 bg-gray-900 rounded-lg p-3"></div>
                    
                    <div class="flex gap-2">
                        <button onclick="closeDownloadModal()" id="btnClose" class="hidden flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium">Tutup</button>
                        <button onclick="cancelDownload()" id="btnCancel" class="flex-1 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium">Batalkan</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Video Modal -->
    <div id="videoModal" class="fixed inset-0 z-[100] hidden">
        <div class="absolute inset-0 bg-black/90" onclick="closeVideo()"></div>
        <div class="relative h-full flex items-center justify-center p-4">
            <div class="bg-gray-800 rounded-xl w-full max-w-4xl overflow-hidden shadow-2xl">
                <div class="p-3 border-b border-gray-700 flex justify-between items-center">
                    <h3 id="videoTitle" class="font-bold truncate"></h3>
                    <button onclick="closeVideo()" class="text-gray-400 hover:text-white text-2xl">&times;</button>
                </div>
                <div class="flex flex-col lg:flex-row">
                    <div class="flex-1 bg-black">
                        <video id="videoPlayer" class="w-full aspect-video" controls></video>
                    </div>
                    <div class="lg:w-64 p-3 border-t lg:border-t-0 lg:border-l border-gray-700 max-h-80 lg:max-h-[60vh] overflow-y-auto">
                        <p class="text-sm text-gray-400 mb-2">Episode:</p>
                        <div id="epList" class="grid grid-cols-6 lg:grid-cols-4 gap-1"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const API = 'https://restxdb.onrender.com/api';
        const LANG = 'in';
        
        let state = {
            drama: null,
            dramaId: null,
            episodes: [],
            currentEp: 0,
            hls: null,
            cancelled: false,
            downloading: false
        };

        const $ = id => document.getElementById(id);

        // ========== API ==========
        async function api(endpoint) {
            try {
                const res = await fetch(`${API}${endpoint}`);
                return await res.json();
            } catch(e) {
                console.error('API Error:', e);
                return null;
            }
        }

        async function getVideoUrl(bookId, chapterIndex) {
            // Try GET
            try {
                const res = await fetch(`${API}/watch/${bookId}/${chapterIndex}?lang=${LANG}&source=search_result`);
                const data = await res.json();
                if (data?.data?.videoUrl) return data.data.videoUrl;
            } catch(e) {}
            
            // Try POST
            try {
                const res = await fetch(`${API}/watch/player?lang=${LANG}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bookId: String(bookId), chapterIndex, lang: LANG })
                });
                const data = await res.json();
                if (data?.data?.videoUrl) return data.data.videoUrl;
            } catch(e) {}
            
            return null;
        }

        // ========== HELPERS ==========
        const getTitle = d => d?.bookName || d?.name || d?.title || 'Untitled';
        const getCover = d => d?.cover || d?.coverWap || '';
        const getId = d => d?.bookId || d?.id || '';
        const getEpCount = d => d?.chapterCount || d?.seriesCount || 0;

        function dramaCard(d, rank = null) {
            return `
            <div onclick="openDrama('${getId(d)}')" class="cursor-pointer group">
                <div class="relative rounded-lg overflow-hidden bg-gray-800">
                    ${rank !== null ? `<div class="absolute top-1 left-1 z-10 w-6 h-6 ${rank < 3 ? 'bg-yellow-500' : 'bg-gray-900/80'} rounded flex items-center justify-center text-xs font-bold">${rank + 1}</div>` : ''}
                    <img src="${getCover(d)}" alt="${getTitle(d)}" class="w-full aspect-[2/3] object-cover group-hover:scale-105 transition-transform duration-300" onerror="this.src='https://placehold.co/200x300/374151/666?text=No+Image'">
                    <div class="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                        <div class="w-12 h-12 rounded-full bg-purple-500 flex items-center justify-center">
                            <svg class="w-6 h-6 ml-1" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                        </div>
                    </div>
                    <div class="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black to-transparent">
                        <h3 class="text-sm font-medium line-clamp-2">${getTitle(d)}</h3>
                        <p class="text-xs text-gray-400">${getEpCount(d)} Episode</p>
                    </div>
                </div>
            </div>`;
        }

        function grid(items, withRank = false) {
            if (!items?.length) return '<p class="text-gray-500 text-center py-10">Tidak ada data</p>';
            return `<div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">${items.map((d, i) => dramaCard(d, withRank ? i : null)).join('')}</div>`;
        }

        function skeleton(n = 12) {
            return `<div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">${Array(n).fill('<div class="aspect-[2/3] bg-gray-800 rounded-lg animate-pulse"></div>').join('')}</div>`;
        }

        // ========== PAGES ==========
        async function goHome() {
            state.drama = null;
            $('app').innerHTML = `
                <div class="space-y-8">
                    <section>
                        <h2 class="text-lg font-bold mb-3 flex items-center gap-2">⭐ Rekomendasi</h2>
                        <div id="secRecommend">${skeleton()}</div>
                    </section>
                    <section>
                        <h2 class="text-lg font-bold mb-3 flex items-center gap-2">🔥 Populer</h2>
                        <div id="secPopular">${skeleton(6)}</div>
                    </section>
                    <section>
                        <h2 class="text-lg font-bold mb-3 flex items-center gap-2">🕐 Terbaru</h2>
                        <div id="secNew">${skeleton()}</div>
                    </section>
                </div>`;

            const [rec, pop, newD] = await Promise.all([
                api(`/foryou/1?lang=${LANG}`),
                api(`/rank/1?lang=${LANG}`),
                api(`/new/1?lang=${LANG}&pageSize=12`)
            ]);

            $('secRecommend').innerHTML = grid(rec?.data?.list?.slice(0, 12) || []);
            $('secPopular').innerHTML = grid(pop?.data?.list?.slice(0, 6) || [], true);
            $('secNew').innerHTML = grid(newD?.data?.list?.slice(0, 12) || []);
        }

        // ========== SEARCH ==========
        let searchTimer;
        async function handleSearch(val) {
            clearTimeout(searchTimer);
            if (val.length < 2) { $('suggestions').classList.add('hidden'); return; }
            searchTimer = setTimeout(async () => {
                const res = await api(`/suggest/${encodeURIComponent(val)}?lang=${LANG}`);
                const list = res?.data || [];
                if (list.length) {
                    $('suggestions').innerHTML = list.map(s => `<div onclick="pickSuggestion('${s}')" class="px-3 py-2 hover:bg-gray-700 cursor-pointer text-sm">${s}</div>`).join('');
                    $('suggestions').classList.remove('hidden');
                } else {
                    $('suggestions').classList.add('hidden');
                }
            }, 300);
        }

        function pickSuggestion(val) {
            $('searchInput').value = val;
            $('suggestions').classList.add('hidden');
            doSearch();
        }

        async function doSearch() {
            const q = $('searchInput').value.trim();
            if (!q) return;
            $('suggestions').classList.add('hidden');
            state.drama = null;
            $('app').innerHTML = `<h2 class="text-lg font-bold mb-3">🔍 Hasil: "${q}"</h2><div id="results">${skeleton()}</div>`;
            const res = await api(`/search/${encodeURIComponent(q)}/1?lang=${LANG}`);
            $('results').innerHTML = grid(res?.data?.list || []);
        }

        // ========== DRAMA DETAIL ==========
        async function openDrama(id) {
            if (!id) return;
            state.dramaId = id;
            $('app').innerHTML = '<div class="flex justify-center py-20"><div class="w-10 h-10 border-4 border-purple-500 border-t-transparent rounded-full animate-spin"></div></div>';

            const res = await api(`/chapters/${id}?lang=${LANG}`);
            if (!res?.data) {
                $('app').innerHTML = '<p class="text-center py-20 text-gray-500">Gagal memuat drama</p>';
                return;
            }

            const drama = res.data;
            state.drama = drama;
            state.episodes = drama.chapterList || [];

            const title = getTitle(drama);
            const cover = getCover(drama);
            const desc = drama.introduction || '';
            const eps = state.episodes;

            $('app').innerHTML = `
                <button onclick="goHome()" class="text-purple-400 hover:underline mb-4 flex items-center gap-1">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
                    Kembali
                </button>
                
                <div class="bg-gray-800 rounded-xl p-4 mb-4">
                    <div class="flex gap-4">
                        <img src="${cover}" alt="${title}" class="w-32 rounded-lg object-cover" onerror="this.src='https://placehold.co/200x300/374151/666?text=No+Image'">
                        <div class="flex-1">
                            <h1 class="text-xl font-bold mb-2">${title}</h1>
                            <p class="text-sm text-gray-400 mb-3 line-clamp-2">${desc}</p>
                            <p class="text-sm text-gray-400 mb-4">📺 ${eps.length} Episode</p>
                            <div class="flex flex-wrap gap-2">
                                ${eps.length > 0 ? `
                                    <button onclick="playEp(0)" class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg font-medium flex items-center gap-2">
                                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                                        Tonton
                                    </button>
                                    <button onclick="startDownload()" class="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-medium flex items-center gap-2">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
                                        Download ZIP (${eps.length} EP)
                                    </button>
                                ` : '<p class="text-gray-500">Tidak ada episode</p>'}
                            </div>
                        </div>
                    </div>
                </div>
                
                ${eps.length > 0 ? `
                    <div class="bg-gray-800 rounded-xl p-4">
                        <h2 class="font-bold mb-3">Daftar Episode</h2>
                        <div class="grid grid-cols-8 sm:grid-cols-10 md:grid-cols-12 gap-2">
                            ${eps.map((ep, i) => `<button onclick="playEp(${i})" class="aspect-square rounded-lg bg-gray-700 hover:bg-purple-600 flex items-center justify-center text-sm font-medium transition">${i + 1}</button>`).join('')}
                        </div>
                    </div>
                ` : ''}
            `;
        }

        // ========== VIDEO PLAYER ==========
        async function playEp(index) {
            state.currentEp = index;
            const ep = state.episodes[index];
            const chapterIndex = ep?.chapterIndex ?? index;

            $('videoModal').classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            $('videoTitle').textContent = `${getTitle(state.drama)} - Episode ${index + 1}`;
            $('videoPlayer').src = '';

            $('epList').innerHTML = state.episodes.map((_, i) => 
                `<button onclick="playEp(${i})" class="aspect-square rounded text-xs font-medium ${i === index ? 'bg-purple-600' : 'bg-gray-700 hover:bg-gray-600'}">${i + 1}</button>`
            ).join('');

            const url = await getVideoUrl(state.dramaId, chapterIndex);
            if (url) {
                const player = $('videoPlayer');
                if (state.hls) { state.hls.destroy(); state.hls = null; }

                if (url.includes('.m3u8') && Hls.isSupported()) {
                    state.hls = new Hls();
                    state.hls.loadSource(url);
                    state.hls.attachMedia(player);
                    state.hls.on(Hls.Events.MANIFEST_PARSED, () => player.play().catch(() => {}));
                } else {
                    player.src = url;
                    player.onloadeddata = () => player.play().catch(() => {});
                }
                
                player.onended = () => {
                    if (state.currentEp + 1 < state.episodes.length) playEp(state.currentEp + 1);
                };
            }
        }

        function closeVideo() {
            $('videoModal').classList.add('hidden');
            document.body.style.overflow = '';
            $('videoPlayer').pause();
            $('videoPlayer').src = '';
            if (state.hls) { state.hls.destroy(); state.hls = null; }
        }

        // ========== DOWNLOAD ZIP ==========
        async function startDownload() {
            if (state.downloading) return;
            state.downloading = true;
            state.cancelled = false;

            const eps = state.episodes;
            const title = getTitle(state.drama);
            const safeTitle = title.replace(/[^a-zA-Z0-9\s]/g, '').replace(/\s+/g, '_');

            // Show modal
            $('downloadModal').classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            $('dlCover').src = getCover(state.drama);
            $('dlTitle').textContent = title;
            $('dlEpCount').textContent = `${eps.length} Episode`;
            $('btnClose').classList.add('hidden');
            $('btnCancel').classList.remove('hidden');
            $('dlLog').innerHTML = '';
            $('dlBar').style.width = '0%';
            $('dlProgress').textContent = '0%';

            const log = (msg, type = 'info') => {
                const colors = { info: 'text-gray-400', success: 'text-green-400', error: 'text-red-400', warning: 'text-yellow-400' };
                $('dlLog').innerHTML += `<div class="${colors[type]}">${msg}</div>`;
                $('dlLog').scrollTop = $('dlLog').scrollHeight;
            };

            const updateProgress = (current, total, status) => {
                const pct = Math.round((current / total) * 100);
                $('dlBar').style.width = pct + '%';
                $('dlProgress').textContent = pct + '%';
                $('dlStatus').textContent = status;
            };

            log('📡 Mengambil link video...');
            
            const zip = new JSZip();
            let success = 0;
            let failed = 0;

            for (let i = 0; i < eps.length; i++) {
                if (state.cancelled) {
                    log('❌ Download dibatalkan', 'warning');
                    break;
                }

                const ep = eps[i];
                const chapterIndex = ep?.chapterIndex ?? i;
                const filename = `${safeTitle}_EP${String(i + 1).padStart(2, '0')}.mp4`;

                updateProgress(i, eps.length * 2, `Mengambil link EP ${i + 1}/${eps.length}`);
                $('dlDetail').textContent = `Episode ${i + 1} dari ${eps.length}`;

                log(`📺 EP ${i + 1}: Mengambil link...`);

                const url = await getVideoUrl(state.dramaId, chapterIndex);
                
                if (!url) {
                    log(`❌ EP ${i + 1}: Gagal mendapat link`, 'error');
                    failed++;
                    continue;
                }

                log(`⬇️ EP ${i + 1}: Downloading...`);
                updateProgress(eps.length + i, eps.length * 2, `Download EP ${i + 1}/${eps.length}`);

                try {
                    const response = await fetch(url);
                    if (!response.ok) throw new Error('Fetch failed');

                    const contentLength = +response.headers.get('content-length') || 0;
                    const reader = response.body.getReader();
                    const chunks = [];
                    let loaded = 0;

                    while (true) {
                        if (state.cancelled) break;
                        const { done, value } = await reader.read();
                        if (done) break;
                        chunks.push(value);
                        loaded += value.length;
                        if (contentLength > 0) {
                            $('dlDetail').textContent = `EP ${i + 1}: ${Math.round(loaded / 1024 / 1024)}MB / ${Math.round(contentLength / 1024 / 1024)}MB`;
                        }
                    }

                    if (state.cancelled) break;

                    const blob = new Blob(chunks, { type: 'video/mp4' });
                    zip.file(filename, blob);
                    success++;
                    log(`✅ EP ${i + 1}: OK (${Math.round(blob.size / 1024 / 1024)}MB)`, 'success');
                } catch (e) {
                    log(`❌ EP ${i + 1}: Download gagal`, 'error');
                    failed++;
                }

                // Small delay to avoid overwhelming the server
                await new Promise(r => setTimeout(r, 300));
            }

            if (state.cancelled) {
                finishDownload();
                return;
            }

            if (success === 0) {
                log('❌ Tidak ada episode yang berhasil didownload', 'error');
                finishDownload();
                return;
            }

            // Create ZIP
            log(`📦 Membuat file ZIP (${success} episode)...`);
            updateProgress(95, 100, 'Membuat ZIP...');

            try {
                const zipBlob = await zip.generateAsync({ 
                    type: 'blob',
                    compression: 'DEFLATE',
                    compressionOptions: { level: 1 }
                }, (meta) => {
                    $('dlDetail').textContent = `Kompres: ${Math.round(meta.percent)}%`;
                });

                saveAs(zipBlob, `${safeTitle}_${success}EP.zip`);
                updateProgress(100, 100, 'Selesai!');
                log(`🎉 Download selesai! ${success} episode (${Math.round(zipBlob.size / 1024 / 1024)}MB)`, 'success');
                if (failed > 0) log(`⚠️ ${failed} episode gagal`, 'warning');
            } catch (e) {
                log('❌ Gagal membuat ZIP', 'error');
            }

            finishDownload();
        }

        function finishDownload() {
            state.downloading = false;
            $('btnClose').classList.remove('hidden');
            $('btnCancel').classList.add('hidden');
        }

        function cancelDownload() {
            state.cancelled = true;
            $('dlStatus').textContent = 'Membatalkan...';
        }

        function closeDownloadModal() {
            if (state.downloading && !state.cancelled) {
                if (!confirm('Download sedang berjalan. Yakin batalkan?')) return;
                state.cancelled = true;
            }
            $('downloadModal').classList.add('hidden');
            document.body.style.overflow = '';
            state.downloading = false;
        }

        // ========== INIT ==========
        document.addEventListener('click', e => {
            if (!e.target.closest('#searchInput') && !e.target.closest('#suggestions')) {
                $('suggestions').classList.add('hidden');
            }
        });

        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                closeVideo();
                closeDownloadModal();
            }
        });

        goHome();
    </script>
</body>
</html>
