document.addEventListener('DOMContentLoaded', () => {
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-query');
    const resultsDiv = document.getElementById('search-results');
    const statsDiv = document.getElementById('stats-container');

    // --- Загрузка статистики (без изменений) ---
    fetch('/stats').then(r => r.json()).then(data => {
        statsDiv.innerHTML = `
            Total: <b>${data.total}</b> | 
            With Text: <b>${data.with_text}</b> | 
            With AI Summary: <b style="color:#4caf50">${data.with_summary}</b> | 
            Indexed: <b>${data.indexed}</b>
        `;
    });

    // --- Обработчик формы поиска (без изменений) ---
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = searchInput.value.trim();
        const mode = document.querySelector('input[name="search-mode"]:checked').value;

        if (query.length < 2) return;
        resultsDiv.innerHTML = '<p>Searching analyzing semantics...</p>';

        try {
            const res = await fetch(`/search?q=${encodeURIComponent(query)}&mode=${mode}`);
            const data = await res.json();

            if (data.results.length === 0) {
                resultsDiv.innerHTML = `<p>No results found in <b>${mode}</b> mode.</p>`;
                return;
            }

            const html = data.results.map(game => {
                const snippetHtml = game.snippet ? `<div class="result-snippet">AI Summary: "${game.snippet}"</div>` : '';
                const matchClass = game.match_type === 'summary' ? 'summary' : 'text';
                const matchLabel = game.match_type === 'summary' ? 'AI Match' : 'Text Match';

                return `
                    <div class="result-item">
                        <div class="result-header">
                            <a href="${game.url}" target="_blank" class="result-title">${game.title}</a>
                            <div class="result-meta">
                                <span class="badge ${matchClass}">${matchLabel}</span>
                                <span class="score">${game.score}%</span>
                            </div>
                        </div>
                        ${snippetHtml}
                    </div>
                `;
            }).join('');

            resultsDiv.innerHTML = `<p style="color:#888; margin-bottom:10px">Results using <b>${data.mode_used}</b> mode:</p>` + html;
        } catch (err) {
            resultsDiv.innerHTML = `<p style="color:red">Error: ${err.message}</p>`;
        }
    });

    // --- НОВАЯ ФУНКЦИЯ: Загрузка и отображение списка всех игр ---
    async function loadAllGames() {
        const gamesListDiv = document.getElementById('all-games-list');
        try {
            // Создаем новый эндпоинт /games на сервере
            const response = await fetch('/games'); 
            const games = await response.json();

            if (games.length === 0) {
                gamesListDiv.innerHTML = '<p>No games found in the database.</p>';
                return;
            }

            // Создаем HTML для каждой игры
            const gamesHtml = games.map((game, index) => {
                const indexedStatus = game.is_indexed
                    ? '<span class="status-indicator indexed">Indexed</span>'
                    : '<span class="status-indicator not-indexed">Not Indexed</span>';
                
                // Если summary есть - создаем кликабельный элемент, если нет - просто метку
                const summaryStatus = game.has_summary
                    ? `<span class="summary-toggle" data-target="summary-${index}">Summary</span>`
                    : '<span class="status-indicator no-summary">No Summary</span>';

                // Если summary есть - создаем скрытый div с его текстом
                const summaryContent = game.has_summary
                    ? `<div class="summary-content" id="summary-${index}">${game.summary.replace(/\n/g, '<br>')}</div>`
                    : '';

                return `
                    <div class="game-item-list">
                        <div class="game-header-list">
                            <span class="game-title-list">${game.title}</span>
                            <div class="game-meta-list">
                                ${indexedStatus}
                                ${summaryStatus}
                            </div>
                        </div>
                        ${summaryContent}
                    </div>
                `;
            }).join('');

            gamesListDiv.innerHTML = gamesHtml;

            // Добавляем обработчики кликов для всех кнопок "Summary"
            document.querySelectorAll('.summary-toggle').forEach(toggle => {
                toggle.addEventListener('click', () => {
                    const targetId = toggle.getAttribute('data-target');
                    const summaryContent = document.getElementById(targetId);
                    if (summaryContent) {
                        // Переключаем класс 'visible' для показа/скрытия
                        summaryContent.classList.toggle('visible');
                    }
                });
            });

        } catch (error) {
            gamesListDiv.innerHTML = `<p style="color:red">Error loading game list: ${error.message}</p>`;
        }
    }

    // Вызываем новую функцию при загрузке страницы
    loadAllGames();
});