(() => {
  const code = window.GAME.code;
  const tokenKey = `jeoparty:judge:${code}`;
  const socket = io({ transports: ['polling', 'websocket'] });
  const el = id => document.getElementById(id);
  let token = null;
  let state = null;
  let replaced = false;
  try { token = localStorage.getItem(tokenKey); } catch (e) { /* use in-memory token */ }

  function hideQuestion() {
    state = null;
    el('judge-question').hidden = true;
    el('judge-answer').textContent = '';
    el('judge-waiting').hidden = true;
  }

  socket.on('connect', () => {
    if (replaced) return;
    el('judge-connection').textContent = 'Connecting private host screen…';
    socket.emit('judge:join', { code, judge_token: token });
  });
  socket.on('disconnect', () => {
    hideQuestion();
    el('judge-connection').textContent = replaced
      ? 'Another private host screen took over. Rejoin to request approval again.'
      : 'Reconnecting… Play pauses until both host screens are connected.';
  });
  socket.on('judge:pending', data => {
    hideQuestion();
    el('judge-pairing').hidden = false;
    el('pairing-code').textContent = data.pairing_code;
    el('judge-connection').textContent = 'Waiting for approval on the game board.';
  });
  socket.on('judge:approved', data => {
    token = data.judge_token;
    try { localStorage.setItem(tokenKey, token); } catch (e) { /* use in-memory token */ }
    el('judge-pairing').hidden = true;
    el('judge-error').hidden = true;
  });
  socket.on('judge:replaced', () => {
    replaced = true;
    hideQuestion();
    socket.disconnect();
  });
  socket.on('error', data => {
    hideQuestion();
    el('judge-connection').textContent = 'Unable to connect.';
    el('judge-error').textContent = data.message || 'Connection failed.';
    el('judge-error').hidden = false;
  });
  ['game:cancelled', 'game:ended'].forEach(event => socket.on(event, () => {
    try { localStorage.removeItem(tokenKey); } catch (e) { /* storage blocked */ }
    window.location.href = '/join';
  }));

  socket.on('state', data => {
    state = data;
    document.documentElement.setAttribute('data-theme', state.theme);
    el('judge-connection').textContent = state.screens_ready
      ? 'Both host screens connected.' : 'Play paused: reconnect the game board screen.';
    const cur = state.current;
    el('judge-question').hidden = !cur;
    el('judge-waiting').hidden = !!cur;
    if (!cur) {
      el('judge-answer').textContent = '';
      el('judge-waiting').textContent = state.phase === 'lobby'
        ? 'Ready. Start the game from the board when players have joined.'
        : state.phase === 'ended' ? 'Game over. Final standings are on the game board.'
        : 'Waiting for the board to open a question.';
      return;
    }
    el('judge-category').textContent = cur.category;
    el('judge-points').textContent = `${cur.available_points} pts · original ${cur.points}`;
    el('judge-clue').textContent = cur.question;
    el('judge-answer').textContent = `Answer: ${cur.answer}`;
    el('judge-attempt').textContent = `Steals used: ${cur.steals_used}/${state.steal_opportunities}. Teams attempted: ${cur.attempted_teams.join(', ') || 'none'}.`;
    el('judge-buzz').textContent = cur.buzzed_team
      ? `${cur.buzzed_team} is answering${state.phase === 'reveal' ? ' — time is up; judge their answer.' : '.'}`
      : 'Buzzers open. Waiting for a team…';
    const canJudge = state.screens_ready && !!cur.buzzed_team && ['buzzed', 'reveal'].includes(state.phase);
    el('judge-correct').disabled = el('judge-wrong').disabled = !canJudge;
    el('judge-correct').textContent = `Correct +${cur.available_points}`;
    el('judge-wrong').textContent = 'Wrong · no penalty';
    updateTimer();
  });

  function judge(correct) {
    if (!state?.screens_ready || !state.current?.buzzed_team) return;
    el('judge-correct').disabled = el('judge-wrong').disabled = true;
    socket.emit('host:judge', { code, correct });
  }
  el('judge-correct').addEventListener('click', () => judge(true));
  el('judge-wrong').addEventListener('click', () => judge(false));
  el('judge-skip').addEventListener('click', () => socket.emit('host:skip_question', { code }));

  function updateTimer() {
    const deadline = state?.current?.buzz_deadline;
    el('judge-timer').textContent = state?.phase === 'buzzed' && deadline
      ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : '';
  }
  setInterval(updateTimer, 100);
  let wakeLock = null;
  async function stayAwake() {
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    try { wakeLock = await navigator.wakeLock.request('screen'); } catch (e) { /* unsupported or denied */ }
  }
  document.addEventListener('visibilitychange', () => {
    if (!wakeLock || wakeLock.released) stayAwake();
  });
  stayAwake();
})();
