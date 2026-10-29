(() => {
  const listEl = document.getElementById('sets-list');
  const emptyEl = document.getElementById('sets-empty');
  const errorBox = document.getElementById('error');
  const noticeBox = document.getElementById('notice');
  const uploadInput = document.getElementById('upload-input');

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }
  function hideError() { errorBox.hidden = true; }

  function showNotice(msg) {
    noticeBox.textContent = msg;
    noticeBox.hidden = false;
  }

  async function request(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Request failed');
    return data;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(label, className, onClick) {
    const btn = el('button', `btn ${className} btn-small`, label);
    btn.type = 'button';
    btn.addEventListener('click', onClick);
    return btn;
  }

  function passwordInput() {
    const input = el('input', 'input qs-rename-input');
    input.type = 'password';
    input.placeholder = 'Set or master password';
    input.autocomplete = 'current-password';
    input.setAttribute('aria-label', 'Set or master password');
    return input;
  }

  function renderRow(set) {
    const li = el('li', 'qs-item');
    const url = `/api/question-sets/${encodeURIComponent(set.filename)}`;

    const info = el('div', 'qs-info');
    const name = el('div', 'qs-name', set.name);
    const meta = el('div', 'qs-meta', set.categories.join(' · '));
    info.append(name, meta);

    const actions = el('div', 'qs-actions');

    function showDefault() {
      li.classList.remove('confirming');
      info.replaceChildren(name, meta);
      actions.replaceChildren(
        button('Edit', 'btn-primary', () => {
          window.location.href = `/question-sets/${encodeURIComponent(set.filename)}/edit`;
        }),
        button('Rename', 'btn-ghost', showRename),
        button('Download', 'btn-ghost', () => {
          window.location.href = `/question-sets/${encodeURIComponent(set.filename)}/download`;
        }),
        button('Delete', 'btn-danger', showConfirmDelete),
      );
    }

    function showRename() {
      hideError();
      const input = el('input', 'input qs-rename-input');
      input.type = 'text';
      input.maxLength = 60;
      input.value = set.name;
      input.setAttribute('aria-label', 'New set name');
      const password = passwordInput();

      async function save() {
        const newName = input.value.trim();
        if (!newName) { showError('Set name is required'); return; }
        if (newName === set.name) { hideError(); showDefault(); return; }
        if (!password.value) { showError('Enter the password to rename'); password.focus(); return; }
        try {
          const data = await request('PATCH', url, { name: newName, password: password.value });
          set.name = data.name;
          name.textContent = data.name;
          hideError();
          showDefault();
        } catch (err) {
          showError(err.message);
        }
      }

      [input, password].forEach(field => field.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') { hideError(); showDefault(); }
      }));

      info.replaceChildren(input, password);
      actions.replaceChildren(
        button('Save', 'btn-good', save),
        button('Cancel', 'btn-ghost', () => { hideError(); showDefault(); }),
      );
      input.focus();
      input.select();
    }

    function showConfirmDelete() {
      hideError();
      li.classList.add('confirming');
      const prompt = el('div', 'qs-name');
      prompt.textContent = `Delete "${set.name}"?`;
      const password = passwordInput();

      async function confirmDelete() {
        if (!password.value) { showError('Enter the password to delete'); password.focus(); return; }
        try {
          await request('DELETE', url, { password: password.value });
          hideError();
          li.remove();
          emptyEl.hidden = listEl.children.length > 0;
        } catch (err) {
          showError(err.message);
          password.select();
        }
      }

      password.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); confirmDelete(); }
        if (e.key === 'Escape') { hideError(); showDefault(); }
      });

      info.replaceChildren(prompt, el('div', 'qs-meta', 'This cannot be undone.'), password);
      actions.replaceChildren(
        button('Delete', 'btn-danger', confirmDelete),
        button('Cancel', 'btn-ghost', () => { hideError(); showDefault(); }),
      );
      password.focus();
    }

    li.append(info, actions);
    showDefault();
    return li;
  }

  async function load() {
    try {
      const sets = await request('GET', '/api/question-sets');
      listEl.replaceChildren(...sets.map(renderRow));
      emptyEl.hidden = sets.length > 0;
    } catch (err) {
      showError(err.message || 'Could not load question sets');
    }
  }

  async function uploadFile(file) {
    let parsed;
    try {
      parsed = JSON.parse(await file.text());
    } catch (err) {
      return { ok: [], failed: [`${file.name}: not valid JSON`] };
    }
    const sets = Array.isArray(parsed) ? parsed : [parsed];
    const fallbackName = file.name.replace(/\.json$/i, '');
    const ok = [];
    const failed = [];
    for (const [i, set] of sets.entries()) {
      const label = sets.length > 1 ? `${file.name} (set ${i + 1})` : file.name;
      if (!set || typeof set !== 'object' || Array.isArray(set)) {
        failed.push(`${label}: expected a set object`);
        continue;
      }
      const body = { ...set, name: typeof set.name === 'string' && set.name.trim() ? set.name : fallbackName };
      try {
        const data = await request('POST', '/api/question-sets', body);
        ok.push(data.name);
      } catch (err) {
        failed.push(`${label}: ${err.message}`);
      }
    }
    return { ok, failed };
  }

  uploadInput.addEventListener('change', async () => {
    const files = Array.from(uploadInput.files);
    uploadInput.value = '';
    if (!files.length) return;
    hideError();
    noticeBox.hidden = true;

    const ok = [];
    const failed = [];
    for (const file of files) {
      const result = await uploadFile(file);
      ok.push(...result.ok);
      failed.push(...result.failed);
    }
    if (ok.length) {
      showNotice(`Uploaded ${ok.length} set${ok.length === 1 ? '' : 's'}: ${ok.join(', ')}`);
      await load();
    }
    if (failed.length) showError(`Could not upload:\n${failed.join('\n')}`);
  });

  load();
})();
