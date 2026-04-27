(() => {
  const setSelect = document.getElementById('set-select');
  const setHint = document.getElementById('set-hint');
  const teamList = document.getElementById('team-list');
  const teamInput = document.getElementById('team-input');
  const addTeamBtn = document.getElementById('add-team-btn');
  const timeInput = document.getElementById('time-input');
  const errorBox = document.getElementById('error');
  const form = document.getElementById('create-form');

  let teams = [];
  let sets = [];

  // Load question sets
  fetch('/api/question-sets')
    .then(r => r.json())
    .then(data => {
      sets = data;
      if (sets.length === 0) {
        setSelect.innerHTML = '<option value="">No question sets found in questions/</option>';
        setSelect.disabled = true;
        return;
      }
      setSelect.innerHTML = sets.map(s => `<option value="${s.filename}">${s.name}</option>`).join('');
      updateSetHint();
    })
    .catch(() => {
      setSelect.innerHTML = '<option value="">Failed to load question sets</option>';
      setSelect.disabled = true;
    });

  setSelect.addEventListener('change', updateSetHint);

  function updateSetHint() {
    const s = sets.find(s => s.filename === setSelect.value);
    if (s) {
      setHint.textContent = `${s.question_count} questions · categories: ${s.categories.join(', ')}`;
    } else {
      setHint.textContent = '';
    }
  }

  function renderTeams() {
    teamList.innerHTML = teams.map((t, i) => `
      <span class="team-chip">${escapeHtml(t)} <button type="button" data-i="${i}" aria-label="Remove">×</button></span>
    `).join('');
    teamList.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        teams.splice(parseInt(btn.dataset.i, 10), 1);
        renderTeams();
      });
    });
  }

  function addTeam() {
    const name = teamInput.value.trim();
    if (!name) return;
    if (teams.includes(name)) {
      showError('Team names must be unique');
      return;
    }
    teams.push(name);
    teamInput.value = '';
    teamInput.focus();
    renderTeams();
    hideError();
  }

  addTeamBtn.addEventListener('click', addTeam);
  teamInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTeam();
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();
    if (!setSelect.value) {
      showError('Pick a question set');
      return;
    }
    if (teams.length === 0) {
      showError('Add at least one team');
      return;
    }
    const time = parseInt(timeInput.value, 10);
    if (isNaN(time) || time < 1 || time > 120) {
      showError('Question time must be between 1 and 120');
      return;
    }

    try {
      const res = await fetch('/api/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_set: setSelect.value,
          teams,
          question_time: time,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || 'Create failed');
        return;
      }
      // Stash host token so the host page can authenticate
      localStorage.setItem(`jeoparty:host:${data.code}`, data.host_token);
      window.location.href = data.host_url;
    } catch (err) {
      showError('Network error');
    }
  });

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }
  function hideError() {
    errorBox.hidden = true;
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
})();
