(() => {
  const code = window.GAME.code;
  const publicUrl = window.GAME.publicUrl;
  const hostToken = localStorage.getItem(`jeoparty:host:${code}`);

  if (!hostToken) {
    document.body.innerHTML = `
      <div style="padding: 40px; text-align: center;">
        <h2>Host token missing</h2>
        <p>This browser didn't create the game. Open the host link from the same browser that created it,
        or <a href="/create">create a new game</a>.</p>
      </div>`;
    return;
  }

  const socket = io({ transports: ['polling', 'websocket'] });
  let state = null;
  let prevPhase = null;
  let firstStateReceived = false;

  // Show loading overlay until first state arrives
  if (window.Effects) Effects.showLoading('Setting up the game…');

  // Element refs
  const lobby = document.getElementById('lobby');
  const board = document.getElementById('board');
  const ended = document.getElementById('ended');
  const qModal = document.getElementById('question-modal');
  const setNameEl = document.getElementById('set-name');
  const teamScores = document.getElementById('team-scores');
  const codeDisplay = document.getElementById('code-display');
  const lobbyTeams = document.getElementById('lobby-teams');
  const startBtn = document.getElementById('start-btn');
  const joinUrlEl = document.getElementById('join-url');
  const categoriesEl = document.getElementById('categories');
  const tilesEl = document.getElementById('tiles');
  const endGameBtn = document.getElementById('end-game-btn');

  // Question modal
  const qCategory = document.getElementById('q-category');
  const qPoints = document.getElementById('q-points');
  const qText = document.getElementById('q-text');
  const qTimer = document.getElementById('q-timer');
  const buzzInfo = document.getElementById('buzz-info');
  const qAnswer = document.getElementById('q-answer');
  const revealBtn = document.getElementById('reveal-btn');
  const correctBtn = document.getElementById('correct-btn');
  const wrongBtn = document.getElementById('wrong-btn');
  const nextBtn = document.getElementById('next-btn');
  const cancelQBtn = document.getElementById('cancel-q-btn');

  // Score-edit modal
  const scoreEdit = document.getElementById('score-edit');
  const scoreEditTitle = document.getElementById('score-edit-title');
  const scoreEditInput = document.getElementById('score-edit-input');
  const scoreEditSave = document.getElementById('score-edit-save');
  const scoreEditCancel = document.getElementById('score-edit-cancel');

  // Final standings
  const finalStandings = document.getElementById('final-standings');

  // ----- socket events -----

  socket.on('connect', () => {
    socket.emit('host:join', { code, host_token: hostToken });
  });

  socket.on('error', (e) => {
    console.error('host error', e);
    if (e && e.message === 'host auth failed') {
      alert('Host authentication failed. Recreate the game.');
    }
  });

  socket.on('state', (s) => {
    const previousPhase = state ? state.phase : null;
    state = s;
    if (!firstStateReceived) {
      firstStateReceived = true;
      if (window.Effects) Effects.hideLoading();
    }
    // Get-Ready flash when host transitions out of lobby into the board
    if (previousPhase === 'lobby' && state.phase === 'board' && window.Effects) {
      Effects.flash('Get Ready!', 1100);
    }
    // Confetti on game end
    if (previousPhase !== 'ended' && state.phase === 'ended' && window.Effects) {
      Effects.confetti(6000);
    }
    prevPhase = state.phase;
    render();
  });

  // ----- buttons -----

  startBtn.addEventListener('click', () => socket.emit('host:start_game', { code }));
  endGameBtn.addEventListener('click', () => {
    if (confirm('End the game now and show final standings?')) {
      socket.emit('host:cancel_question', { code });
      // The cleanest "end" action is to just navigate away; for now, force ended view client-side.
      if (state) state.phase = 'ended';
      if (window.Effects) Effects.confetti(6000);
      render();
    }
  });
  revealBtn.addEventListener('click', () => socket.emit('host:reveal_answer', { code }));
  correctBtn.addEventListener('click', () => socket.emit('host:judge', { code, correct: true }));
  wrongBtn.addEventListener('click', () => socket.emit('host:judge', { code, correct: false }));
  nextBtn.addEventListener('click', () => socket.emit('host:next', { code }));
  cancelQBtn.addEventListener('click', () => socket.emit('host:cancel_question', { code }));

  scoreEditCancel.addEventListener('click', () => { scoreEdit.hidden = true; });
  scoreEditSave.addEventListener('click', () => {
    const val = parseInt(scoreEditInput.value, 10);
    if (!isNaN(val) && scoreEdit.dataset.team) {
      socket.emit('host:edit_score', { code, team: scoreEdit.dataset.team, score: val });
    }
    scoreEdit.hidden = true;
  });

  // ----- render -----

  function render() {
    if (!state) return;
    setNameEl.textContent = state.set_name ? `· ${state.set_name}` : '';
    renderScores();
    if (publicUrl) {
      joinUrlEl.textContent = `${publicUrl}/join?code=${code}`;
    } else {
      joinUrlEl.textContent = `${location.origin}/join?code=${code}`;
    }

    lobby.hidden = state.phase !== 'lobby';
    board.hidden = !['board', 'question', 'buzzed', 'reveal'].includes(state.phase);
    qModal.hidden = !['question', 'buzzed', 'reveal'].includes(state.phase);
    ended.hidden = state.phase !== 'ended';

    if (state.phase === 'lobby') renderLobby();
    if (!board.hidden) renderBoard();
    if (!qModal.hidden) renderQuestion();
    if (state.phase === 'ended') renderEnded();
  }

  function renderScores() {
    teamScores.innerHTML = state.teams.map(t => `
      <button class="team-score-chip" data-team="${escapeAttr(t.name)}">
        ${escapeHtml(t.name)}: ${t.score}
      </button>
    `).join('');
    teamScores.querySelectorAll('.team-score-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const teamName = btn.dataset.team;
        const team = state.teams.find(t => t.name === teamName);
        if (!team) return;
        scoreEdit.dataset.team = teamName;
        scoreEditTitle.textContent = `Edit ${teamName}'s score`;
        scoreEditInput.value = team.score;
        scoreEdit.hidden = false;
        scoreEditInput.focus();
      });
    });
  }

  function renderLobby() {
    codeDisplay.textContent = code;
    lobbyTeams.innerHTML = state.teams.map(t => `
      <div class="lobby-team">
        <div class="lobby-team-name">${escapeHtml(t.name)} <span class="muted small">· ${t.members.length} player${t.members.length === 1 ? '' : 's'}</span></div>
        <div class="lobby-members">${t.members.length ? t.members.map(m => escapeHtml(m.name)).join(', ') : '<span class="muted">no players yet</span>'}</div>
      </div>
    `).join('');
  }

  function renderBoard() {
    categoriesEl.innerHTML = state.categories.map(c =>
      `<div class="category-cell">${escapeHtml(c)}</div>`
    ).join('');

    // Build a lookup of asked tiles
    const asked = new Set(state.asked.map(a => `${a[0]}|${a[1]}`));

    // 6 rows × 6 columns: tiles[i][j] = state.tiles for category j, row i
    // state.tiles is grouped by category; we need to read by row/col
    // Group questions by category, sort by points
    const byCat = {};
    state.tiles.forEach(t => {
      if (!byCat[t.category]) byCat[t.category] = [];
      byCat[t.category].push(t);
    });
    Object.values(byCat).forEach(arr => arr.sort((a, b) => a.points - b.points));

    let html = '';
    const rows = Math.max(...Object.values(byCat).map(arr => arr.length), 6);
    for (let row = 0; row < rows; row++) {
      for (const cat of state.categories) {
        const tile = (byCat[cat] || [])[row];
        if (!tile) {
          html += `<button class="tile" disabled></button>`;
        } else {
          const isAsked = asked.has(`${tile.category}|${tile.points}`);
          html += `<button class="tile ${isAsked ? 'asked' : ''}" data-cat="${escapeAttr(tile.category)}" data-pts="${tile.points}" ${isAsked || state.phase !== 'board' ? 'disabled' : ''}>${tile.points}</button>`;
        }
      }
    }
    tilesEl.innerHTML = html;
    tilesEl.querySelectorAll('.tile').forEach(b => {
      b.addEventListener('click', () => {
        socket.emit('host:pick_question', {
          code,
          category: b.dataset.cat,
          points: parseInt(b.dataset.pts, 10),
        });
      });
    });
  }

  // Timer state
  let timerInterval = null;
  let timerStartedAt = null;
  let timerKey = null;

  function renderQuestion() {
    const cur = state.current;
    if (!cur) return;
    qCategory.textContent = cur.category;
    qPoints.textContent = `${cur.points} pts`;
    qText.textContent = cur.question;

    // Timer
    const key = `${cur.category}|${cur.points}`;
    if (state.phase === 'question') {
      if (timerKey !== key) {
        timerKey = key;
        timerStartedAt = Date.now();
        startTimer();
      }
    } else {
      stopTimer();
    }

    // Buzz info
    if (cur.buzzed_team) {
      buzzInfo.hidden = false;
      const player = state.teams.find(t => t.name === cur.buzzed_team)?.members.find(m => m.id === cur.buzzed_player);
      buzzInfo.textContent = `Buzzed: ${player ? player.name : '???'} (${cur.buzzed_team})`;
    } else {
      buzzInfo.hidden = true;
    }

    // Answer
    if (cur.answer && (state.phase === 'reveal' || state.phase === 'buzzed')) {
      qAnswer.hidden = false;
      qAnswer.textContent = `Answer: ${cur.answer}`;
    } else {
      qAnswer.hidden = true;
    }

    // Buttons
    revealBtn.hidden = state.phase !== 'question';
    correctBtn.hidden = state.phase !== 'buzzed';
    wrongBtn.hidden = state.phase !== 'buzzed';
    nextBtn.hidden = state.phase !== 'reveal';
  }

  function startTimer() {
    stopTimer();
    const total = state.question_time * 1000;
    const update = () => {
      const elapsed = Date.now() - timerStartedAt;
      const remaining = Math.max(0, total - elapsed);
      const secs = Math.ceil(remaining / 1000);
      qTimer.textContent = secs;
      qTimer.classList.toggle('expired', remaining <= 0);
      if (remaining <= 0) stopTimer();
    };
    update();
    timerInterval = setInterval(update, 100);
  }

  function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = null;
  }

  function renderEnded() {
    const sorted = [...state.teams].sort((a, b) => b.score - a.score);
    finalStandings.innerHTML = sorted.map((t, i) => `
      <li><span>${i + 1}. ${escapeHtml(t.name)}</span><strong>${t.score}</strong></li>
    `).join('');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }
})();
