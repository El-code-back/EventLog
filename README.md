# EventLog MVP

MVP-платформа для личных и командных активностей: регистрация по имени, события, команды, приватность, друзья, приглашения и аналитика участия.

## Запуск

```powershell
python server.py
```

Откройте `http://127.0.0.1:8000`.

## Что внутри

- `server.py` — Django-подобный REST backend на Python stdlib + SQLite.
- `static/index.html` — SPA-интерфейс.
- `static/app.js` — клиентская логика, календарь, графики, CRUD, друзья и приглашения.
- `static/styles.css` — mobile-first UI без placeholder-логотипов.

В реальном UI нет шаблонных пользователей, команд или событий. При первом запуске база создаётся пустой, а пользователь добавляет живые данные сам.

## API

- `POST /api/register` — регистрация по имени.
- `GET /api/events` и `POST /api/events` — список и создание событий.
- `GET /api/events/:id` — detail события.
- `POST /api/events/:id/status` — статус участия.
- `POST /api/events/:id/notes` — заметки пользователя.
- `GET /api/teams`, `POST /api/teams`, `GET /api/teams/:id` — команды.
- `GET /api/dashboard` — календарь, лента и графики.
- `GET /api/analytics/user/:id` — агрегаты участия пользователя.
- `GET /api/analytics/team/:id` — агрегаты участия команды.
- `GET /api/users/:id/profile` — профиль, друзья, команды, приглашения.
- `GET /api/users/search` — поиск пользователей по имени и коду.
- `POST /api/friends/request`, `POST /api/friends/respond` — дружба.
- `POST /api/team-invites`, `POST /api/team-invites/respond` — приглашения в команды.
