// =========================================================================
// AutoRewarder — UI script
// =========================================================================

let accountsCache = [];
let currentAccountId = null;

// =========================================================================
// Toasts
// =========================================================================

const TOAST_ICONS = {
  info:    '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
  warning: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  error:   '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
};

function show_toast(message, type, opts) {
  const kind = TOAST_ICONS[type] ? type : 'info';
  const duration = (opts && opts.duration) || (kind === 'error' ? 5000 : 3500);

  const container = document.getElementById('toast_container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast ' + kind;
  toast.innerHTML =
    TOAST_ICONS[kind] +
    '<div class="toast-msg"></div>' +
    '<button class="toast-close" aria-label="Dismiss">&times;</button>';

  toast.querySelector('.toast-msg').textContent = message;

  const dismiss = () => {
    toast.classList.add('hiding');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  };

  toast.querySelector('.toast-close').addEventListener('click', dismiss);
  container.appendChild(toast);

  if (duration > 0) setTimeout(dismiss, duration);
}

// =========================================================================
// Generic modal (prompt/confirm replacement)
// =========================================================================

let _modalResolve = null;

function open_modal(opts) {
  const backdrop = document.getElementById('app_modal');
  const title = document.getElementById('modal_title');
  const message = document.getElementById('modal_message');
  const input = document.getElementById('modal_input');
  const confirmBtn = document.getElementById('modal_confirm');
  const cancelBtn = document.getElementById('modal_cancel');

  title.textContent = opts.title || '';
  message.textContent = opts.message || '';

  const withInput = Boolean(opts.withInput);
  input.hidden = !withInput;
  input.value = opts.inputDefault || '';
  input.placeholder = opts.inputPlaceholder || '';

  confirmBtn.textContent = opts.confirmLabel || 'OK';
  cancelBtn.textContent = opts.cancelLabel || 'Cancel';
  cancelBtn.hidden = Boolean(opts.hideCancel);
  confirmBtn.className = 'btn-primary' + (opts.danger ? ' danger' : '');

  backdrop.hidden = false;
  setTimeout(() => (withInput ? input : confirmBtn).focus(), 30);

  return new Promise((resolve) => { _modalResolve = resolve; });
}

function close_modal(result) {
  const backdrop = document.getElementById('app_modal');
  backdrop.hidden = true;
  if (_modalResolve) {
    const r = _modalResolve;
    _modalResolve = null;
    r(result);
  }
}

function prompt_modal(title, message, inputDefault, opts) {
  return open_modal({
    title: title,
    message: message || '',
    withInput: true,
    inputDefault: inputDefault || '',
    inputPlaceholder: (opts && opts.placeholder) || '',
    confirmLabel: (opts && opts.confirmLabel) || 'OK',
  });
}

function confirm_modal(title, message, opts) {
  return open_modal({
    title: title,
    message: message || '',
    withInput: false,
    confirmLabel: (opts && opts.confirmLabel) || 'Confirm',
    danger: Boolean(opts && opts.danger),
  });
}

// =========================================================================
// Avatars
// =========================================================================

const AVATAR_PALETTE = [
  '#5b8eff', '#e879a0', '#f59e0b', '#34d399',
  '#a78bfa', '#fbbf24', '#fb7185', '#22d3ee',
];

function avatar_color(id) {
  if (!id) return AVATAR_PALETTE[0];
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

function avatar_initials(label) {
  const s = (label || '?').trim();
  if (!s) return '?';
  const parts = s.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2);
  return (parts[0][0] + parts[parts.length - 1][0]);
}

function make_avatar(account, size) {
  const el = document.createElement('span');
  el.className = 'avatar' + (size ? ' avatar-' + size : '');
  el.style.backgroundColor = avatar_color(account ? account.id : '');
  el.textContent = account ? avatar_initials(account.label) : '?';
  return el;
}

// Backwards compat alias.
function create_avatar(account, size) { return make_avatar(account, size); }

// =========================================================================
// Activity log
// =========================================================================

function clear_log(str) {
  return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

function detect_log_severity(msg) {
  const s = String(msg);
  if (/\[ERROR\]/i.test(s)) return 'error';
  if (/\[WARNING\]/i.test(s)) return 'warning';
  if (/completed|success|done!|ready/i.test(s)) return 'success';
  return '';
}

function update_log(message) {
  const logDiv = document.getElementById('log_area');
  if (!logDiv) return;

  const severity = detect_log_severity(message);
  const safeHtml = clear_log(message).replace(/\n/g, '<br>');
  const line = document.createElement('div');
  line.className = 'log-line' + (severity ? ' ' + severity : '');
  line.innerHTML = safeHtml;
  logDiv.appendChild(line);
  logDiv.scrollTop = logDiv.scrollHeight;
}

const _loggedOnce = new Set();
function update_log_once(message) {
  if (_loggedOnce.has(message)) return;
  _loggedOnce.add(message);
  update_log(message);
}

// =========================================================================
// Start / bot control
// =========================================================================

function start_bot() {
  if (!currentAccountId) {
    show_toast('Add an account first.', 'warning');
    return;
  }

  const current = accountsCache.find(a => a.id === currentAccountId);
  if (!current || !current.first_setup_done) {
    show_toast('Finish the setup for this account before starting.', 'warning');
    return;
  }

  const countStr = document.getElementById('count_input').value;
  const count = parseInt(countStr, 10);

  if (isNaN(count) || count <= 0) {
    show_toast('Enter a valid positive number of queries.', 'warning');
    return;
  }
  if (count > 99) {
    show_toast('Maximum 99 queries per run.', 'warning');
    return;
  }

  const btn = document.getElementById('start_btn');
  btn.disabled = true;
  const label = btn.querySelector('.btn-label');
  if (label) label.textContent = 'Running…';

  update_status_indicator('executing');
  pywebview.api.main(count);
}

function enable_start_button() {
  const btn = document.getElementById('start_btn');
  const label = btn.querySelector('.btn-label');
  if (label) label.textContent = 'Start run';
  const current = accountsCache.find(a => a.id === currentAccountId);
  btn.disabled = !(current && current.first_setup_done);
  update_status_indicator();
}

function update_status_indicator(forceState) {
  const dot = document.getElementById('dot');
  const text = document.getElementById('status_text');
  if (!dot || !text) return;

  dot.classList.remove('active', 'ready', 'warning');

  let state = forceState;
  if (!state) {
    const current = accountsCache.find(a => a.id === currentAccountId);
    if (!current) state = 'empty';
    else if (!current.first_setup_done) state = 'setup';
    else state = 'ready';
  }

  switch (state) {
    case 'executing':
      dot.classList.add('active');
      text.textContent = 'Running…';
      break;
    case 'ready':
      dot.classList.add('ready');
      text.textContent = 'Ready';
      break;
    case 'setup':
      dot.classList.add('warning');
      text.textContent = 'Setup needed';
      break;
    case 'empty':
    default:
      text.textContent = 'No account selected';
      break;
  }
}

function show_history() {
  pywebview.api.open_history_window();
}

function hideBrowserToggle() {
  const toggle = document.getElementById('hideBrowserToggle');
  if (!toggle) return;
  pywebview.api.set_hide_browser(Boolean(toggle.checked));
}

// =========================================================================
// Custom account dropdown
// =========================================================================

function toggle_account_menu(force) {
  const trigger = document.getElementById('account_trigger');
  const menu = document.getElementById('account_menu');
  if (!trigger || !menu) return;

  const shouldOpen = force === undefined ? menu.hidden : force;
  menu.hidden = !shouldOpen;
  trigger.setAttribute('aria-expanded', String(shouldOpen));
}

function render_account_menu() {
  const menu = document.getElementById('account_menu');
  if (!menu) return;

  menu.innerHTML = '';

  if (accountsCache.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'accounts-empty';
    empty.textContent = 'No accounts yet';
    menu.appendChild(empty);
  } else {
    for (const acc of accountsCache) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'account-option' + (acc.is_current ? ' current' : '');
      btn.setAttribute('role', 'option');

      btn.appendChild(make_avatar(acc));

      const info = document.createElement('span');
      info.className = 'account-option-info';
      const name = document.createElement('span');
      name.className = 'account-option-name';
      name.textContent = acc.label;
      const meta = document.createElement('span');
      meta.className = 'account-option-meta';
      meta.textContent = acc.first_setup_done ? 'Ready' : 'Setup pending';
      info.appendChild(name);
      info.appendChild(meta);
      btn.appendChild(info);

      const check = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      check.setAttribute('class', 'account-option-check');
      check.setAttribute('width', '14');
      check.setAttribute('height', '14');
      check.setAttribute('viewBox', '0 0 24 24');
      check.setAttribute('fill', 'none');
      check.setAttribute('stroke', 'currentColor');
      check.setAttribute('stroke-width', '2.5');
      check.setAttribute('stroke-linecap', 'round');
      check.setAttribute('stroke-linejoin', 'round');
      check.innerHTML = '<polyline points="20 6 9 17 4 12"></polyline>';
      btn.appendChild(check);

      btn.addEventListener('click', () => {
        toggle_account_menu(false);
        if (acc.id !== currentAccountId) {
          pywebview.api.switch_account(acc.id).then(ok => {
            if (!ok) show_toast('Could not switch account. Is the bot running?', 'warning');
          });
        }
      });

      menu.appendChild(btn);
    }
  }

  // Divider + actions.
  if (accountsCache.length > 0) {
    const divider = document.createElement('div');
    divider.className = 'menu-divider';
    menu.appendChild(divider);
  }

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'menu-action';
  addBtn.innerHTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>' +
    '<span>Add account</span>';
  addBtn.addEventListener('click', () => {
    toggle_account_menu(false);
    prompt_and_create_account();
  });
  menu.appendChild(addBtn);

  if (accountsCache.length > 0) {
    const manageBtn = document.createElement('button');
    manageBtn.type = 'button';
    manageBtn.className = 'menu-action';
    manageBtn.style.color = 'var(--text-muted)';
    manageBtn.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
      '<span>Manage accounts…</span>';
    manageBtn.addEventListener('click', () => {
      toggle_account_menu(false);
      open_accounts_modal();
    });
    menu.appendChild(manageBtn);
  }
}

function render_account_trigger() {
  const avatarEl = document.getElementById('current_avatar');
  const labelEl = document.getElementById('current_label');
  const metaEl = document.getElementById('current_meta');
  const trigger = document.getElementById('account_trigger');
  if (!avatarEl || !labelEl || !metaEl || !trigger) return;

  const current = accountsCache.find(a => a.id === currentAccountId);

  if (current) {
    avatarEl.textContent = avatar_initials(current.label);
    avatarEl.style.backgroundColor = avatar_color(current.id);
    labelEl.textContent = current.label;
    metaEl.textContent = current.first_setup_done ? 'Ready to run' : 'Setup pending';
    trigger.disabled = false;
  } else {
    avatarEl.textContent = '+';
    avatarEl.style.backgroundColor = 'var(--surface-3)';
    labelEl.textContent = 'No account yet';
    metaEl.textContent = accountsCache.length ? 'Select one below' : 'Add your first account';
    trigger.disabled = accountsCache.length === 0 && false; // keep clickable to open menu
  }
}

// =========================================================================
// Account creation
// =========================================================================

async function prompt_and_create_account() {
  const defaultLabel = `Account ${accountsCache.length + 1}`;
  const label = await prompt_modal(
    'Add a new account',
    'Give this account a name — you can rename it later.',
    defaultLabel,
    { placeholder: defaultLabel, confirmLabel: 'Continue' }
  );
  if (label === null) return;
  const trimmed = String(label).trim() || defaultLabel;

  show_toast(`Opening browser for "${trimmed}". Log in, then close the window.`, 'info', { duration: 6000 });

  pywebview.api.create_account(trimmed).then(result => {
    if (!result || !result.ok) {
      if (result && result.error === 'bot_running') {
        show_toast('Cannot add an account while the bot is running.', 'warning');
      } else if (result && result.error === 'setup_failed') {
        show_toast('Setup cancelled — account not created.', 'warning');
      } else {
        show_toast('Could not create account.', 'error');
      }
    } else {
      show_toast(`Account "${result.label}" is ready.`, 'success');
    }
    refresh_account_ui();
  });
}

// =========================================================================
// Accounts management modal (opens from the header button or dropdown action)
// =========================================================================

function open_accounts_modal() {
  const backdrop = document.getElementById('accounts_modal');
  if (!backdrop) return;
  backdrop.hidden = false;
  if (typeof render_accounts_section === 'function') {
    render_accounts_section(accountsCache);
  }
}

function close_accounts_modal() {
  const backdrop = document.getElementById('accounts_modal');
  if (backdrop) backdrop.hidden = true;
}

// =========================================================================
// Settings modal (general + scheduled run)
// =========================================================================

function open_settings_modal() {
  const backdrop = document.getElementById('settings_modal');
  if (!backdrop) return;

  Promise.all([
    pywebview.api.get_all_schedules(),
    pywebview.api.get_launch_on_startup(),
  ]).then(([schedules, startup]) => {
    render_schedule_cards(schedules || []);

    // Start-with-Windows toggle — disable row on unsupported OS.
    const startupToggle = document.getElementById('startupToggle');
    const startupRow = startupToggle.closest('.settings-row');
    const startupHint = document.getElementById('startup_hint');
    startupToggle.checked = Boolean(startup && startup.enabled);
    if (startup && !startup.supported) {
      startupRow.classList.add('row-disabled');
      startupToggle.disabled = true;
      startupHint.textContent = 'Available on Windows only.';
    } else {
      startupRow.classList.remove('row-disabled');
      startupToggle.disabled = false;
      startupHint.textContent = 'Launch AutoRewarder when you sign in.';
    }
  }).catch(err => {
    console.error('Failed to load settings:', err);
    show_toast('Could not load settings.', 'error');
  });

  backdrop.hidden = false;
}

function close_settings_modal() {
  const backdrop = document.getElementById('settings_modal');
  if (backdrop) backdrop.hidden = true;
}

function render_schedule_cards(schedules) {
  const container = document.getElementById('schedule_accounts_list');
  const empty = document.getElementById('schedule_empty');
  if (!container || !empty) return;

  container.innerHTML = '';

  if (!schedules || schedules.length === 0) {
    container.hidden = true;
    empty.hidden = false;
    return;
  }
  container.hidden = false;
  empty.hidden = true;

  for (const item of schedules) {
    const card = build_schedule_card(item);
    container.appendChild(card);
  }
}

function build_schedule_card(item) {
  const acc = { id: item.id, label: item.label };
  const sched = item.schedule || {};

  const card = document.createElement('div');
  card.className = 'schedule-card' + (sched.enabled ? '' : ' disabled');
  card.dataset.id = item.id;

  // Header: avatar + name/status + enable toggle
  const header = document.createElement('div');
  header.className = 'schedule-card-header';

  header.appendChild(make_avatar(acc));

  const title = document.createElement('div');
  title.className = 'schedule-card-title';
  const name = document.createElement('div');
  name.className = 'schedule-card-name';
  name.textContent = acc.label;
  const status = document.createElement('div');
  status.className = 'schedule-card-status';
  status.textContent =
    (item.first_setup_done ? '' : 'Setup pending · ') +
    (sched.enabled ? 'Schedule on' : 'Schedule off');
  title.appendChild(name);
  title.appendChild(status);
  header.appendChild(title);

  const toggleWrap = document.createElement('label');
  toggleWrap.className = 'toggle-compact';
  toggleWrap.title = 'Enable schedule';
  const toggleInput = document.createElement('input');
  toggleInput.type = 'checkbox';
  toggleInput.className = 'schedule-enabled';
  toggleInput.checked = Boolean(sched.enabled);
  toggleInput.setAttribute('aria-label', 'Enable schedule for ' + acc.label);
  const togglePill = document.createElement('span');
  togglePill.className = 'toggle-pill';
  toggleWrap.appendChild(toggleInput);
  toggleWrap.appendChild(togglePill);
  header.appendChild(toggleWrap);

  card.appendChild(header);

  // Body: 3-column form
  const body = document.createElement('div');
  body.className = 'schedule-card-body';

  const grid = document.createElement('div');
  grid.className = 'form-grid-3';

  grid.appendChild(make_form_field('Start time', 'time', 'schedule-time', sched.time || '09:00'));
  grid.appendChild(make_form_field('Queries',    'number', 'schedule-queries', sched.queries != null ? sched.queries : 30, { min: 1, max: 99 }));
  grid.appendChild(make_form_field('Window (h)', 'number', 'schedule-window', sched.window_hours != null ? sched.window_hours : 1, { min: 0, max: 12 }));

  body.appendChild(grid);
  card.appendChild(body);

  // Toggle wires disabled state on body.
  toggleInput.addEventListener('change', () => {
    card.classList.toggle('disabled', !toggleInput.checked);
    status.textContent =
      (item.first_setup_done ? '' : 'Setup pending · ') +
      (toggleInput.checked ? 'Schedule on' : 'Schedule off');
  });

  return card;
}

function make_form_field(labelText, inputType, className, value, opts) {
  const wrap = document.createElement('div');
  wrap.className = 'form-field';

  const label = document.createElement('label');
  label.textContent = labelText;
  wrap.appendChild(label);

  const input = document.createElement('input');
  input.type = inputType;
  input.className = className;
  input.value = value;
  if (opts) {
    if (opts.min !== undefined) input.min = opts.min;
    if (opts.max !== undefined) input.max = opts.max;
  }
  wrap.appendChild(input);

  return wrap;
}

async function save_settings() {
  const cards = Array.from(document.querySelectorAll('#schedule_accounts_list .schedule-card'));
  const startupWanted = document.getElementById('startupToggle').checked;

  // Validate + collect payloads per account.
  const payloads = [];
  for (const card of cards) {
    const id = card.dataset.id;
    const enabled = card.querySelector('.schedule-enabled').checked;
    const time = card.querySelector('.schedule-time').value || '09:00';
    const queries = parseInt(card.querySelector('.schedule-queries').value, 10);
    const windowHours = parseInt(card.querySelector('.schedule-window').value, 10);

    if (enabled) {
      if (!/^\d{2}:\d{2}$/.test(time)) {
        show_toast('Enter a valid start time (HH:MM) for all enabled schedules.', 'warning');
        return;
      }
      if (isNaN(queries) || queries < 1 || queries > 99) {
        show_toast('Queries must be between 1 and 99 (all enabled schedules).', 'warning');
        return;
      }
      if (isNaN(windowHours) || windowHours < 0 || windowHours > 12) {
        show_toast('Window must be between 0 and 12 hours.', 'warning');
        return;
      }
    }

    payloads.push({
      id: id,
      payload: {
        enabled: enabled,
        time: time,
        queries: isNaN(queries) ? 30 : queries,
        window_hours: isNaN(windowHours) ? 1 : windowHours,
      },
    });
  }

  try {
    const scheduleCalls = payloads.map(p =>
      pywebview.api.set_schedule(p.id, p.payload)
    );

    const startupInfo = await pywebview.api.get_launch_on_startup();
    let startupCall = Promise.resolve(true);
    if (startupInfo && startupInfo.supported && startupInfo.enabled !== startupWanted) {
      startupCall = pywebview.api.set_launch_on_startup(startupWanted);
    }

    const results = await Promise.all([...scheduleCalls, startupCall]);
    const startupOk = results[results.length - 1];
    const scheduleResults = results.slice(0, -1);
    const failures = scheduleResults.filter(ok => !ok).length;

    if (failures > 0) {
      show_toast(`${failures} schedule${failures > 1 ? 's' : ''} failed to save.`, 'error');
      return;
    }
    if (!startupOk && startupInfo && startupInfo.supported) {
      show_toast('Schedules saved, but startup setting failed.', 'warning');
    } else {
      show_toast('Settings saved.', 'success');
    }
    close_settings_modal();
  } catch (err) {
    console.error('save_settings failed:', err);
    show_toast('Save failed.', 'error');
  }
}

// =========================================================================
// Master UI refresh
// =========================================================================

function refresh_account_ui() {
  if (!window.pywebview || !pywebview.api) return;

  pywebview.api.list_accounts().then(accounts => {
    accountsCache = Array.isArray(accounts) ? accounts : [];
    currentAccountId = null;
    for (const acc of accountsCache) {
      if (acc.is_current) { currentAccountId = acc.id; break; }
    }

    render_account_trigger();
    render_account_menu();

    // Empty state overlay.
    const emptyState = document.getElementById('empty_state');
    if (accountsCache.length === 0) {
      emptyState.hidden = false;
    } else {
      emptyState.hidden = true;
    }

    // Start button.
    const startBtn = document.getElementById('start_btn');
    const current = accountsCache.find(a => a.id === currentAccountId);
    const shouldEnable = Boolean(current && current.first_setup_done);
    const label = startBtn.querySelector('.btn-label');
    if (!label || label.textContent === 'Start run' || label.textContent === 'Loading…') {
      startBtn.disabled = !shouldEnable;
      if (label) label.textContent = 'Start run';
    }

    update_status_indicator();

    // Re-render the accounts management modal list if open.
    if (typeof render_accounts_section === 'function') {
      render_accounts_section(accountsCache);
    }
  }).catch(err => {
    console.error('refresh_account_ui failed:', err);
  });
}

// =========================================================================
// Driver warmup loader
// =========================================================================

let loaderInterval;

function start_loader() {
  clearInterval(loaderInterval);

  const tryShowLoader = () => {
    pywebview.api.check_driver_status().then(isLoading => {
      if (isLoading === true && !document.getElementById('inline_loader')) {
        const logDiv = document.getElementById('log_area');
        const loader = document.createElement('div');
        loader.id = 'inline_loader';
        loader.className = 'loader-line';
        loader.innerHTML = '<span class="spinner"></span><span>Preparing the browser driver…</span>';
        logDiv.appendChild(loader);
        logDiv.scrollTop = logDiv.scrollHeight;
      }
      if (isLoading === false) stop_loader();
    }).catch(err => {
      console.error('Failed to check driver status:', err);
      stop_loader();
    });
  };

  tryShowLoader();
  loaderInterval = setInterval(tryShowLoader, 500);
}

function stop_loader() {
  clearInterval(loaderInterval);

  const inline = document.getElementById('inline_loader');
  if (inline) inline.remove();

  const startBtn = document.getElementById('start_btn');
  const current = accountsCache.find(a => a.id === currentAccountId);
  if (startBtn) {
    const label = startBtn.querySelector('.btn-label');
    const txt = label ? label.textContent : startBtn.textContent;
    if (txt === 'Start run' || txt === 'Loading…') {
      startBtn.disabled = !(current && current.first_setup_done);
      if (label) label.textContent = 'Start run';
    }
  }
  update_status_indicator();
}

// =========================================================================
// Boot
// =========================================================================

document.addEventListener('DOMContentLoaded', function() {
  // Hide-browser toggle.
  const toggle = document.getElementById('hideBrowserToggle');
  if (toggle) toggle.addEventListener('change', hideBrowserToggle);

  // Empty-state CTA.
  const cta = document.getElementById('empty_cta');
  if (cta) cta.addEventListener('click', prompt_and_create_account);

  // Account trigger opens the custom dropdown.
  const trigger = document.getElementById('account_trigger');
  if (trigger) {
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle_account_menu();
    });
  }

  // Click outside closes the dropdown.
  document.addEventListener('click', (e) => {
    const picker = document.getElementById('account_picker');
    if (picker && !picker.contains(e.target)) toggle_account_menu(false);
  });

  // Escape closes the dropdown.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') toggle_account_menu(false);
  });

  // Header "manage accounts" button.
  const manageBtn = document.getElementById('manageBtn');
  if (manageBtn) manageBtn.addEventListener('click', open_accounts_modal);

  // Header settings button.
  const settingsBtn = document.getElementById('settingsBtn');
  if (settingsBtn) settingsBtn.addEventListener('click', open_settings_modal);

  // Settings modal close + save.
  const settingsClose = document.getElementById('settingsModalClose');
  if (settingsClose) settingsClose.addEventListener('click', close_settings_modal);
  const settingsCancel = document.getElementById('settingsCancel');
  if (settingsCancel) settingsCancel.addEventListener('click', close_settings_modal);
  const settingsSave = document.getElementById('settingsSave');
  if (settingsSave) settingsSave.addEventListener('click', save_settings);
  const settingsModal = document.getElementById('settings_modal');
  if (settingsModal) {
    settingsModal.addEventListener('click', (e) => {
      if (e.target === settingsModal) close_settings_modal();
    });
  }
  // Accounts modal close.
  const accountsModalClose = document.getElementById('accountsModalClose');
  if (accountsModalClose) accountsModalClose.addEventListener('click', close_accounts_modal);
  const accountsModal = document.getElementById('accounts_modal');
  if (accountsModal) {
    accountsModal.addEventListener('click', (e) => {
      if (e.target === accountsModal) close_accounts_modal();
    });
  }

  // Generic modal wiring.
  const modalConfirm = document.getElementById('modal_confirm');
  const modalCancel = document.getElementById('modal_cancel');
  const modalInput = document.getElementById('modal_input');
  const modalBackdrop = document.getElementById('app_modal');

  if (modalConfirm) {
    modalConfirm.addEventListener('click', () => {
      const input = document.getElementById('modal_input');
      const value = input.hidden ? true : input.value;
      close_modal(value);
    });
  }
  if (modalCancel) modalCancel.addEventListener('click', () => close_modal(null));
  if (modalInput) {
    modalInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); modalConfirm.click(); }
      else if (e.key === 'Escape') modalCancel.click();
    });
  }
  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) close_modal(null);
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modalBackdrop && !modalBackdrop.hidden) close_modal(null);
  });
});

window.addEventListener('pywebviewready', function() {
  pywebview.api.get_settings().then(function(settings) {
    const toggle = document.getElementById('hideBrowserToggle');
    if (toggle) toggle.checked = Boolean(settings.hide_browser);
  });

  refresh_account_ui();
  start_loader();
});
