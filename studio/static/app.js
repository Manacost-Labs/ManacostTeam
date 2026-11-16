// Manacost Studio — ванильный модуль без зависимостей. Весь внешний текст
// выводится через textContent; ссылки — только http(s).

const $ = (id) => document.getElementById(id);

const GENRES = {
  hearthstone: [
    ['', 'По умолчанию'],
    ['constructed-guide', 'Гайд (Стандарт/Вольный)'],
    ['anti-guide', 'Антигайд'],
    ['battlegrounds-guide', 'Гайд по Полям сражений'],
    ['battlegrounds-article', 'Статья о Полях сражений'],
    ['analytics-article', 'Аналитика'],
    ['meta-report', 'Мета-отчёт'],
    ['news', 'Новость'],
  ],
  'world-of-warcraft': [
    ['', 'По умолчанию'],
    ['wow-guide', 'Гайд по WoW'],
    ['meta-report', 'Мета-отчёт'],
    ['news', 'Новость'],
    ['game-guide', 'Игровой гайд'],
    ['game-article', 'Статья'],
  ],
  other: [
    ['game-guide', 'Игровой гайд'],
    ['game-article', 'Статья'],
    ['news', 'Новость'],
  ],
};

const SEVERITY = { error: 'Ошибка', likely: 'Вероятно', review: 'На проверку' };

class ApiError extends Error {}

async function api(path, body) {
  const options = body === undefined
    ? { credentials: 'same-origin' }
    : {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      };
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError('Сеть недоступна: запрос не дошёл до Studio.');
  }
  if (response.status === 401) {
    window.location.assign('/auth/login');
    throw new ApiError('Сессия истекла — перенаправляю на вход…');
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.error) || `Ошибка ${response.status}`;
    const detail = data && typeof data.detail === 'string' ? ` (${data.detail})` : '';
    throw new ApiError(message + detail);
  }
  return data;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === '') continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

function chip(text, kind = '') {
  return el('span', { class: `chip ${kind}`.trim(), text });
}

// Кнопка выполняет действие только по явному нажатию; во время запроса заблокирована.
function bind(buttonId, statusId, busyText, action) {
  const button = $(buttonId);
  const status = $(statusId);
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    const started = Date.now();
    button.disabled = true;
    status.className = 'status busy';
    status.textContent = busyText;
    try {
      const note = await action();
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      status.className = 'status';
      status.textContent = note ? `${note} · ${seconds} с` : `Готово · ${seconds} с`;
    } catch (error) {
      status.className = 'status error';
      status.textContent = error instanceof ApiError ? error.message : `Ошибка: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
}

function requireText(id, message) {
  const value = $(id).value;
  if (!value.trim()) {
    $(id).focus();
    throw new ApiError(message);
  }
  return value;
}

// ---------- Вкладки ----------
function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const select = (tab, focus = false) => {
    for (const other of tabs) {
      const active = other === tab;
      other.setAttribute('aria-selected', String(active));
      other.tabIndex = active ? 0 : -1;
      $(other.getAttribute('aria-controls')).hidden = !active;
    }
    if (focus) tab.focus();
    try { localStorage.setItem('studio-tab', tab.id); } catch { /* приватный режим */ }
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (step) select(tabs[(index + step + tabs.length) % tabs.length], true);
    });
  });
  let saved = null;
  try { saved = localStorage.getItem('studio-tab'); } catch { /* ignore */ }
  const initial = tabs.find((tab) => tab.id === saved);
  if (initial) select(initial);
}

// ---------- Копирование ----------
function setupCopy() {
  for (const button of document.querySelectorAll('button.copy')) {
    button.addEventListener('click', async () => {
      const target = $(button.dataset.copy);
      const text = 'value' in target ? target.value : target.innerText;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        if ('select' in target) { target.select(); document.execCommand('copy'); }
      }
      const label = button.textContent;
      button.textContent = 'Скопировано';
      setTimeout(() => { button.textContent = label; }, 1500);
    });
  }
}

// ---------- Исследование ----------
function renderAnswer(container, answer, sources) {
  container.replaceChildren();
  const byNumber = new Map(sources.map((source) => [source.n, source]));
  const pattern = /\[(\d{1,3})\]/g;
  let last = 0;
  for (const match of answer.matchAll(pattern)) {
    container.append(answer.slice(last, match.index));
    const source = byNumber.get(Number(match[1]));
    const href = source && safeUrl(source.url);
    container.append(href
      ? el('a', { href, target: '_blank', rel: 'noopener noreferrer', title: source.title }, match[0])
      : match[0]);
    last = match.index + match[0].length;
  }
  container.append(answer.slice(last));
}

function setupResearch() {
  bind('research-run', 'research-status', 'Ищу источники и готовлю ответ…', async () => {
    const query = requireText('research-query', 'Сформулируйте вопрос.').trim();
    const providers = [...document.querySelectorAll('#research-providers input:checked')].map((box) => box.value);
    if (!providers.length) throw new ApiError('Выберите хотя бы одного провайдера.');
    const data = await api('/api/research', { query, providers, timeframe: $('research-timeframe').value });
    renderAnswer($('research-answer'), data.answer, data.sources);
    $('research-sources').replaceChildren(...data.sources.map((source) => {
      const href = safeUrl(source.url);
      const meta = [source.platform, source.where, source.date && source.date.slice(0, 10)].filter(Boolean).join(' · ');
      return el('li', { value: String(source.n) },
        href ? el('a', { href, target: '_blank', rel: 'noopener noreferrer' }, source.title) : source.title,
        el('div', { class: 'meta', text: meta }));
    }));
    const errors = data.provider_errors || [];
    $('research-errors').replaceChildren(...(errors.length
      ? [el('p', { class: 'muted small', text: 'Не ответили: ' + errors.map((e) => `${e.title} — ${e.error}`).join('; ') })]
      : []));
    $('research-result').hidden = false;
    return `Источников: ${data.sources.length}${data.model ? ` · модель ${data.model}` : ''}`;
  });
}

// ---------- Редактура ----------
function fillGenres() {
  const game = $('edit-game').value;
  const options = GENRES[game] || GENRES.other;
  $('edit-genre').replaceChildren(...options.map(([value, label]) => el('option', { value, text: label })));
}

function editBody(withMode) {
  const body = {
    text: requireText('edit-text', 'Вставьте текст.'),
    game: $('edit-game').value,
  };
  if ($('edit-genre').value) body.genre = $('edit-genre').value;
  if ($('edit-patch').value.trim()) body.patch = $('edit-patch').value.trim();
  if (withMode) body.mode = $('edit-mode').value;
  return body;
}

function finding(item) {
  const severity = item.severity || 'review';
  const where = [SEVERITY[severity] || severity, item.analyzer, item.line ? `строка ${item.line}` : '']
    .filter(Boolean).join(' · ');
  return el('li', { class: severity },
    el('div', { class: 'where', text: where }),
    el('div', { text: item.message || item.id || '' }),
    item.evidence ? el('div', { class: 'evidence', text: item.evidence }) : null,
    item.suggestion ? el('div', { class: 'muted', text: `→ ${item.suggestion}` }) : null);
}

function setupEdit() {
  fillGenres();
  $('edit-game').addEventListener('change', fillGenres);

  bind('edit-analyze', 'edit-status', 'Проверяю текст анализаторами…', async () => {
    const data = await api('/api/edit/analyze', editBody(false));
    const summary = data.summary || {};
    $('edit-summary').replaceChildren(
      chip(`Ошибки: ${summary.error ?? 0}`, summary.error ? 'bad' : 'ok'),
      chip(`Вероятные: ${summary.likely ?? 0}`),
      chip(`На проверку: ${summary.review ?? 0}`),
      ...(data.analyzers_skipped && data.analyzers_skipped.length
        ? [chip(`Пропущены: ${data.analyzers_skipped.join(', ')}`)] : []));
    $('edit-output-wrap').hidden = true;
    $('edit-findings').replaceChildren(...(data.findings || []).map(finding));
    $('edit-result').hidden = false;
    return `Находок: ${(data.findings || []).length}`;
  });

  bind('edit-run', 'edit-status', 'Модель правит текст — это может занять пару минут…', async () => {
    const data = await api('/api/edit/run', editBody(true));
    const chips = [
      chip(data.accepted ? 'Правка принята' : 'Правка не принята', data.accepted ? 'ok' : 'bad'),
      chip(`Статус: ${data.status || '—'}`),
      chip(`Изменений: ${(data.changes || []).length}`),
    ];
    if (data.checks_complete === false) chips.push(chip('Проверки неполные', 'bad'));
    if (data.model) chips.push(chip(`Модель: ${data.model}`));
    $('edit-summary').replaceChildren(...chips);
    $('edit-output').value = data.text || '';
    $('edit-output-wrap').hidden = false;
    const notes = [
      ...(data.rejection_reasons || []).map((text) => ({ severity: 'error', message: text, analyzer: 'причина отказа' })),
      ...(data.factual_risks || []).map((text) => ({ severity: 'likely', message: text, analyzer: 'фактический риск' })),
      ...(data.regressions || []).map((text) => ({ severity: 'likely', message: text, analyzer: 'регрессия' })),
      ...(data.qa_findings || []),
    ];
    $('edit-findings').replaceChildren(...notes.map(finding));
    $('edit-result').hidden = false;
    return data.accepted ? 'Правка готова' : 'Правка не принята — возвращён исходник';
  });
}

// ---------- Шорткоды ----------
function setupShortcodes(session) {
  if (session && session.catalog_available === false) {
    const note = $('shortcodes-catalog');
    note.textContent = 'Каталог карт не подключён (CARD_CATALOG_FILE). Без него шорткоды не расставляются.';
    note.hidden = false;
  }
  bind('shortcodes-run', 'shortcodes-status', 'Ищу точные имена карт…', async () => {
    const data = await api('/api/shortcodes', {
      text: requireText('shortcodes-text', 'Вставьте текст.'),
      format: $('shortcodes-format').value,
    });
    $('shortcodes-output').value = data.text;
    $('shortcodes-summary').replaceChildren(
      chip(`Режим: ${data.format_title}`),
      chip(`Вставлено: ${data.inserted}`, data.inserted ? 'ok' : ''),
      ...(data.review.length ? [chip(`На проверку: ${data.review.join(', ')}`, 'bad')] : []));
    $('shortcodes-result').hidden = false;
    return `Вставлено шорткодов: ${data.inserted}`;
  });
}

// ---------- Перевод ----------
function setupTranslate() {
  const toggleProduct = () => {
    $('translate-product-wrap').hidden = $('translate-game').value !== 'world-of-warcraft';
  };
  $('translate-game').addEventListener('change', toggleProduct);
  toggleProduct();

  bind('translate-run', 'translate-status', 'Готовлю термины, перевожу и проверяю…', async () => {
    const body = {
      text: requireText('translate-text', 'Вставьте исходный текст.'),
      game: $('translate-game').value,
      style: $('translate-style').value,
    };
    if ($('translate-patch').value.trim()) body.patch = $('translate-patch').value.trim();
    if (body.game === 'world-of-warcraft' && $('translate-product').value.trim()) {
      body.product = $('translate-product').value.trim();
    }
    const data = await api('/api/translate', body);
    const qa = data.qa || {};
    $('translate-output').value = data.translation;
    $('translate-summary').replaceChildren(
      chip(qa.ready_for_editor ? 'QA пройден' : 'QA: есть замечания', qa.ready_for_editor ? 'ok' : 'bad'),
      chip(`Защищено терминов: ${data.terms_protected}`),
      ...(data.model ? [chip(`Модель: ${data.model}`)] : []));
    const issues = [];
    const add = (cond, message, evidence) => { if (cond) issues.push({ severity: 'likely', analyzer: 'QA', message, evidence }); };
    add(qa.numbers_match === false, 'Числа не совпадают с оригиналом', (qa.missing_numbers || []).join(', '));
    add(qa.links_match === false, 'Ссылки не совпадают с оригиналом', (qa.missing_links || []).join(' '));
    add(qa.code_spans_match === false, 'Количество фрагментов кода изменилось');
    add((qa.missing_terms || []).length, 'Утверждённые термины не найдены в переводе', (qa.missing_terms || []).join(', '));
    add((qa.leaked_markers || []).length, 'В переводе остались служебные маркеры', (qa.leaked_markers || []).join(' '));
    add(qa.table_row_delta, `Изменилось число строк таблиц: ${qa.table_row_delta}`);
    for (const name of data.review_candidates || []) {
      issues.push({ severity: 'review', analyzer: 'имя без утверждённой пары', message: name });
    }
    for (const warning of data.resource_warnings || []) {
      issues.push({ severity: 'review', analyzer: 'ресурсы', message: String(warning) });
    }
    $('translate-qa').replaceChildren(...issues.map(finding));
    $('translate-result').hidden = false;
    return qa.ready_for_editor ? 'Перевод готов' : 'Перевод готов, проверьте замечания QA';
  });
}

// ---------- Сессия ----------
async function setupSession() {
  let session = null;
  try {
    session = await api('/api/session');
    $('user-name').textContent = session.name || session.sub;
  } catch {
    session = null;
  }
  $('logout').addEventListener('click', async () => {
    try { await api('/auth/logout', {}); } catch { /* cookie всё равно истечёт */ }
    document.querySelector('main').hidden = true;
    document.querySelector('.tabs').hidden = true;
    $('signed-out').hidden = false;
  });
  return session;
}

const session = await setupSession();
setupTabs();
setupCopy();
setupResearch();
setupEdit();
setupShortcodes(session);
setupTranslate();
