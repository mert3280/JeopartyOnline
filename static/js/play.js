(() => {
  const code = window.GAME.code;
  const STORAGE_KEY = `jeoparty:player:${code}`;
  const NAME_KEY = `jeoparty:name:${code}`;
  const TEAM_KEY = `jeoparty:team:${code}`;

  const socket = io({ transports: ['polling', 'websocket'] });
  let state = null;
  let me = { player_id: null, name: null, team: null };
  let firstStateReceived = false;

  // Show loading overlay until we have a state from the server
  if (window.Effects) Effects.showLoading('Connecting…');

  // Sections
  const joinScreen = document.getElementById('join-screen');
  const playLobby = document.getElementById('play-lobby');
  const playGame = document.getElementById('play-game');
  const playEnded = document.getElementById('play-ended');

  // Join screen
  const nameInput = document.getElementById('name-input');
  const teamOptions = document.getElementById('team-options');
  const joinBtn = document.getElementById('join-btn');
  const joinError = document.getElementById('join-error');
  let selectedTeam = null;

  // Lobby
  const playLobbyInfo = document.getElementById('play-lobby-info');

  // In-game
  const teamChip = document.getElementById('play-team-chip');
  const nameChip = document.getElementById('play-name-chip');
  const playStatus = document.getElementById('play-status');
  const playQuestion = document.getElementById('play-question');
  const qCat = document.getElementById('play-q-cat');
  const qPts = document.getElementById('play-q-pts');
  const qText = document.getElementById('play-q-text');
  const qAnswer = document.getElementById('play-q-answer');
  const buzzStatus = document.getElementById('play-buzz-status');
  const buzzBtn = document.getElementById('buzz-btn');
  const playScores = document.getElementById('play-scores');

  // Ended
  const playStandings = document.getElementById('play-standings');

  // Pre-fill name from previous session
  nameInput.value = localStorage.getItem(NAME_KEY) || '';

  // ---- socket events ----

  socket.on('connect', () => {
    const savedPlayerId = localStorage.getItem(STORAGE_KEY);
    if (savedPlayerId) {
      socket.emit('player:reconnect', { code, player_id: savedPlayerId });
    } else {
      // New player — fetch state so team list populates immediately
      socket.emit('player:request_state', { code });
    }
  });

  socket.on('reconnected', (data) => {
    if (data && data.ok) {
      me.player_id = data.player_id;
      me.name = localStorage.getItem(NAME_KEY);
      me.team = localStorage.getItem(TEAM_KEY);
    } else {
      // Stale player_id; clear and prompt fresh join
      localStorage.removeItem(STORAGE_KEY);
    }
  });

  socket.on('joined', (data) => {
    me.player_id = data.player_id;
    me.name = nameInput.value.trim();
    me.team = selectedTeam;
    localStorage.setItem(STORAGE_KEY, data.player_id);
    localStorage.setItem(NAME_KEY, me.name);
    localStorage.setItem(TEAM_KEY, me.team);
    if (window.Effects) Effects.hideLoading();
  });

  socket.on('error', (e) => {
    if (e && e.message) showJoinError(e.message);
    if (window.Effects) Effects.hideLoading();
  });

  socket.on('state', (s) => {
    const previousPhase = state ? state.phase : null;
    state = s;
    // Apply host's chosen theme to this player
    if (s.theme) document.documentElement.setAttribute('data-theme', s.theme);
    if (!firstStateReceived) {
      firstStateReceived = true;
      if (window.Effects) Effects.hideLoading();
    }
    // Confetti when game ends
    if (previousPhase !== 'ended' && state.phase === 'ended' && window.Effects) {
      Effects.confetti(6000);
    }
    render();
  });

  socket.on('buzz_result', (b) => {
    // Visual feedback even before next state arrives
    if (buzzBtn) buzzBtn.disabled = true;
  });

  // ---- join screen ----

  function renderTeamOptions(teams) {
    teamOptions.innerHTML = teams.map(t => `
      <button type="button" class="team-option" data-team="${escapeAttr(t.name)}">
        ${escapeHtml(t.name)}
        <span class="muted small">· ${t.members.length} player${t.members.length === 1 ? '' : 's'}</span>
      </button>
    `).join('');
    teamOptions.querySelectorAll('.team-option').forEach(b => {
      b.addEventListener('click', () => {
        teamOptions.querySelectorAll('.team-option').forEach(x => x.classList.remove('selected'));
        b.classList.add('selected');
        selectedTeam = b.dataset.team;
        updateJoinButton();
      });
    });
  }

  nameInput.addEventListener('input', updateJoinButton);

  function updateJoinButton() {
    joinBtn.disabled = !(nameInput.value.trim() && selectedTeam);
  }

  joinBtn.addEventListener('click', () => {
    hideJoinError();
    if (window.Effects) Effects.showLoading('Joining the game…');
    socket.emit('player:join', {
      code,
      name: nameInput.value.trim(),
      team: selectedTeam,
    });
  });

  buzzBtn.addEventListener('click', () => {
    socket.emit('player:buzz', { code });
    buzzBtn.disabled = true;
  });

  function showJoinError(msg) { joinError.textContent = msg; joinError.hidden = false; }
  function hideJoinError() { joinError.hidden = true; }

  // ---- render ----

  function render() {
    if (!state) return;

    const inGame = !!me.player_id;
    joinScreen.hidden = inGame;
    if (!inGame) {
      renderTeamOptions(state.teams);
      return;
    }

    playLobby.hidden = state.phase !== 'lobby';
    playGame.hidden = !['board', 'question', 'buzzed', 'reveal'].includes(state.phase);
    playEnded.hidden = state.phase !== 'ended';

    if (state.phase === 'lobby') {
      const team = state.teams.find(t => t.name === me.team);
      const others = team ? team.members.filter(m => m.id !== me.player_id).length : 0;
      playLobbyInfo.innerHTML = `On <strong>${escapeHtml(me.team || '')}</strong>${others ? ` with ${others} other${others === 1 ? '' : 's'}` : ''}.`;
    }

    if (!playGame.hidden) renderGame();
    if (state.phase === 'ended') renderEnded();
  }

  function renderGame() {
    teamChip.textContent = me.team || '';
    nameChip.textContent = me.name || '';

    const scoreOf = (name) => state.teams.find(t => t.name === name)?.score ?? 0;
    playScores.innerHTML = state.teams.map(t => `
      <span class="play-score-chip ${t.name === me.team ? 'mine' : ''}">${escapeHtml(t.name)}: ${t.score}</span>
    `).join('');

    if (state.phase === 'board') {
      playStatus.hidden = false;
      playStatus.textContent = "Waiting for the host to pick a question…";
      playQuestion.hidden = true;
      return;
    }

    // question / buzzed / reveal
    const cur = state.current;
    if (!cur) return;
    playStatus.hidden = true;
    playQuestion.hidden = false;
    qCat.textContent = cur.category;
    qPts.textContent = `${cur.points} pts`;
    qText.textContent = cur.question;

    const someoneBuzzed = !!cur.buzzed_team;

    if (state.phase === 'question') {
      buzzBtn.hidden = false;
      buzzBtn.disabled = false;
      buzzBtn.textContent = 'BUZZ';
      buzzStatus.hidden = true;
      qAnswer.hidden = true;
    } else if (state.phase === 'buzzed') {
      buzzBtn.hidden = true;
      buzzStatus.hidden = false;
      const buzzedName = state.teams
        .find(t => t.name === cur.buzzed_team)?.members
        .find(m => m.id === cur.buzzed_player)?.name || 'Someone';
      const isMe = cur.buzzed_player === me.player_id;
      buzzStatus.textContent = isMe
        ? `You buzzed in for ${cur.buzzed_team}!`
        : `${buzzedName} (${cur.buzzed_team}) buzzed in.`;
      qAnswer.hidden = true;
    } else if (state.phase === 'reveal') {
      buzzBtn.hidden = true;
      buzzStatus.hidden = false;
      if (cur.buzzed_team) {
        const buzzedName = state.teams
          .find(t => t.name === cur.buzzed_team)?.members
          .find(m => m.id === cur.buzzed_player)?.name || 'Someone';
        const isMe = cur.buzzed_player === me.player_id;
        buzzStatus.textContent = isMe
          ? `You buzzed in for ${cur.buzzed_team}!`
          : `${buzzedName} (${cur.buzzed_team}) buzzed in.`;
      } else {
        buzzStatus.textContent = "Time's up!";
      }
      qAnswer.hidden = !cur.answer;
      if (cur.answer) qAnswer.textContent = `Answer: ${cur.answer}`;
    }
  }

  function renderEnded() {
    const sorted = [...state.teams].sort((a, b) => b.score - a.score);
    playStandings.innerHTML = sorted.map((t, i) => `
      <li><span>${i + 1}. ${escapeHtml(t.name)}</span><strong>${t.score}</strong></li>
    `).join('');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }
})();
