const api = {
  get: (path) => fetch(path).then(check),
  post: (path, body) =>
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(check),
};

async function check(response) {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Ошибка запроса");
  return payload;
}

const labels = {
  hackathon: "Хакатон",
  webinar: "Вебинар",
  conference: "Конференция",
  workshop: "Воркшоп",
  challenge: "Челлендж",
  meeting: "Митинг",
  local: "Локальный",
  interuniversity: "Межвузовский",
  international: "Международный",
  online: "Онлайн",
  planned: "Планирую",
  attended: "Участвовал",
  cancelled: "Отменил",
  interested: "Интересно",
  all: "Видно всем",
  friends: "Друзьям / командам",
  team: "Только команде",
  private: "Только мне",
  team_only: "Участники команды",
  public_anonymous: "Все, анонимно",
  hidden: "Скрыто",
};

const typeColors = {
  hackathon: "#e9564f",
  webinar: "#2d7dd2",
  conference: "#7768ae",
  workshop: "#f0a202",
  challenge: "#00a896",
  meeting: "#5f6c7b",
};

const state = {
  user: JSON.parse(localStorage.getItem("eventlog:user") || "null"),
  view: "all",
  page: "dashboard",
  meta: null,
  events: [],
  teams: [],
  activeTeam: null,
  profile: null,
  inviteTarget: null,
  analytics: null,
  charts: {},
  calendar: null,
};

const els = {
  currentUser: document.querySelector("#currentUser"),
  nameInput: document.querySelector("#nameInput"),
  pinInput: document.querySelector("#pinInput"),
  registerBtn: document.querySelector("#registerBtn"),
  pageTitle: document.querySelector("#pageTitle"),
  pageLead: document.querySelector("#pageLead"),
  navTabs: document.querySelector(".nav-tabs"),
  viewMode: document.querySelector("#viewMode"),
  searchInput: document.querySelector("#searchInput"),
  typeFilter: document.querySelector("#typeFilter"),
  levelFilter: document.querySelector("#levelFilter"),
  tagFilter: document.querySelector("#tagFilter"),
  eventList: document.querySelector("#eventList"),
  recentFeed: document.querySelector("#recentFeed"),
  summaryStats: document.querySelector("#summaryStats"),
  collaboratorsList: document.querySelector("#collaboratorsList"),
  timelineList: document.querySelector("#timelineList"),
  openCreateBtn: document.querySelector("#openCreateBtn"),
  closeCreateBtn: document.querySelector("#closeCreateBtn"),
  eventDialog: document.querySelector("#eventDialog"),
  eventForm: document.querySelector("#eventForm"),
  detailDialog: document.querySelector("#detailDialog"),
  eventDetail: document.querySelector("#eventDetail"),
  profileBox: document.querySelector("#profileBox"),
  friendNameInput: document.querySelector("#friendNameInput"),
  friendCodeInput: document.querySelector("#friendCodeInput"),
  findFriendBtn: document.querySelector("#findFriendBtn"),
  friendSearchResults: document.querySelector("#friendSearchResults"),
  friendsList: document.querySelector("#friendsList"),
  invitesList: document.querySelector("#invitesList"),
  teamName: document.querySelector("#teamName"),
  teamMembers: document.querySelector("#teamMembers"),
  teamEvents: document.querySelector("#teamEvents"),
  teamNameInput: document.querySelector("#teamNameInput"),
  createTeamBtn: document.querySelector("#createTeamBtn"),
};

function userId() {
  return state.user?.id || 0;
}

function isReady() {
  return Boolean(userId());
}

function formatDate(value) {
  if (!value) return "Дата не указана";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function emptyState(title, text, action = "") {
  return `
    <div class="empty-state">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(text)}</p>
      ${action}
    </div>
  `;
}

function eventCard(event, compact = false) {
  const tags = (event.tags || []).slice(0, 3).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("");
  return `
    <article class="event-card" style="--type-color:${typeColors[event.type] || "#1f7a5a"}">
      <div class="event-meta">
        <span class="chip">${labels[event.type] || event.type}</span>
        <span class="chip level">${labels[event.level] || event.level}</span>
        ${event.is_private ? '<span class="chip private">Приватно</span>' : ""}
      </div>
      <h3>${escapeHtml(event.title)}</h3>
      <p>${escapeHtml(compact ? event.description.slice(0, 110) : event.description)}</p>
      <div class="event-meta">
        <span class="chip">${formatDate(event.start_date)}</span>
        <span class="chip">${labels[event.status] || "Без статуса"}</span>
        ${event.team_name ? `<span class="chip">${escapeHtml(event.team_name)}</span>` : ""}
      </div>
      <div class="event-meta">${tags}</div>
      <div class="card-actions">
        <button data-detail="${event.id}" type="button">Детали</button>
        <button data-status="${event.id}" data-value="planned" type="button">Планирую</button>
        <button data-status="${event.id}" data-value="attended" type="button">Участвовал</button>
      </div>
    </article>
  `;
}

function fillSelect(select, values, placeholder) {
  select.innerHTML = `<option value="">${placeholder}</option>${values
    .map((item) => `<option value="${item}">${labels[item] || item}</option>`)
    .join("")}`;
}

function syncUser() {
  if (!state.user) {
    els.currentUser.textContent = "Создайте профиль, чтобы начать.";
    return;
  }
  const invite = `${location.origin}/invite/${state.user.invite_token}`;
  els.currentUser.innerHTML = `Профиль: <strong>${escapeHtml(state.user.name)}</strong><br>Код для поиска: <strong>${escapeHtml(state.user.invite_code)}</strong><br><span>${escapeHtml(invite)}</span>`;
}

async function loadMeta() {
  state.meta = await api.get("/api/meta");
  fillSelect(els.typeFilter, state.meta.event_types, "Все типы");
  fillSelect(els.levelFilter, state.meta.levels, "Все уровни");
  fillSelect(els.eventForm.elements.type, state.meta.event_types, "Тип события");
  fillSelect(els.eventForm.elements.level, state.meta.levels, "Уровень");
}

function queryString() {
  const params = new URLSearchParams({ user_id: userId(), view: state.view });
  if (els.searchInput.value.trim()) params.set("search", els.searchInput.value.trim());
  if (els.typeFilter.value) params.set("type", els.typeFilter.value);
  if (els.levelFilter.value) params.set("level", els.levelFilter.value);
  if (els.tagFilter.value.trim()) params.set("tag", els.tagFilter.value.trim());
  return params.toString();
}

async function refreshAll() {
  if (!isReady()) {
    state.events = [];
    state.teams = [];
    state.activeTeam = null;
    state.profile = null;
    state.analytics = null;
    renderAllEmpty();
    return;
  }
  const [events, dashboard, analytics, profile, teams] = await Promise.all([
    api.get(`/api/events?${queryString()}`),
    api.get(`/api/dashboard?user_id=${userId()}`),
    api.get(`/api/analytics/user/${userId()}?period=month`),
    api.get(`/api/users/${userId()}/profile`),
    api.get(`/api/teams?user_id=${userId()}`),
  ]);
  state.events = events;
  state.analytics = analytics;
  state.profile = profile;
  state.teams = teams;
  state.activeTeam = teams[0] ? await api.get(`/api/teams/${teams[0].id}`) : null;
  renderEvents();
  renderDashboard(dashboard, analytics);
  renderSocial();
  renderTeam();
}

function renderAllEmpty() {
  const action = '<button class="primary" data-focus-register type="button">Создать профиль</button>';
  els.eventList.innerHTML = emptyState("Сначала профиль", "Введите имя и, если хотите, короткий пин для повторного входа.", action);
  els.recentFeed.innerHTML = emptyState("Нет участий", "После регистрации здесь появятся ваши ближайшие события.");
  els.summaryStats.innerHTML = "";
  els.collaboratorsList.innerHTML = emptyState("Совместных участий пока нет", "Добавьте друзей и отмечайте участие в событиях.");
  els.timelineList.innerHTML = emptyState("История пуста", "Активность появится после первого участия.");
  renderCalendar([]);
  renderChart("statusChart", "bar", [], ["#1f7a5a"]);
  renderChart("typeChart", "doughnut", [], Object.values(typeColors));
  renderSocial();
  renderTeam();
}

function renderEvents() {
  els.eventList.innerHTML = state.events.length
    ? state.events.map((event) => eventCard(event)).join("")
    : emptyState("У вас пока нет событий", "Нажмите «Создать событие», чтобы добавить первое.", '<button class="primary" data-create-empty type="button">Создать событие</button>');
}

function renderDashboard(data, analytics) {
  const summary = analytics?.summary || {};
  els.summaryStats.innerHTML = `
    <article><strong>${summary.planned || 0}</strong><span>планов за месяц</span></article>
    <article><strong>${summary.attended || 0}</strong><span>фактических участий</span></article>
    <article><strong>${summary.conversion || 0}%</strong><span>конверсия план → участие</span></article>
  `;
  els.recentFeed.innerHTML = data.recent.length
    ? data.recent.map((event) => eventCard(event, true)).join("")
    : emptyState("У вас пока нет участий", "Нажмите «Создать событие», чтобы добавить первое.");
  els.collaboratorsList.innerHTML = analytics.collaborators.length
    ? analytics.collaborators.map((item) => `<div class="list-row"><strong>${escapeHtml(item.name)}</strong><span>${item.shared_count} совместных активностей</span></div>`).join("")
    : emptyState("Совместных участий пока нет", "Добавьте друзей и участвуйте в событиях вместе.");
  els.timelineList.innerHTML = analytics.timeline.length
    ? analytics.timeline.map((item) => `<div class="timeline-row"><span>${escapeHtml(item.label)}</span><strong>${item.count}</strong></div>`).join("")
    : emptyState("История активности пуста", "Отмечайте планируемое и фактическое участие.");
  renderCalendar(data.upcoming);
  renderChart("statusChart", "bar", analytics.periods, ["#2d7dd2", "#1f7a5a", "#f0a202", "#b54747"]);
  renderChart("typeChart", "doughnut", analytics.types, Object.values(typeColors));
}

function renderCalendar(events) {
  const calendarEvents = events.map((event) => ({
    id: event.id,
    title: event.title,
    start: event.start_date,
    end: event.end_date,
    backgroundColor: typeColors[event.type],
    borderColor: typeColors[event.type],
  }));
  if (!state.calendar) {
    state.calendar = new FullCalendar.Calendar(document.querySelector("#calendar"), {
      initialView: window.innerWidth < 560 ? "listWeek" : "dayGridMonth",
      height: window.innerWidth < 560 ? 360 : 500,
      locale: "ru",
      headerToolbar: {
        left: "prev,next",
        center: "title",
        right: window.innerWidth < 560 ? "listWeek" : "dayGridMonth,listWeek",
      },
      events: calendarEvents,
      eventClick: (info) => openDetail(info.event.id),
    });
    state.calendar.render();
    return;
  }
  state.calendar.removeAllEvents();
  state.calendar.addEventSource(calendarEvents);
}

function renderChart(id, type, data, colors) {
  const ctx = document.getElementById(id);
  if (state.charts[id]) state.charts[id].destroy();
  state.charts[id] = new Chart(ctx, {
    type,
    data: {
      labels: data.map((item) => labels[item.label] || item.label),
      datasets: [
        {
          data: data.map((item) => item.count),
          backgroundColor: colors,
          borderWidth: 0,
          borderRadius: type === "bar" ? 6 : 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
      scales: type === "bar" ? { y: { beginAtZero: true, ticks: { precision: 0 } } } : {},
    },
  });
}

function renderSocial() {
  renderInviteTarget();
  if (!state.profile) {
    els.profileBox.innerHTML = emptyState("Профиля пока нет", "Войдите по имени, чтобы получить код и ссылку приглашения.");
    els.friendsList.innerHTML = emptyState("У вас пока нет друзей", "Отправьте приглашение, чтобы добавить их.");
    els.invitesList.innerHTML = emptyState("Приглашений нет", "Входящие приглашения появятся здесь.");
    return;
  }
  els.profileBox.innerHTML = `
    <div class="profile-token"><span>Код</span><strong>${escapeHtml(state.profile.invite_code)}</strong></div>
    <div class="profile-token"><span>Ссылка</span><strong>${escapeHtml(`${location.origin}/invite/${state.profile.invite_token}`)}</strong></div>
    <div class="chips">${state.profile.teams.map((team) => `<span class="chip">${escapeHtml(team.name)}</span>`).join("") || '<span class="muted">Команд пока нет</span>'}</div>
  `;
  els.friendsList.innerHTML = state.profile.friends.length
    ? state.profile.friends
        .map((friend) => `<div class="list-row"><strong>${escapeHtml(friend.name)}</strong><span>${friend.shared_events || 0} совместных событий</span>${state.activeTeam ? `<button data-team-invite="${friend.id}" type="button">В команду</button>` : ""}</div>`)
        .join("")
    : emptyState("У вас пока нет друзей", "Найдите человека по имени и короткому коду.");
  const friendInvites = state.profile.friend_invites
    .map(
      (invite) => `
      <div class="list-row">
        <strong>${escapeHtml(invite.from_name)}</strong>
        <span>хочет добавить вас в друзья</span>
        <button data-friend-response="accepted" data-requester="${invite.requester_id}" type="button">Принять</button>
        <button data-friend-response="declined" data-requester="${invite.requester_id}" type="button">Отклонить</button>
      </div>`
    )
    .join("");
  const teamInvites = state.profile.team_invites
    .map(
      (invite) => `
      <div class="list-row">
        <strong>${escapeHtml(invite.team_name)}</strong>
        <span>приглашение от ${escapeHtml(invite.from_name)}</span>
        <button data-team-response="accepted" data-invite-id="${invite.id}" type="button">Принять</button>
        <button data-team-response="declined" data-invite-id="${invite.id}" type="button">Отклонить</button>
      </div>`
    )
    .join("");
  els.invitesList.innerHTML = friendInvites || teamInvites ? friendInvites + teamInvites : emptyState("Приглашений нет", "Входящие и исходящие приглашения появятся здесь.");
}

function renderInviteTarget() {
  if (!state.inviteTarget) return;
  const isSelf = state.inviteTarget.id === userId();
  els.friendSearchResults.innerHTML = `
    <div class="list-row invite-target">
      <strong>${escapeHtml(state.inviteTarget.name)}</strong>
      <span>Код: ${escapeHtml(state.inviteTarget.invite_code)}</span>
      ${
        isSelf
          ? "<span>Это ваш профиль.</span>"
          : isReady()
            ? `<button data-add-friend="${state.inviteTarget.id}" type="button">Добавить в друзья</button>`
            : "<span>Войдите или создайте профиль, чтобы добавить пользователя.</span>"
      }
    </div>
  `;
}

function renderTeam() {
  if (!state.activeTeam) {
    els.teamName.textContent = "Команды пока нет";
    els.teamMembers.innerHTML = "";
    els.teamEvents.innerHTML = emptyState("Командных событий пока нет", "Создайте команду и привяжите к ней событие.");
    renderChart("teamChart", "doughnut", [], []);
    return;
  }
  els.teamName.textContent = state.activeTeam.name;
  els.teamMembers.innerHTML = state.activeTeam.members.map((member) => `<span class="chip">${escapeHtml(member.name)} · ${escapeHtml(member.role)}</span>`).join("");
  els.teamEvents.innerHTML = state.activeTeam.events.length
    ? state.activeTeam.events.map((event) => eventCard(event, true)).join("")
    : emptyState("Командных событий пока нет", "При создании события отметьте связь с текущей командой.");
  renderChart("teamChart", "doughnut", state.activeTeam.analytics.types, Object.values(typeColors));
}

async function openDetail(eventId) {
  if (!isReady()) return;
  const event = await api.get(`/api/events/${eventId}?user_id=${userId()}`);
  els.eventDetail.innerHTML = `
    <header>
      <div class="dialog-head">
        <h2>${escapeHtml(event.title)}</h2>
        <button data-close-detail type="button" aria-label="Закрыть">×</button>
      </div>
      <div class="event-meta">
        <span class="chip">${labels[event.type]}</span>
        <span class="chip level">${labels[event.level]}</span>
        <span class="chip">${labels[event.visibility_scope]}</span>
        ${event.team_name ? `<span class="chip">${escapeHtml(event.team_name)}</span>` : ""}
      </div>
    </header>
    <p>${escapeHtml(event.description)}</p>
    <div class="detail-grid">
      <div class="detail-box"><strong>Даты</strong><p>${formatDate(event.start_date)} - ${formatDate(event.end_date)}</p></div>
      <div class="detail-box"><strong>Ссылка</strong><p>${event.link ? `<a href="${escapeHtml(event.link)}" target="_blank" rel="noreferrer">${escapeHtml(event.link)}</a>` : "Не указана"}</p></div>
      <div class="detail-box"><strong>Участники</strong><p>${event.participants.map((item) => `${escapeHtml(item.name)} · ${labels[item.status]}`).join(", ") || "Пока нет"}</p></div>
      <div class="detail-box"><strong>Команды</strong><p>${event.teams.map((item) => `${escapeHtml(item.name)} (${labels[item.visibility]})`).join(", ") || "Не привязано"}</p></div>
    </div>
    <section>
      <h2>Статус участия</h2>
      <div class="status-row">
        ${state.meta.statuses.map((status) => `<button class="${event.status === status ? "active" : ""}" data-status="${event.id}" data-value="${status}" type="button">${labels[status]}</button>`).join("")}
      </div>
    </section>
    <form class="notes-form" data-notes="${event.id}">
      <label><strong>Мои заметки</strong><textarea name="notes">${escapeHtml(event.notes || "")}</textarea></label>
      <button type="submit">Сохранить заметки</button>
    </form>
    <section>
      <h2>Комментарии</h2>
      <div class="feed">
        ${event.comments.map((comment) => `<p><strong>${escapeHtml(comment.author)}:</strong> ${escapeHtml(comment.body)}</p>`).join("") || '<p class="muted">Комментариев пока нет.</p>'}
      </div>
    </section>
  `;
  els.detailDialog.showModal();
}

async function updateStatus(eventId, status) {
  if (!isReady()) return alert("Сначала создайте профиль.");
  await api.post(`/api/events/${eventId}/status`, { user_id: userId(), status });
  await refreshAll();
  if (els.detailDialog.open) openDetail(eventId);
}

function setPage(page) {
  state.page = page;
  document.querySelectorAll(".page").forEach((item) => item.classList.toggle("active", item.id === `${page}Page`));
  document.querySelectorAll(".nav-tabs button").forEach((item) => item.classList.toggle("active", item.dataset.page === page));
  const copy = {
    dashboard: ["Мои активности", "Ближайшие события, участие и приглашения без лишней настройки."],
    events: ["События", "Поиск, фильтры и карточки событий."],
    social: ["Друзья и приглашения", "Поиск по имени и коду, входящие приглашения, совместные события."],
    team: ["Команда", "Участники, командные события и аналитика участия."],
  };
  els.pageTitle.textContent = copy[page][0];
  els.pageLead.textContent = copy[page][1];
  if (state.calendar) setTimeout(() => state.calendar.updateSize(), 0);
}

async function findFriends() {
  if (!isReady()) return alert("Сначала создайте профиль.");
  const params = new URLSearchParams();
  if (els.friendNameInput.value.trim()) params.set("name", els.friendNameInput.value.trim());
  if (els.friendCodeInput.value.trim()) params.set("code", els.friendCodeInput.value.trim());
  const users = await api.get(`/api/users/search?${params.toString()}`);
  els.friendSearchResults.innerHTML = users.length
    ? users
        .filter((user) => user.id !== userId())
        .map((user) => `<div class="list-row"><strong>${escapeHtml(user.name)}</strong><span>${escapeHtml(user.invite_code)}</span><button data-add-friend="${user.id}" type="button">Добавить</button></div>`)
        .join("")
    : emptyState("Никого не нашли", "Проверьте имя и короткий код.");
}

async function loadInviteTargetFromUrl() {
  const match = location.pathname.match(/^\/invite\/([^/]+)$/);
  if (!match) return;
  state.inviteTarget = await api.get(`/api/invite/${encodeURIComponent(match[1])}`);
  setPage("social");
  renderInviteTarget();
}

function bindEvents() {
  els.registerBtn.addEventListener("click", async () => {
    const user = await api.post("/api/register", {
      name: els.nameInput.value,
      pin: els.pinInput.value,
      access_code: els.pinInput.value,
    });
    state.user = user;
    localStorage.setItem("eventlog:user", JSON.stringify(user));
    syncUser();
    await refreshAll();
  });

  els.navTabs.addEventListener("click", (event) => {
    const page = event.target.dataset.page;
    if (page) setPage(page);
  });

  els.viewMode.addEventListener("click", async (event) => {
    const view = event.target.dataset.view;
    if (!view) return;
    state.view = view;
    [...els.viewMode.children].forEach((button) => button.classList.toggle("active", button.dataset.view === view));
    await refreshAll();
  });

  [els.searchInput, els.typeFilter, els.levelFilter, els.tagFilter].forEach((control) => control.addEventListener("input", () => refreshAll()));

  document.body.addEventListener("click", async (event) => {
    const detail = event.target.closest("[data-detail]");
    const status = event.target.closest("[data-status]");
    const close = event.target.closest("[data-close-detail]");
    const createEmpty = event.target.closest("[data-create-empty]");
    const addFriend = event.target.closest("[data-add-friend]");
    const friendResponse = event.target.closest("[data-friend-response]");
    const teamInvite = event.target.closest("[data-team-invite]");
    const teamResponse = event.target.closest("[data-team-response]");
    const focusRegister = event.target.closest("[data-focus-register]");
    if (detail) openDetail(detail.dataset.detail);
    if (status) updateStatus(status.dataset.status, status.dataset.value);
    if (close) els.detailDialog.close();
    if (createEmpty) els.eventDialog.showModal();
    if (focusRegister) els.nameInput.focus();
    if (addFriend) {
      await api.post("/api/friends/request", { requester_id: userId(), target_id: Number(addFriend.dataset.addFriend) });
      await refreshAll();
      await findFriends();
    }
    if (friendResponse) {
      await api.post("/api/friends/respond", {
        requester_id: Number(friendResponse.dataset.requester),
        addressee_id: userId(),
        status: friendResponse.dataset.friendResponse,
      });
      await refreshAll();
    }
    if (teamInvite) {
      if (!state.activeTeam) return alert("Сначала создайте команду.");
      await api.post("/api/team-invites", { team_id: state.activeTeam.id, invited_user_id: Number(teamInvite.dataset.teamInvite), invited_by: userId() });
      await refreshAll();
    }
    if (teamResponse) {
      await api.post("/api/team-invites/respond", { invite_id: Number(teamResponse.dataset.inviteId), status: teamResponse.dataset.teamResponse });
      await refreshAll();
    }
  });

  els.openCreateBtn.addEventListener("click", () => {
    if (!isReady()) return alert("Сначала создайте профиль.");
    els.eventDialog.showModal();
  });
  els.closeCreateBtn.addEventListener("click", () => els.eventDialog.close());
  els.findFriendBtn.addEventListener("click", findFriends);

  els.eventForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!isReady()) return alert("Сначала создайте профиль.");
    const form = new FormData(els.eventForm);
    const payload = Object.fromEntries(form.entries());
    payload.created_by = userId();
    payload.is_private = payload.visibility_scope === "private";
    payload.team_id = form.get("attach_team") && state.activeTeam ? state.activeTeam.id : null;
    await api.post("/api/events", payload);
    els.eventForm.reset();
    els.eventDialog.close();
    await refreshAll();
    setPage("events");
  });

  els.eventDetail.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-notes]");
    if (!form) return;
    event.preventDefault();
    await api.post(`/api/events/${form.dataset.notes}/notes`, {
      user_id: userId(),
      notes: new FormData(form).get("notes"),
    });
    await refreshAll();
    openDetail(form.dataset.notes);
  });

  els.createTeamBtn.addEventListener("click", async () => {
    if (!isReady()) return alert("Сначала создайте профиль.");
    await api.post("/api/teams", { name: els.teamNameInput.value, created_by: userId() });
    els.teamNameInput.value = "";
    await refreshAll();
  });
}

async function init() {
  syncUser();
  bindEvents();
  await loadMeta();
  await loadInviteTargetFromUrl();
  await refreshAll();
  if (!state.inviteTarget) setPage("dashboard");
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
