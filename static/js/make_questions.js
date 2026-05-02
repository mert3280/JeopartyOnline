(() => {
  const POINT_TIERS = [100, 200, 300, 400, 500, 600];
  const NUM_CATEGORIES = 6;

  const tabsEl = document.getElementById('cat-tabs');
  const panelsEl = document.getElementById('cat-panels');
  const setNameInput = document.getElementById('set-name');
  const errorBox = document.getElementById('error');
  const form = document.getElementById('make-form');
  const successBox = document.getElementById('success');
  const successMsg = document.getElementById('success-msg');

  let activeIdx = 0;

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function buildTabs() {
    tabsEl.innerHTML = '';
    for (let i = 0; i < NUM_CATEGORIES; i++) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cat-tab';
      btn.dataset.idx = i;
      btn.textContent = `Cat ${i + 1}`;
      btn.addEventListener('click', () => setActive(i));
      tabsEl.appendChild(btn);
    }
  }

  function buildPanels() {
    panelsEl.innerHTML = '';
    for (let i = 0; i < NUM_CATEGORIES; i++) {
      const panel = document.createElement('div');
      panel.className = 'cat-panel';
      panel.dataset.idx = i;

      const catField = document.createElement('div');
      catField.className = 'field';
      catField.innerHTML = `
        <label class="label" for="cat-name-${i}">Category ${i + 1} title</label>
        <input id="cat-name-${i}" class="input cat-name" type="text" maxlength="40"
               data-idx="${i}" placeholder="e.g. Movies" required>
      `;
      panel.appendChild(catField);

      POINT_TIERS.forEach((pts, qIdx) => {
        const qBlock = document.createElement('div');
        qBlock.className = 'mq-block';
        qBlock.innerHTML = `
          <div class="mq-points">${pts}</div>
          <div class="mq-fields">
            <textarea class="input mq-question" rows="2" maxlength="500"
                      data-cat="${i}" data-pts="${pts}"
                      placeholder="Question / clue" required></textarea>
            <input type="text" class="input mq-answer" maxlength="200"
                   data-cat="${i}" data-pts="${pts}"
                   placeholder="Answer" required>
          </div>
        `;
        panel.appendChild(qBlock);
      });

      panelsEl.appendChild(panel);
    }
  }

  function setActive(i) {
    activeIdx = i;
    tabsEl.querySelectorAll('.cat-tab').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.idx, 10) === i);
    });
    panelsEl.querySelectorAll('.cat-panel').forEach(panel => {
      panel.classList.toggle('active', parseInt(panel.dataset.idx, 10) === i);
    });
    refreshTabStatus();
  }

  function refreshTabStatus() {
    for (let i = 0; i < NUM_CATEGORIES; i++) {
      const btn = tabsEl.querySelector(`.cat-tab[data-idx="${i}"]`);
      const panel = panelsEl.querySelector(`.cat-panel[data-idx="${i}"]`);
      if (!btn || !panel) continue;
      const cat = panel.querySelector('.cat-name').value.trim();
      const qs = panel.querySelectorAll('.mq-question');
      const as = panel.querySelectorAll('.mq-answer');
      let filled = !!cat;
      qs.forEach((q, j) => { if (!q.value.trim() || !as[j].value.trim()) filled = false; });
      btn.classList.toggle('done', filled);
    }
  }

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
    errorBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function hideError() { errorBox.hidden = true; }

  function collect() {
    const name = setNameInput.value.trim();
    const categories = [];
    const questions = [];
    let firstMissingCat = -1;

    for (let i = 0; i < NUM_CATEGORIES; i++) {
      const panel = panelsEl.querySelector(`.cat-panel[data-idx="${i}"]`);
      const cat = panel.querySelector('.cat-name').value.trim();
      if (!cat) { if (firstMissingCat < 0) firstMissingCat = i; categories.push(''); }
      else categories.push(cat);

      POINT_TIERS.forEach(pts => {
        const q = panel.querySelector(`.mq-question[data-pts="${pts}"]`).value.trim();
        const a = panel.querySelector(`.mq-answer[data-pts="${pts}"]`).value.trim();
        questions.push({
          category: String(i + 1),
          question: q,
          answer: a,
          points: pts,
          _missing: !q || !a,
          _catIdx: i,
        });
      });
    }

    return { name, categories, questions, firstMissingCat };
  }

  form.addEventListener('input', refreshTabStatus);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();

    const { name, categories, questions, firstMissingCat } = collect();
    if (!name) { showError('Set name is required'); return; }
    if (firstMissingCat >= 0) {
      setActive(firstMissingCat);
      showError(`Category ${firstMissingCat + 1} title is missing`);
      return;
    }
    const missingQ = questions.find(q => q._missing);
    if (missingQ) {
      setActive(missingQ._catIdx);
      showError(`A question/answer is empty in Category ${missingQ._catIdx + 1}`);
      return;
    }

    const payload = {
      name,
      categories,
      questions: questions.map(({ category, question, answer, points }) => (
        { category, question, answer, points }
      )),
    };

    try {
      const res = await fetch('/api/question-sets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || 'Save failed');
        return;
      }
      form.hidden = true;
      successBox.hidden = false;
      successMsg.textContent = `Saved as "${data.name}" — available in the Create Game dropdown.`;
    } catch (err) {
      showError('Network error');
    }
  });

  buildTabs();
  buildPanels();
  setActive(0);
})();
