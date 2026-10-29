(() => {
  const setSelect = document.getElementById('set-select');
  const setHint = document.getElementById('set-hint');
  const timeInput = document.getElementById('time-input');
  const cookiesInput = document.getElementById('cookies-input');
  const errorBox = document.getElementById('error');
  const form = document.getElementById('create-form');
  const themePicker = document.getElementById('theme-picker');

  let sets = [];
  let selectedTheme = 'classic';

  // Theme picker — live preview
  if (themePicker) {
    themePicker.querySelectorAll('.theme-swatch').forEach(swatch => {
      swatch.addEventListener('click', () => {
        const theme = swatch.dataset.themeValue;
        selectedTheme = theme;
        document.documentElement.setAttribute('data-theme', theme);
        themePicker.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('selected'));
        swatch.classList.add('selected');
      });
    });
    // Mark default selection
    const defaultSwatch = themePicker.querySelector('.theme-swatch[data-theme-value="classic"]');
    if (defaultSwatch) defaultSwatch.classList.add('selected');
  }

  // Load question sets
  fetch('/api/question-sets')
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Failed to load question sets');
      return data;
    })
    .then(data => {
      sets = data;
      if (sets.length === 0) {
        setSelect.innerHTML = '<option value="">No question sets available</option>';
        setSelect.disabled = true;
        return;
      }
      setSelect.replaceChildren(...sets.map(s => new Option(s.name, s.filename)));
      updateSetHint();
    })
    .catch(err => {
      setSelect.innerHTML = '<option value="">Failed to load question sets</option>';
      setSelect.disabled = true;
      showError(err.message);
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

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();
    if (!setSelect.value) {
      showError('Pick a question set');
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
          question_time: time,
          theme: selectedTheme,
          cookies_enabled: cookiesInput.checked,
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
})();
