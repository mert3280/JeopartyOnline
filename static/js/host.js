(() => {
  const code = window.GAME.code;
  const publicUrl = window.GAME.publicUrl;
  const tokenKey = `jeoparty:host:${code}`;

  // A hand-off link carries the token in the fragment (#t=...). Save it, then strip it
  // from the address bar so it doesn't linger in history or get shared by accident.
  const handoffToken = new URLSearchParams(location.hash.slice(1)).get('t');
  if (handoffToken) {
    try { localStorage.setItem(tokenKey, handoffToken); } catch (e) { /* private mode — keep in memory */ }
    history.replaceState(null, '', location.pathname + location.search);
  }
  let storedToken = null;
  try { storedToken = localStorage.getItem(tokenKey); } catch (e) { /* storage blocked */ }
  const hostToken = handoffToken || storedToken;

  if (!hostToken) {
    document.body.innerHTML = `
      <div style="padding: 40px; text-align: center;">
        <h2>Host token missing</h2>
        <p>This browser didn't create the game. On the device that's hosting, tap
        <strong>Host from another device</strong> and scan the QR (or open the link) here,
        or <a href="/create">create a new game</a>.</p>
      </div>`;
    return;
  }

  // Polling first, then upgrade: see play.js (phones open the host handoff link too).
  const socket = io({ transports: ['polling', 'websocket'] });
  let state = null;
  let prevPhase = null;
  let firstStateReceived = false;
  let replaced = false;  // another device took over; don't auto-reclaim on reconnect

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
  const cancelGameBtns = [
    document.getElementById('cancel-game-btn'),
    document.getElementById('board-cancel-game-btn'),
  ];
  const joinUrlEl = document.getElementById('join-url');
  const headerJoin = document.getElementById('header-join');
  const headerJoinHost = document.getElementById('header-join-host');
  const boardGrid = document.getElementById('board-grid');
  const endGameBtn = document.getElementById('end-game-btn');
  const connBanner = document.getElementById('conn-banner');

  // Hand-off + takeover
  const handoff = document.getElementById('handoff');
  const handoffQr = document.getElementById('handoff-qr');
  const handoffStatus = document.getElementById('handoff-status');
  const handoffUrl = document.getElementById('handoff-url');
  const handoffShare = document.getElementById('handoff-share');
  const handoffCopy = document.getElementById('handoff-copy');
  const handoffClose = document.getElementById('handoff-close');
  const replacedModal = document.getElementById('replaced');
  const reclaimBtn = document.getElementById('reclaim-btn');

  // Question modal
  const qModalCard = document.querySelector('#question-modal .modal-card');
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
    connBanner.hidden = true;
    if (!replaced) socket.emit('host:join', { code, host_token: hostToken });
  });

  // Phones drop the socket when the screen locks or the network hops; socket.io
  // reconnects on its own and the 'connect' handler re-authenticates.
  socket.on('disconnect', () => { connBanner.hidden = false; });

  socket.on('host:replaced', () => {
    replaced = true;
    handoff.hidden = true;
    replacedModal.hidden = false;
  });
  reclaimBtn.addEventListener('click', () => {
    replaced = false;
    replacedModal.hidden = true;
    socket.emit('host:join', { code, host_token: hostToken });
  });

  socket.on('error', (e) => {
    console.error('host error', e);
    if (e && e.message === 'host auth failed') {
      alert('Host authentication failed. Recreate the game.');
    }
  });

  // The room is gone (this host cancelled it), so drop the token and go home.
  socket.on('game:cancelled', () => {
    try { localStorage.removeItem(tokenKey); } catch (e) { /* storage blocked */ }
    window.location.href = '/';
  });

  // Lobby cookie mini-game sends just the cookie numbers, not a whole state.
  // The host only shows cookies eaten, so skip redraws (and the cards'
  // pop-in animation) for bites that don't finish a cookie.
  socket.on('cookie', (c) => {
    if (!state) return;
    let finished = false;
    c.teams.forEach(ct => {
      const team = state.teams.find(t => t.name === ct.name);
      if (!team) return;
      if (team.cookies_eaten !== ct.cookies_eaten) finished = true;
      Object.assign(team, ct);
    });
    if (finished) render();
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
  cancelGameBtns.forEach(btn => btn.addEventListener('click', () => {
    if (confirm('Cancel this game? Everyone will be sent back to the home page.')) {
      socket.emit('host:cancel_game', { code });
    }
  }));
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

  document.querySelectorAll('.handoff-open-btn').forEach(btn => {
    btn.addEventListener('click', openHandoff);
  });
  handoffClose.addEventListener('click', () => { handoff.hidden = true; });
  handoffCopy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(handoffUrl.value);
    } catch (e) {
      // Clipboard API needs https; fall back to selecting the text
      handoffUrl.select();
      document.execCommand('copy');
    }
    handoffCopy.textContent = 'Copied!';
    setTimeout(() => { handoffCopy.textContent = 'Copy link'; }, 1500);
  });
  handoffShare.addEventListener('click', () => {
    navigator.share({ title: 'Host JeoParty', url: handoffUrl.value }).catch(() => {});
  });

  async function openHandoff() {
    handoff.hidden = false;
    handoffQr.hidden = true;
    handoffUrl.hidden = true;
    handoffCopy.hidden = true;
    handoffShare.hidden = true;
    handoffStatus.textContent = 'Generating link…';
    try {
      const res = await fetch(`/api/host/${code}/handoff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host_token: hostToken }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'failed');
      handoffQr.src = data.qr;
      handoffQr.hidden = false;
      handoffUrl.value = data.url;
      handoffUrl.hidden = false;
      handoffCopy.hidden = false;
      handoffShare.hidden = !navigator.share;
      handoffStatus.textContent = '';
    } catch (e) {
      handoffStatus.textContent = "Couldn't create a hand-off link. Try again in a moment.";
    }
  }

  // Keep a phone/tablet host's screen awake — if it sleeps, the socket drops mid-game.
  let wakeLock = null;
  async function requestWakeLock() {
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
    } catch (e) { /* denied or unsupported — not fatal */ }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!wakeLock || wakeLock.released)) requestWakeLock();
  });
  requestWakeLock();

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
    const base = publicUrl || location.origin;
    joinUrlEl.textContent = `${base}/join?code=${code}`;
    // Keep the code visible mid-game so late arrivals can still join.
    headerJoinHost.textContent = `${base.replace(/^https?:\/\//, '')}/join`;
    headerJoin.hidden = state.phase === 'lobby' || state.phase === 'ended';

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
    const showPicker = state.phase === 'board';
    teamScores.innerHTML = state.teams.map(t => {
      const picking = showPicker && t.name === state.picking_team;
      return `
      <button class="team-score-chip team-colored${picking ? ' picking' : ''}${cookieShiny(t)}" data-team="${escapeAttr(t.name)}"
              style="background:${t.color_bg};color:${t.color_fg};border-color:${t.color_bg};">
        ${picking ? '<span class="picking-indicator" aria-hidden="true">▸</span>' : ''}${cookieCrown(t)}${escapeHtml(t.name)}: ${t.score}${picking ? '<span class="picking-label"> · picks next</span>' : ''}
      </button>
    `;
    }).join('');
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
    startBtn.disabled = !state.teams.some(t => t.members.length);
    if (!state.teams.length) {
      lobbyTeams.innerHTML = "<p class=\"muted\">No teams yet. They'll appear here as players create them.</p>";
      return;
    }
    lobbyTeams.innerHTML = state.teams.map(t => `
      <div class="lobby-team team-colored${cookieShiny(t)}" style="background:${t.color_bg};color:${t.color_fg};border-color:${t.color_bg};">
        <div class="lobby-team-name">${cookieCrown(t)}${escapeHtml(t.name)} <span class="lobby-team-meta">· ${t.members.length} player${t.members.length === 1 ? '' : 's'}</span>
          <span class="lobby-cookies" title="Cookies eaten">🍪 ${t.cookies_eaten}</span></div>
        <div class="lobby-members">${t.members.length ? t.members.map(m => escapeHtml(m.name)).join(', ') : '<span class="lobby-team-meta">no players yet</span>'}</div>
      </div>
    `).join('');
  }

  // Lobby cookie rewards stay on team names through the game, then go away at the end.
  function cookieShiny(t) {
    return t.cookies_eaten > 0 && state.phase !== 'ended' ? ' cookie-shiny' : '';
  }
  function cookieCrown(t) {
    return t.cookie_crown && state.phase !== 'ended'
      ? '<span class="cookie-crown" title="Ate the most cookies" aria-label="Ate the most cookies">🍪<span class="cookie-crown-hat">👑</span></span>'
      : '';
  }

  function renderBoard() {
    // Build a lookup of asked tiles
    const asked = new Set(state.asked.map(a => `${a[0]}|${a[1]}`));

    // Group questions by category, sort by points
    const byCat = {};
    state.tiles.forEach(t => {
      if (!byCat[t.category]) byCat[t.category] = [];
      byCat[t.category].push(t);
    });
    Object.values(byCat).forEach(arr => arr.sort((a, b) => a.points - b.points));

    // One column per category (header + its tiles). On wide screens CSS flows the
    // columns into the classic grid; on phones each column becomes its own card.
    const rows = Math.max(...Object.values(byCat).map(arr => arr.length), 6);
    const cols = state.categories.length;
    boardGrid.style.setProperty('--rows', rows);
    boardGrid.style.setProperty('--cols', cols);
    let html = '';
    state.categories.forEach((cat, col) => {
      html += `<div class="board-col"><div class="category-cell">${escapeHtml(cat)}</div>`;
      for (let row = 0; row < rows; row++) {
        const tile = (byCat[cat] || [])[row];
        // Stagger the entrance by on-screen (row-major) order, first two rows only
        const idx = row * cols + col;
        const delay = idx < 12 ? ` style="animation-delay:${(idx + 1) * 0.02}s"` : '';
        if (!tile) {
          html += `<button class="tile" disabled${delay}></button>`;
        } else {
          const isAsked = asked.has(`${tile.category}|${tile.points}`);
          html += `<button class="tile ${isAsked ? 'asked' : ''}" data-cat="${escapeAttr(tile.category)}" data-pts="${tile.points}" ${isAsked || state.phase !== 'board' ? 'disabled' : ''}${delay}>${tile.points}</button>`;
        }
      }
      html += '</div>';
    });
    boardGrid.innerHTML = html;
    boardGrid.querySelectorAll('.tile').forEach(b => {
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

    // Timer — starts when a player buzzes, not when question is picked
    const key = `${cur.category}|${cur.points}`;
    const buzzKey = `buzzed|${key}`;
    if (state.phase === 'buzzed') {
      if (timerKey !== buzzKey) {
        timerKey = buzzKey;
        timerStartedAt = Date.now();
        startTimer();
      }
    } else {
      stopTimer();
      qTimer.textContent = '';
      qTimer.classList.remove('expired');
      if (state.phase === 'question') timerKey = null;
    }

    // Buzz info — shown in buzzed and reveal phases
    if (cur.buzzed_team) {
      buzzInfo.hidden = false;
      const team = state.teams.find(t => t.name === cur.buzzed_team);
      const player = team?.members.find(m => m.id === cur.buzzed_player);
      buzzInfo.innerHTML = `<span class="buzz-team-name">${escapeHtml(cur.buzzed_team)}</span><span class="buzz-player-name">${escapeHtml(player ? player.name : '???')} buzzed in</span>`;
      if (team && qModalCard) {
        qModalCard.style.background = team.color_bg;
        qModalCard.style.color = team.color_fg;
        qModalCard.classList.add('team-buzzed');
      }
    } else {
      buzzInfo.hidden = true;
      if (qModalCard) {
        qModalCard.style.background = '';
        qModalCard.style.color = '';
        qModalCard.classList.remove('team-buzzed');
      }
    }

    // Answer — only after timer expires (reveal phase)
    if (cur.answer && state.phase === 'reveal') {
      qAnswer.hidden = false;
      qAnswer.textContent = `Answer: ${cur.answer}`;
    } else {
      qAnswer.hidden = true;
    }

    // Buttons
    correctBtn.textContent = `Correct +${cur.points}`;
    wrongBtn.textContent = `Wrong −${cur.points}`;
    revealBtn.hidden = true;
    correctBtn.hidden = state.phase !== 'reveal';
    wrongBtn.hidden = state.phase !== 'reveal';
    nextBtn.hidden = true;
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
