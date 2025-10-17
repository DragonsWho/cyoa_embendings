document.addEventListener('DOMContentLoaded', () => {
    // Получаем элементы со страницы
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-query');
    const searchResultsContainer = document.getElementById('search-results');
    const statsContainer = document.getElementById('stats-container');
    const allGamesListContainer = document.getElementById('all-games-list');
    const gameCountSpan = document.getElementById('game-count');

    /**
     * Загружает и отображает статистику с сервера.
     */
    const loadStats = async () => {
        try {
            const response = await fetch('/stats');
            if (!response.ok) throw new Error('Ошибка сети при загрузке статистики');
            
            const data = await response.json();
            statsContainer.innerHTML = `<p><strong>Всего игр в базе:</strong> ${data.total_games} | <strong>Проиндексировано:</strong> ${data.indexed_games}</p>`;
        } catch (error) {
            statsContainer.innerHTML = `<p style="color: #ef5350;">Не удалось загрузить статистику.</p>`;
            console.error(error);
        }
    };

    /**
     * Загружает и отображает полный список игр.
     */
    const loadAllGames = async () => {
        try {
            const response = await fetch('/games');
            if (!response.ok) throw new Error('Ошибка сети при загрузке списка игр');

            const games = await response.json();
            gameCountSpan.textContent = games.length;

            if (games.length === 0) {
                allGamesListContainer.innerHTML = '<p>В базе пока нет игр.</p>';
                return;
            }

            const list = document.createElement('ul');
            games.forEach(game => {
                const listItem = document.createElement('li');
                // Простое отображение названия
                listItem.textContent = game.title;
                list.appendChild(listItem);
            });
            
            allGamesListContainer.innerHTML = ''; // Очищаем "Загрузка..."
            allGamesListContainer.appendChild(list);

        } catch (error) {
            allGamesListContainer.innerHTML = `<p style="color: #ef5350;">Не удалось загрузить список игр.</p>`;
            console.error(error);
        }
    };

    /**
     * Выполняет поиск по запросу пользователя.
     */
    const performSearch = async (event) => {
        event.preventDefault(); // Предотвращаем стандартную отправку формы
        const query = searchInput.value.trim();
        
        if (query.length < 3) {
            searchResultsContainer.innerHTML = '<p>Запрос должен содержать минимум 3 символа.</p>';
            return;
        }

        searchResultsContainer.innerHTML = '<p>Поиск...</p>';

        try {
            const encodedQuery = encodeURIComponent(query);
            const response = await fetch(`/search?q=${encodedQuery}`);
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Произошла ошибка на сервере');
            }
            
            displayResults(result.results);

        } catch (error) {
            searchResultsContainer.innerHTML = `<p style="color: #ef5350;">Ошибка: ${error.message}</p>`;
            console.error(error);
        }
    };

    /**
     * Отображает результаты поиска на странице.
     * @param {Array} results - Массив объектов с результатами.
     */
    const displayResults = (results) => {
        if (!results || results.length === 0) {
            searchResultsContainer.innerHTML = '<p>Ничего не найдено. Попробуйте другой запрос.</p>';
            return;
        }

        const list = document.createElement('ul');
        results.forEach(game => {
            const listItem = document.createElement('li');
            listItem.className = 'result-item';
            // Используем правильные поля из ответа API: title, url, score
            listItem.innerHTML = `
                <a href="${game.url}" target="_blank" title="ID: ${game.id}">${game.title}</a>
                <span>Similarity: ${game.score}%</span>
            `;
            list.appendChild(listItem);
        });

        searchResultsContainer.innerHTML = ''; // Очищаем "Поиск..."
        searchResultsContainer.appendChild(list);
    };

    // --- Привязка событий ---
    searchForm.addEventListener('submit', performSearch);

    // --- Первоначальная загрузка данных при открытии страницы ---
    loadStats();
    loadAllGames();
});