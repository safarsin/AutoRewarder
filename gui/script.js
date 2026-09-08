// =========================================================================
// AutoRewarder — UI script
// =========================================================================

let accountsCache = [];
let currentAccountId = null;
// True while the background WebDriver warmup (which also refreshes the balance)
// is running at launch. Start must stay disabled until it finishes, so a run
// can't open a second driver on the same Edge profile.
let driverWarmingUp = false;
// True while a balance scrape holds a driver (launch refresh, manual refresh,
// or account-switch refresh). Start must stay disabled during it too.
let balanceFetching = false;

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
//
// Security: log messages can contain user-controlled strings (account labels
// entered via the "Add/Rename" modals, Python exception messages, etc.).
// We therefore build the log line node with textContent/createElement only —
// never innerHTML — so a crafted account name like `<img src=x onerror=...>`
// renders as literal text. For the one legitimate case where we need a
// clickable element (update-available notice), see `update_log_link` below,
// which builds the anchor via createElement so the URL is never parsed as
// HTML.
// =========================================================================

function detect_log_severity(msg) {
  const s = String(msg);
  if (/\[ERROR\]/i.test(s)) return 'error';
  if (/\[WARNING\]/i.test(s)) return 'warning';
  if (/completed|success|done!|ready/i.test(s)) return 'success';
  return '';
}

function _new_log_line(message) {
  const severity = detect_log_severity(message);
  const line = document.createElement('div');
  line.className = 'log-line' + (severity ? ' ' + severity : '');

  // Preserve newlines without HTML: split → text nodes separated by <br>.
  const parts = String(message).split('\n');
  for (let i = 0; i < parts.length; i++) {
    if (i > 0) line.appendChild(document.createElement('br'));
    line.appendChild(document.createTextNode(parts[i]));
  }
  return line;
}

function update_log(message) {
  const logDiv = document.getElementById('log_area');
  if (!logDiv) return;

  logDiv.appendChild(_new_log_line(message));
  logDiv.scrollTop = logDiv.scrollHeight;
}

/**
 * Append a log line with a trailing clickable link. Only the `text` portion
 * is user-facing content (still safely inserted as text); the anchor is
 * built via createElement so the URL cannot be interpreted as HTML.
 * Called from Python via evaluate_js when an app update is available.
 */
function update_log_link(text, linkLabel, url) {
  const logDiv = document.getElementById('log_area');
  if (!logDiv) return;

  const line = _new_log_line(text);
  line.appendChild(document.createTextNode(' '));

  const a = document.createElement('a');
  a.href = '#';
  a.textContent = String(linkLabel);
  a.addEventListener('click', function (e) {
    e.preventDefault();
    if (window.pywebview && pywebview.api && typeof pywebview.api.open_link === 'function') {
      pywebview.api.open_link(String(url));
    }
  });
  line.appendChild(a);

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

  const dailyOnly = Boolean(document.getElementById('dailyOnlyToggle')?.checked);

  let pc = 0;
  let mobile = 0;
  if (!dailyOnly) {
    pc = parseInt(document.getElementById('count_pc').value, 10);
    mobile = parseInt(document.getElementById('count_mobile').value, 10);

    const pcValid = !isNaN(pc) && pc >= 0 && pc <= 130;
    const mobileValid = !isNaN(mobile) && mobile >= 0 && mobile <= 99;
    if (!pcValid) {
      show_toast('PC must be between 0 and 130.', 'warning');
      return;
    }
    if (!mobileValid) {
      show_toast('Mobile must be between 0 and 99.', 'warning');
      return;
    }
    if (pc + mobile === 0) {
      show_toast('Set at least one of PC or Mobile above 0.', 'warning');
      return;
    }
  }

  const btn = document.getElementById('start_btn');
  btn.disabled = true;
  const label = btn.querySelector('.btn-label');
  if (label) label.textContent = 'Running…';

  const stopBtn = document.getElementById('stop_btn');
  if (stopBtn) stopBtn.disabled = false;

  // Save the query counts to global settings before running.
  if (!dailyOnly) {
    pywebview.api.set_queries_counts(pc, mobile).then(ok => {
      if (!ok) console.error('Failed to save query counts (backend returned false).');
    }).catch(err => {
      console.error('Failed to save query counts:', err);
    });
  }

  update_status_indicator('executing');
  pywebview.api.main(pc, mobile, dailyOnly);
}

function _sync_daily_only_ui() {
  const toggle = document.getElementById('dailyOnlyToggle');
  const pcField = document.getElementById('count_pc');
  const mobileField = document.getElementById('count_mobile');
  if (!toggle) return;
  const off = toggle.checked;
  if (pcField) pcField.disabled = off;
  if (mobileField) mobileField.disabled = off;
}

document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('dailyOnlyToggle');
  if (toggle) toggle.addEventListener('change', _sync_daily_only_ui);
  _sync_daily_only_ui();

  // Auto-save query counts when they change (on blur).
  const pcField = document.getElementById('count_pc');
  const mobileField = document.getElementById('count_mobile');
  const save_counts = () => {
    if (pcField && mobileField) {
      const pc = parseInt(pcField.value, 10);
      const mobile = parseInt(mobileField.value, 10);
      if (!isNaN(pc) && !isNaN(mobile) && pc >= 0 && pc <= 130 && mobile >= 0 && mobile <= 99) {
        pywebview.api.set_queries_counts(pc, mobile).then(ok => {
          if (!ok) console.error('Failed to auto-save query counts (backend returned false).');
        }).catch(err => {
          console.error('Failed to auto-save query counts:', err);
        });
      }
    }
  };
  if (pcField) pcField.addEventListener('blur', save_counts);
  if (mobileField) mobileField.addEventListener('blur', save_counts);
});

function enable_start_button() {
  const btn = document.getElementById('start_btn');
  const label = btn.querySelector('.btn-label');
  if (label) label.textContent = 'Start run';
  const current = accountsCache.find(a => a.id === currentAccountId);
  btn.disabled = !(current && current.first_setup_done) || driverWarmingUp || balanceFetching;

  // Stop button is meaningful only while a run is in progress.
  const stopBtn = document.getElementById('stop_btn');
  if (stopBtn) {
    stopBtn.disabled = true;
    const stopLabel = stopBtn.querySelector('.stop-label');
    if (stopLabel) stopLabel.textContent = 'Stop';
  }
  update_status_indicator();
}

function stop_bot() {
  if (!window.pywebview || !pywebview.api || !pywebview.api.stop) return;
  const stopBtn = document.getElementById('stop_btn');
  if (stopBtn) {
    stopBtn.disabled = true;
    const stopLabel = stopBtn.querySelector('.stop-label');
    if (stopLabel) stopLabel.textContent = 'Stopping…';
  }
  pywebview.api.stop().catch(err => console.error('stop failed:', err));
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

  set_hide_browser_toggle_enabled(state !== 'executing');

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

function show_stats() {
  if (!window.pywebview || !pywebview.api || !pywebview.api.open_stats_window) return;
  pywebview.api.open_stats_window();
}

/**
 * Format a points number for the compact card: thousands separators, with a
 * leading "~" when the figure is an estimate (no real balance scraped yet).
 */
function _fmt_points(value, isEstimate) {
  if (value == null || isNaN(value)) return '—';
  const sign = value > 0 && isEstimate === 'delta' ? '+' : '';
  const prefix = (isEstimate === true && value > 0) ? '~' : '';
  return prefix + sign + Number(value).toLocaleString();
}

/**
 * Toggle the compact stats card's "searching" animation. Called from Python
 * while it scrapes the real balance (at launch, or on a manual refresh).
 */
function set_stats_loading(on) {
  balanceFetching = Boolean(on);
  const card = document.getElementById('stats_card');
  if (card) card.classList.toggle('stats-loading', balanceFetching);

  // A balance scrape holds a driver on the profile → block Start meanwhile.
  const btn = document.getElementById('start_btn');
  if (!btn) return;
  const label = btn.querySelector('.btn-label');
  const txt = label ? label.textContent : '';
  if (txt === 'Running…') return;  // a run owns the button; leave it alone
  if (balanceFetching) {
    btn.disabled = true;
    if (label) label.textContent = 'Loading…';
  } else {
    const current = accountsCache.find(a => a.id === currentAccountId);
    btn.disabled = !(current && current.first_setup_done) || driverWarmingUp;
    if (label && !driverWarmingUp) label.textContent = 'Start run';
  }
}

/**
 * Refresh the compact stats card for the current account. Called on load,
 * after switching accounts, and (from Python) at the end of every run.
 */
function refresh_stats_ui() {
  if (!window.pywebview || !pywebview.api || !pywebview.api.get_stats) return;
  const totalEl = document.getElementById('stat_total');
  const sessionEl = document.getElementById('stat_session');
  const totalLabel = document.getElementById('stat_total_label');

  pywebview.api.get_stats().then(function (stats) {
    // Drop a response that arrived after the user switched accounts, so stale
    // data can't overwrite the card for the now-active account.
    if (stats && stats.account && stats.account.id !== currentAccountId) return;
    if (!stats || !stats.derived) {
      if (totalEl) totalEl.textContent = '—';
      if (sessionEl) sessionEl.textContent = '—';
      if (totalLabel) totalLabel.textContent = 'Total points';
      return;
    }
    const d = stats.derived;
    if (totalEl) totalEl.textContent = _fmt_points(d.total_points, d.is_estimate);
    if (totalLabel) {
      totalLabel.textContent = d.is_estimate ? 'Total points (est.)' : 'Total points';
    }
    if (sessionEl) {
      // Show the real balance delta as a signed "+N"; estimates get a "~".
      const flag = d.session_is_estimate ? true : 'delta';
      sessionEl.textContent = _fmt_points(d.session_points, flag);
    }
  }).catch(function (err) {
    console.error('refresh_stats_ui failed:', err);
  });
}

function set_hide_browser_toggle_enabled(enabled) {
  const toggle = document.getElementById('hideBrowserToggle');
  if (!toggle) return;
  toggle.disabled = !enabled;
  toggle.setAttribute('aria-disabled', String(!enabled));
  const row = toggle.closest('.toggle-row');
  if (row) row.classList.toggle('row-disabled', !enabled);
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
      '<span>Account settings…</span>';
    manageBtn.addEventListener('click', () => {
      toggle_account_menu(false);
      open_settings_modal(currentAccountId ? account_panel_id(currentAccountId) : 'general');
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
// Settings modal — side navigation, one panel per section / per account
//
// Panel ids: "general", "tasks", "search", "about" (static markup in
// index.html) and "acc:<account_id>" (built here from get_all_schedules()).
// The per-account identity header, setup banner and rename / re-run setup /
// delete actions live in settings.js.
// =========================================================================

// Panel ids with unsaved edits. Drives the nav markers, the footer summary
// and the "Discard changes?" prompt on close.
const settingsDirty = new Set();
let settingsActivePanel = 'general';
// False while the modal is loading (or after a failed load): Save is
// disabled and save_settings() refuses to run, so stale or default field
// values can never be persisted.
let settingsLoaded = false;
let aboutRepoUrl = 'https://github.com/safarsin/AutoRewarder';

function account_panel_id(accountId) {
  return 'acc:' + accountId;
}

function settings_panels() {
  return Array.from(document.querySelectorAll('#settings_pane_body .settings-panel'));
}

function settings_nav_items() {
  return Array.from(document.querySelectorAll('#settings_nav .settings-nav-item'));
}

function settings_is_open() {
  const backdrop = document.getElementById('settings_modal');
  return Boolean(backdrop && !backdrop.hidden);
}

// Show one panel, highlight its nav entry and update the pane header. Falls
// back to General when the requested panel no longer exists (deleted account).
function settings_go(panelId) {
  const panels = settings_panels();
  let target = panels.find(p => p.dataset.panel === panelId);
  if (!target) {
    target = panels.find(p => p.dataset.panel === 'general');
    if (!target) return;
    panelId = 'general';
  }
  settingsActivePanel = panelId;

  panels.forEach(p => p.classList.toggle('active', p === target));
  settings_nav_items().forEach(btn => {
    btn.classList.toggle('active', btn.dataset.panel === panelId);
  });

  const title = document.getElementById('settings_pane_title');
  const desc = document.getElementById('settings_pane_desc');
  if (title) title.textContent = target.dataset.title || '';
  if (desc) desc.textContent = target.dataset.desc || '';

  const body = document.getElementById('settings_pane_body');
  if (body) body.scrollTop = 0;
}

function settings_mark_dirty(panelId) {
  if (!panelId) return;
  settingsDirty.add(panelId);
  settings_refresh_dirty();
}

function settings_clear_dirty() {
  settingsDirty.clear();
  settings_refresh_dirty();
}

function settings_refresh_dirty() {
  settings_nav_items().forEach(btn => {
    btn.dataset.dirty = settingsDirty.has(btn.dataset.panel) ? '1' : '0';
  });
  const summary = document.getElementById('settings_dirty');
  if (!summary) return;
  const n = settingsDirty.size;
  summary.textContent =
    n === 0 ? 'No changes' : (n === 1 ? '1 section changed' : `${n} sections changed`);
  summary.classList.toggle('has-changes', n > 0);
}

/**
 * Open the Settings modal. `panelId` selects the section to land on
 * (e.g. account_panel_id(id) from the account dropdown); anything else —
 * including the click Event passed by a plain listener — opens General.
 */
function open_settings_modal(panelId) {
  const backdrop = document.getElementById('settings_modal');
  if (!backdrop) return;
  const initialPanel = typeof panelId === 'string' ? panelId : 'general';

  // Static panels can be shown right away; account panels exist only after
  // the schedules have loaded, so settings_go() runs again below.
  settings_clear_dirty();
  settings_go(initialPanel.startsWith('acc:') ? 'general' : initialPanel);

  // Nothing can be saved until every value below has been loaded into the
  // fields; otherwise a click during loading would persist stale or default
  // values.
  settingsLoaded = false;
  const saveBtn = document.getElementById('settingsSave');
  if (saveBtn) saveBtn.disabled = true;

  Promise.all([
    pywebview.api.get_all_schedules(),
    pywebview.api.get_launch_on_startup(),
    pywebview.api.get_close_to_tray(),
    pywebview.api.get_llm_config(),
    pywebview.api.get_force_tasks(),
    pywebview.api.get_app_info(),
  ]).then(([schedules, startup, closeToTray, llmConfig, forceTasks, appInfo]) => {
    render_account_panels(Array.isArray(schedules) ? schedules : []);

    // Background auto-run toggle — disable row on unsupported OS.
    const startupToggle = document.getElementById('startupToggle');
    const startupRow = startupToggle.closest('.settings-row');
    const startupHint = document.getElementById('startup_hint');
    startupToggle.checked = Boolean(startup && startup.enabled);
    if (startup && !startup.supported) {
      startupRow.classList.add('row-disabled');
      startupToggle.disabled = true;
      startupHint.textContent = 'Available on Windows and Linux only.';
    } else {
      startupRow.classList.remove('row-disabled');
      startupToggle.disabled = false;
      startupHint.textContent = "Automatically run AutoRewarder in the background at each account's scheduled time.";
    }

    // Close-to-tray toggle — default to true if the API failed.
    const trayToggle = document.getElementById('closeToTrayToggle');
    if (trayToggle) {
      trayToggle.checked = closeToTray !== false;
    }

    // Force toggles — default to off if the API failed.
    const force = forceTasks || {};
    const forceDailyToggle = document.getElementById('forceDailyToggle');
    const forceVisualToggle = document.getElementById('forceVisualToggle');
    if (forceDailyToggle) forceDailyToggle.checked = Boolean(force.force_daily_tasks);
    if (forceVisualToggle) forceVisualToggle.checked = Boolean(force.force_visual_search);

    // LLM search-term generation.
    const cfg = llmConfig || {};
    const llmToggle = document.getElementById('llmToggle');
    const providerSel = document.getElementById('llmProvider');
    const keyInput = document.getElementById('llmApiKey');
    const localeInput = document.getElementById('llmLocale');
    const localeHint = document.getElementById('llm_locale_hint');
    if (llmToggle) llmToggle.checked = Boolean(cfg.use_llm_queries);
    if (providerSel && cfg.llm_provider) providerSel.value = cfg.llm_provider;
    llmDefaultModels = cfg.default_models || {};
    llm_render_model_options(cfg.llm_model || '');
    llm_update_key_link();
    if (keyInput) {
      keyInput.value = cfg.llm_api_key || '';
      set_api_key_visible(false);
    }
    if (localeInput) localeInput.value = cfg.search_locale || 'auto';
    if (localeHint) {
      const eff = cfg.effective_locale || 'en-US';
      localeHint.textContent =
        `Detected language: ${eff}. Leave "auto" to follow your system, or enter a locale like fr-FR.`;
    }
    apply_llm_field_state();
    // Fill the model picker once per session when the feature is usable;
    // the refresh button re-fetches on demand.
    if (cfg.use_llm_queries && cfg.llm_api_key) {
      if (llmModelCache[llm_provider()]) llm_set_model_hint(llm_loaded_hint(), false);
      else llm_load_models();
    } else {
      llm_set_model_hint(LLM_MODEL_HINT_IDLE, false);
    }

    render_about_panel(appInfo || {});

    // Filling the fields above fired no input/change events (values were set
    // programmatically), so nothing is dirty yet — but clear defensively.
    settings_clear_dirty();
    settings_go(initialPanel);
    settingsLoaded = true;
    if (saveBtn) saveBtn.disabled = false;
  }).catch(err => {
    console.error('Failed to load settings:', err);
    show_toast('Could not load settings.', 'error');
    // The fields hold defaults or stale values: close rather than let the
    // user edit and save them.
    close_settings_modal({ force: true });
  });

  backdrop.hidden = false;
}

/**
 * Close the Settings modal. With unsaved edits, asks for confirmation first
 * unless `opts.force` is true (used right after a successful save). A DOM
 * Event passed by a plain click listener is ignored.
 */
async function close_settings_modal(opts) {
  const backdrop = document.getElementById('settings_modal');
  if (!backdrop || backdrop.hidden) return;

  const force = Boolean(opts && opts.force === true);
  if (!force && settingsDirty.size > 0) {
    const n = settingsDirty.size;
    const discard = await confirm_modal(
      'Discard changes?',
      n === 1
        ? 'One section has unsaved changes. Close without saving?'
        : `${n} sections have unsaved changes. Close without saving?`,
      { confirmLabel: 'Discard' }
    );
    if (!discard) return;
  }

  backdrop.hidden = true;
  settings_clear_dirty();
}

// Dim + disable the LLM config fields when the feature is toggled off.
function apply_llm_field_state() {
  const toggle = document.getElementById('llmToggle');
  const fields = document.getElementById('llm_fields');
  if (!fields) return;
  fields.classList.toggle('dim', !(toggle && toggle.checked));
}

function set_api_key_visible(visible) {
  const key = document.getElementById('llmApiKey');
  const btn = document.getElementById('llmApiKeyToggle');
  if (!key) return;
  key.type = visible ? 'text' : 'password';
  if (btn) {
    const label = visible ? 'Hide API key' : 'Show API key';
    btn.setAttribute('aria-label', label);
    btn.title = label;
  }
}

// -------------------------------------------------------------------------
// Search terms: key portals + model picker
// -------------------------------------------------------------------------

const LLM_PROVIDERS = {
  openai:    { label: 'OpenAI',        keyLabel: 'the OpenAI Platform',   keyUrl: 'https://platform.openai.com/api-keys' },
  anthropic: { label: 'Anthropic',     keyLabel: 'the Anthropic Console', keyUrl: 'https://console.anthropic.com/settings/keys' },
  gemini:    { label: 'Google Gemini', keyLabel: 'Google AI Studio',      keyUrl: 'https://aistudio.google.com/app/apikey' },
};
const LLM_CUSTOM_MODEL = '__custom__';
const LLM_MODEL_HINT_IDLE = 'Load the list to pick a model, or keep the provider default.';

// Models fetched this session, per provider: switching providers back and
// forth refills the picker without another network call.
let llmModelCache = {};
// Provider -> default model id (from get_llm_config); labels the blank choice.
let llmDefaultModels = {};

function llm_provider() {
  const sel = document.getElementById('llmProvider');
  const value = sel ? sel.value : 'openai';
  return LLM_PROVIDERS[value] ? value : 'openai';
}

function llm_update_key_link() {
  const link = document.getElementById('llmKeyLink');
  if (!link) return;
  const info = LLM_PROVIDERS[llm_provider()];
  link.textContent = info.keyLabel;
  link.dataset.url = info.keyUrl;
}

// The model id as it will be saved; '' means the provider default.
function llm_model_value() {
  const sel = document.getElementById('llmModel');
  if (!sel) return '';
  if (sel.value === LLM_CUSTOM_MODEL) {
    const custom = document.getElementById('llmModelCustom');
    return custom ? custom.value.trim() : '';
  }
  return sel.value;
}

function llm_apply_custom_state() {
  const sel = document.getElementById('llmModel');
  const field = document.getElementById('llm_model_custom_field');
  if (!sel || !field) return;
  field.hidden = sel.value !== LLM_CUSTOM_MODEL;
}

/**
 * Rebuild the model picker: provider default, the models loaded for the
 * current provider, the configured id when it is not among them, then
 * "Custom…" for a hand-typed id.
 */
function llm_render_model_options(selectedId) {
  const sel = document.getElementById('llmModel');
  if (!sel) return;
  const provider = llm_provider();
  const wanted = (selectedId || '').trim();
  const loaded = llmModelCache[provider] || [];

  sel.innerHTML = '';
  const add = (value, label, title) => {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = label;
    if (title) o.title = title;
    sel.appendChild(o);
  };
  const def = llmDefaultModels[provider];
  add('', def ? `Default (${def})` : 'Default for provider');
  loaded.forEach(m => add(m.id, m.label || m.id, m.id));
  if (wanted && !loaded.some(m => m.id === wanted)) add(wanted, wanted, wanted);
  add(LLM_CUSTOM_MODEL, 'Custom…');

  sel.value = wanted;
  llm_apply_custom_state();
}

function llm_set_model_hint(text, isWarning) {
  const hint = document.getElementById('llm_model_hint');
  if (!hint) return;
  hint.textContent = text;
  hint.classList.toggle('warning', Boolean(isWarning));
}

function llm_loaded_hint() {
  const n = (llmModelCache[llm_provider()] || []).length;
  return `${n} model${n === 1 ? '' : 's'} available for this key.`;
}

// Ask the provider which models this key can use, then refill the picker.
function llm_load_models() {
  const provider = llm_provider();
  const keyInput = document.getElementById('llmApiKey');
  const key = keyInput ? keyInput.value.trim() : '';
  const btn = document.getElementById('llmModelRefresh');
  if (!key) {
    llm_set_model_hint('Enter an API key to load the model list.', true);
    return;
  }
  if (btn) { btn.disabled = true; btn.classList.add('busy'); }
  llm_set_model_hint(`Loading models from ${LLM_PROVIDERS[provider].label}…`, false);

  const done = () => {
    if (btn) { btn.disabled = false; btn.classList.remove('busy'); }
  };
  pywebview.api.list_llm_models(provider, key).then(result => {
    const r = result || {};
    if (r.ok && Array.isArray(r.models)) {
      llmModelCache[provider] = r.models;
      // Only touch the picker if the user is still on that provider.
      if (llm_provider() === provider) {
        llm_render_model_options(llm_model_value());
        llm_set_model_hint(llm_loaded_hint(), false);
      }
    } else if (llm_provider() === provider) {
      llm_set_model_hint(r.error || 'Could not load the model list.', true);
    }
    done();
  }).catch(err => {
    console.error('list_llm_models failed:', err);
    if (llm_provider() === provider) llm_set_model_hint('Could not load the model list.', true);
    done();
  });
}

function llm_on_provider_change() {
  const provider = llm_provider();
  const current = llm_model_value();
  const loaded = llmModelCache[provider] || [];
  // A model id rarely survives a provider switch: keep it only if the new
  // provider's list knows it, otherwise fall back to that provider's default.
  llm_render_model_options(loaded.some(m => m.id === current) ? current : '');
  llm_update_key_link();
  llm_set_model_hint(loaded.length ? llm_loaded_hint() : LLM_MODEL_HINT_IDLE, false);
}

function llm_on_toggle_change() {
  apply_llm_field_state();
  const toggle = document.getElementById('llmToggle');
  const keyInput = document.getElementById('llmApiKey');
  if (toggle && toggle.checked && keyInput && keyInput.value.trim() && !llmModelCache[llm_provider()]) {
    llm_load_models();
  }
}

// -------------------------------------------------------------------------
// Account panels (one nav entry + one panel per account)
// -------------------------------------------------------------------------

// Merge a get_all_schedules() item with the cached list_accounts() entry so
// the identity header knows whether this is the current account.
function account_view_model(item) {
  const cached = accountsCache.find(a => a.id === item.id);
  return {
    id: item.id,
    label: item.label,
    first_setup_done: Boolean(item.first_setup_done),
    is_current: Boolean(cached && cached.is_current),
  };
}

function make_nav_empty() {
  const el = document.createElement('div');
  el.className = 'settings-nav-empty';
  el.textContent = 'No accounts yet';
  return el;
}

function render_account_panels(schedules) {
  const navWrap = document.getElementById('settings_nav_accounts');
  const panelWrap = document.getElementById('settings_account_panels');
  if (!navWrap || !panelWrap) return;

  navWrap.innerHTML = '';
  panelWrap.innerHTML = '';

  if (!schedules.length) {
    navWrap.appendChild(make_nav_empty());
    return;
  }
  for (const item of schedules) {
    navWrap.appendChild(build_account_nav_item(item));
    panelWrap.appendChild(build_account_panel(item));
  }
}

function build_account_nav_item(item) {
  const acc = account_view_model(item);
  const sched = item.schedule || {};

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'settings-nav-item';
  btn.dataset.panel = account_panel_id(acc.id);
  btn.dataset.id = acc.id;

  btn.appendChild(make_avatar(acc, 'sm'));

  const label = document.createElement('span');
  label.className = 'settings-nav-label';
  label.textContent = acc.label;
  btn.appendChild(label);

  const status = document.createElement('span');
  status.className = 'settings-nav-status';
  btn.appendChild(status);

  update_account_nav_status(btn, acc, Boolean(sched.enabled));
  return btn;
}

// State dot on a nav entry: amber = setup pending, green = schedule on.
function update_account_nav_status(btn, acc, scheduleEnabled) {
  const status = btn.querySelector('.settings-nav-status');
  if (!status) return;
  const pending = !acc.first_setup_done;
  status.classList.toggle('pending', pending);
  status.classList.toggle('on', !pending && scheduleEnabled);
  status.title = pending ? 'Setup pending' : (scheduleEnabled ? 'Schedule on' : 'Schedule off');
}

function format_schedule_summary(item, sched, enabled) {
  const prefix = item.first_setup_done ? '' : 'Setup pending · ';
  if (!enabled) return prefix + 'Schedule off';
  const pc = sched.queries_pc != null ? sched.queries_pc : 30;
  const mobile = sched.queries_mobile != null ? sched.queries_mobile : 20;
  const time = (sched.run_time && /^\d{2}:\d{2}$/.test(sched.run_time)) ? sched.run_time : '09:00';
  if (sched.advancedScheduling) {
    const dur = sched.runDuration != null ? sched.runDuration : 3;
    const qph = sched.queriesPerHour != null ? sched.queriesPerHour : 10;
    return `${prefix}${time} · PC ${pc} / Mobile ${mobile} · ${dur}h @ ${qph}/h`;
  }
  return `${prefix}${time} · PC ${pc} / Mobile ${mobile}`;
}

/**
 * Build the full panel for one account: identity header (+ setup banner),
 * the Rewards dashboard choice, then the schedule. Field class names are
 * what save_settings() reads back.
 */
function build_account_panel(item) {
  const acc = account_view_model(item);
  const sched = item.schedule || {};

  const panel = document.createElement('div');
  panel.className = 'settings-panel settings-account-panel';
  panel.dataset.panel = account_panel_id(acc.id);
  panel.dataset.id = acc.id;
  panel.dataset.title = acc.label;
  panel.dataset.desc = 'Identity, Rewards dashboard and scheduled run for this account.';

  panel.appendChild(build_account_identity(acc));
  if (!acc.first_setup_done) panel.appendChild(build_setup_note(acc));

  // --- Microsoft Rewards: which dashboard this account uses. Applies to
  // every run, not just scheduled ones, hence its own group. ---
  const rewards = document.createElement('section');
  rewards.className = 'settings-group';

  const rewardsTitle = document.createElement('div');
  rewardsTitle.className = 'settings-group-title';
  rewardsTitle.textContent = 'Microsoft Rewards';
  rewards.appendChild(rewardsTitle);

  const DASHBOARD_VARIANTS = ['auto', 'legacy', 'new'];
  const dashDefault = DASHBOARD_VARIANTS.includes(item.dashboard_variant)
    ? item.dashboard_variant : 'auto';
  rewards.appendChild(make_select_field('Dashboard', 'schedule-dashboard', dashDefault, [
    { value: 'auto', label: 'Auto (detect)' },
    { value: 'legacy', label: 'Legacy' },
    { value: 'new', label: 'New' },
  ]));

  const rewardsHint = document.createElement('p');
  rewardsHint.className = 'form-hint';
  rewardsHint.textContent =
    'Which Microsoft Rewards page this account uses for the Daily Set. Applies to every run, scheduled or not.';
  rewards.appendChild(rewardsHint);
  panel.appendChild(rewards);

  // --- Scheduled run ---
  const schedGroup = document.createElement('section');
  schedGroup.className = 'settings-group';

  const header = document.createElement('div');
  header.className = 'settings-group-header';

  const schedTitle = document.createElement('div');
  schedTitle.className = 'settings-group-title';
  schedTitle.textContent = 'Scheduled run';

  const summary = document.createElement('span');
  summary.className = 'settings-group-summary';
  summary.textContent = format_schedule_summary(item, sched, Boolean(sched.enabled));

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

  header.appendChild(schedTitle);
  header.appendChild(summary);
  header.appendChild(toggleWrap);
  schedGroup.appendChild(header);

  // Fields dim while the schedule is off (same pattern as the LLM block).
  const fields = document.createElement('div');
  fields.className = 'settings-fields schedule-fields';
  if (!toggleInput.checked) fields.classList.add('dim');

  // Daily fire time + PC/Mobile counts on one row. The time is when the
  // OS-level scheduled task triggers for this account — only effective when
  // Background auto-run is on AND this schedule is enabled.
  const rowMain = document.createElement('div');
  rowMain.className = 'form-grid-3';
  const timeDefault = (sched.run_time && /^\d{2}:\d{2}$/.test(sched.run_time)) ? sched.run_time : '09:00';
  const pcDefault = sched.queries_pc != null ? sched.queries_pc : 30;
  const mobileDefault = sched.queries_mobile != null ? sched.queries_mobile : 20;
  rowMain.appendChild(make_form_field('Daily run time', 'time', 'schedule-run-time', timeDefault, {}));
  rowMain.appendChild(make_form_field('PC queries', 'number', 'schedule-queries-pc', pcDefault, { min: 0, max: 130 }));
  rowMain.appendChild(make_form_field('Mobile queries', 'number', 'schedule-queries-mobile', mobileDefault, { min: 0, max: 99 }));
  fields.appendChild(rowMain);

  // Advanced scheduling sub-toggle row.
  const advRow = document.createElement('label');
  advRow.className = 'sched-adv-row';
  const advInput = document.createElement('input');
  advInput.type = 'checkbox';
  advInput.className = 'schedule-advanced';
  advInput.checked = Boolean(sched.advancedScheduling);
  const advPill = document.createElement('span');
  advPill.className = 'toggle-pill';
  const advLabel = document.createElement('span');
  advLabel.className = 'sched-adv-label';
  advLabel.textContent = 'Advanced scheduling (drip-feed across duration)';
  const advWrap = document.createElement('span');
  advWrap.className = 'toggle-compact';
  advWrap.appendChild(advInput);
  advWrap.appendChild(advPill);
  advRow.appendChild(advWrap);
  advRow.appendChild(advLabel);
  fields.appendChild(advRow);

  // Duration + qph row (only meaningful when advancedScheduling is on).
  const rowAdv = document.createElement('div');
  rowAdv.className = 'form-grid-2 sched-adv-fields';
  const durDefault = sched.runDuration != null ? sched.runDuration : 3;
  const qphDefault = sched.queriesPerHour != null ? sched.queriesPerHour : 10;
  rowAdv.appendChild(make_form_field('Run duration (h)', 'number', 'schedule-run-duration', durDefault, { min: 1, max: 24 }));
  rowAdv.appendChild(make_form_field('Queries / hour', 'number', 'schedule-queries-per-hour', qphDefault, { min: 1, max: 99 }));
  if (!advInput.checked) rowAdv.classList.add('dim');
  fields.appendChild(rowAdv);

  const schedHint = document.createElement('p');
  schedHint.className = 'form-hint';
  schedHint.textContent =
    'Background runs fire at a random minute after this time and need "Background auto-run" (General) to be on. ' +
    'Advanced scheduling also paces manual runs started from the main screen.';
  fields.appendChild(schedHint);

  schedGroup.appendChild(fields);
  panel.appendChild(schedGroup);

  // Live summary + nav dot refresh whenever a field changes.
  const refreshSummary = () => {
    const liveSched = {
      advancedScheduling: advInput.checked,
      queries_pc: parseInt(panel.querySelector('.schedule-queries-pc').value, 10),
      queries_mobile: parseInt(panel.querySelector('.schedule-queries-mobile').value, 10),
      runDuration: parseInt(panel.querySelector('.schedule-run-duration').value, 10),
      queriesPerHour: parseInt(panel.querySelector('.schedule-queries-per-hour').value, 10),
      run_time: panel.querySelector('.schedule-run-time').value,
    };
    summary.textContent = format_schedule_summary(item, liveSched, toggleInput.checked);
  };

  toggleInput.addEventListener('change', () => {
    fields.classList.toggle('dim', !toggleInput.checked);
    const navItem = settings_nav_items().find(b => b.dataset.panel === panel.dataset.panel);
    if (navItem) update_account_nav_status(navItem, acc, toggleInput.checked);
    refreshSummary();
  });
  advInput.addEventListener('change', () => {
    rowAdv.classList.toggle('dim', !advInput.checked);
    refreshSummary();
  });
  fields.querySelectorAll('input[type="number"], input[type="time"]').forEach(f => {
    f.addEventListener('input', refreshSummary);
  });

  return panel;
}

/**
 * Called from refresh_account_ui() whenever the account list changes while
 * Settings is open (rename, delete, create, setup finished, account switch).
 * Reconciles nav entries and panels in place so unsaved schedule edits on
 * untouched accounts survive.
 */
function sync_settings_accounts() {
  if (!settings_is_open()) return;

  pywebview.api.get_all_schedules().then(schedules => {
    const list = Array.isArray(schedules) ? schedules : [];
    const navWrap = document.getElementById('settings_nav_accounts');
    const panelWrap = document.getElementById('settings_account_panels');
    if (!navWrap || !panelWrap) return;

    const known = new Set(list.map(item => item.id));

    // Drop what no longer exists.
    Array.from(panelWrap.children).forEach(panel => {
      if (!known.has(panel.dataset.id)) {
        settingsDirty.delete(panel.dataset.panel);
        panel.remove();
      }
    });
    Array.from(navWrap.children).forEach(el => {
      if (el.classList.contains('settings-nav-empty') || !known.has(el.dataset.id)) el.remove();
    });

    // Add new accounts, refresh the identity of existing ones.
    for (const item of list) {
      const panel = Array.from(panelWrap.children).find(p => p.dataset.id === item.id);
      const navItem = Array.from(navWrap.children).find(b => b.dataset.id === item.id);

      if (!panel || !navItem) {
        if (panel) panel.remove();
        if (navItem) navItem.remove();
        navWrap.appendChild(build_account_nav_item(item));
        panelWrap.appendChild(build_account_panel(item));
        continue;
      }

      const acc = account_view_model(item);
      panel.dataset.title = acc.label;

      const head = panel.querySelector('.settings-account-head');
      if (head) head.replaceWith(build_account_identity(acc));

      const note = panel.querySelector('.settings-setup-note');
      if (acc.first_setup_done && note) note.remove();
      if (!acc.first_setup_done && !note) {
        const newHead = panel.querySelector('.settings-account-head');
        if (newHead) newHead.insertAdjacentElement('afterend', build_setup_note(acc));
      }

      const label = navItem.querySelector('.settings-nav-label');
      if (label) label.textContent = acc.label;
      const avatar = navItem.querySelector('.avatar');
      if (avatar) avatar.replaceWith(make_avatar(acc, 'sm'));
      const enabledInput = panel.querySelector('.schedule-enabled');
      update_account_nav_status(navItem, acc, Boolean(enabledInput && enabledInput.checked));
    }

    if (!list.length) navWrap.appendChild(make_nav_empty());

    settings_refresh_dirty();
    // Re-applies the header (label may have changed) or falls back to
    // General if the active account was just deleted.
    settings_go(settingsActivePanel);
  }).catch(err => {
    console.error('sync_settings_accounts failed:', err);
  });
}

// -------------------------------------------------------------------------
// About panel
// -------------------------------------------------------------------------

function render_about_panel(info) {
  const version = document.getElementById('about_version');
  const dir = document.getElementById('about_app_dir');
  const status = document.getElementById('about_status');
  if (version) version.textContent = 'AutoRewarder ' + (info.version || '');
  if (dir) {
    dir.textContent = info.app_dir || '—';
    dir.title = info.app_dir || '';
  }
  if (status) {
    status.className = 'about-status';
    status.textContent = 'Updates are checked once at launch.';
  }
  if (info.repo_url) aboutRepoUrl = String(info.repo_url);
}

function about_check_updates() {
  const btn = document.getElementById('aboutCheckUpdates');
  const status = document.getElementById('about_status');
  if (!btn || !status) return;

  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Checking…';
  status.className = 'about-status';
  status.textContent = 'Contacting GitHub…';

  const restore = () => {
    btn.disabled = false;
    btn.textContent = originalLabel;
  };

  pywebview.api.check_updates_now().then(result => {
    const r = result || {};
    status.textContent = '';
    if (!r.ok) {
      status.className = 'about-status warning';
      status.textContent = 'Could not reach GitHub. Try again later.';
    } else if (r.update_available) {
      status.className = 'about-status warning';
      status.appendChild(document.createTextNode(`Version ${r.latest} is available. `));
      // Anchor built via createElement so the URL is never parsed as HTML.
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = 'Download';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        pywebview.api.open_link(String(r.url));
      });
      status.appendChild(a);
    } else {
      status.className = 'about-status ok';
      status.textContent = `You're up to date (${r.current}).`;
    }
    restore();
  }).catch(err => {
    console.error('check_updates_now failed:', err);
    status.className = 'about-status warning';
    status.textContent = 'Update check failed.';
    restore();
  });
}

// -------------------------------------------------------------------------
// Form field factories
// -------------------------------------------------------------------------

function make_select_field(labelText, className, value, options) {
  const wrap = document.createElement('div');
  wrap.className = 'form-field';

  const label = document.createElement('label');
  label.textContent = labelText;
  wrap.appendChild(label);

  const select = document.createElement('select');
  select.className = className;
  options.forEach(opt => {
    const o = document.createElement('option');
    o.value = opt.value;
    o.textContent = opt.label;
    if (opt.value === value) o.selected = true;
    select.appendChild(o);
  });
  wrap.appendChild(select);

  return wrap;
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

// -------------------------------------------------------------------------
// Save
// -------------------------------------------------------------------------

async function save_settings() {
  if (!settingsLoaded) {
    show_toast('Settings are still loading.', 'warning');
    return;
  }
  const panels = Array.from(document.querySelectorAll('#settings_account_panels .settings-account-panel'));
  const closeToTrayWanted = document.getElementById('closeToTrayToggle').checked;
  const startupWanted = document.getElementById('startupToggle').checked;

  // Validate + collect payloads per account. On a validation error, jump to
  // the offending account so the toast points at a visible field.
  const payloads = [];
  for (const panel of panels) {
    const id = panel.dataset.id;
    const enabled = panel.querySelector('.schedule-enabled').checked;
    const advancedScheduling = panel.querySelector('.schedule-advanced').checked;
    const pc = parseInt(panel.querySelector('.schedule-queries-pc').value, 10);
    const mobile = parseInt(panel.querySelector('.schedule-queries-mobile').value, 10);
    const runDuration = parseInt(panel.querySelector('.schedule-run-duration').value, 10);
    const queriesPerHour = parseInt(panel.querySelector('.schedule-queries-per-hour').value, 10);
    const runTime = panel.querySelector('.schedule-run-time').value;
    const dashEl = panel.querySelector('.schedule-dashboard');
    const dashboardVariant = dashEl && ['auto', 'legacy', 'new'].includes(dashEl.value)
      ? dashEl.value : 'auto';

    if (enabled) {
      const reject = (message) => {
        settings_go(panel.dataset.panel);
        show_toast(message, 'warning');
      };
      if (isNaN(pc) || pc < 0 || pc > 130) {
        reject('PC queries must be between 0 and 130.');
        return;
      }
      if (isNaN(mobile) || mobile < 0 || mobile > 99) {
        reject('Mobile queries must be between 0 and 99.');
        return;
      }
      if ((pc || 0) + (mobile || 0) === 0) {
        reject('Set at least one of PC or Mobile queries above 0.');
        return;
      }
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(runTime || '')) {
        reject('Daily run time must be a valid HH:MM value.');
        return;
      }
      if (advancedScheduling) {
        if (isNaN(runDuration) || runDuration < 1 || runDuration > 24) {
          reject('Run duration must be between 1 and 24 hours.');
          return;
        }
        if (isNaN(queriesPerHour) || queriesPerHour < 1 || queriesPerHour > 99) {
          reject('Queries per hour must be between 1 and 99.');
          return;
        }
      }
    }

    payloads.push({
      id: id,
      dashboardVariant: dashboardVariant,
      payload: {
        enabled: enabled,
        advancedScheduling: advancedScheduling,
        queries_pc: isNaN(pc) ? 30 : pc,
        queries_mobile: isNaN(mobile) ? 20 : mobile,
        runDuration: isNaN(runDuration) ? 3 : runDuration,
        queriesPerHour: isNaN(queriesPerHour) ? 10 : queriesPerHour,
        run_time: /^([01]\d|2[0-3]):[0-5]\d$/.test(runTime || '') ? runTime : '09:00',
      },
    });
  }

  try {
    // Persist each account's dashboard choice first (independent of the
    // schedule payload; kept out of the results[] slicing below).
    await Promise.all(payloads.map(p =>
      pywebview.api.set_dashboard_variant(p.id, p.dashboardVariant)
    ));

    // Persist the force toggles (independent of the schedule slicing).
    const forceDailyEl = document.getElementById('forceDailyToggle');
    const forceVisualEl = document.getElementById('forceVisualToggle');
    await pywebview.api.set_force_tasks(
      Boolean(forceDailyEl && forceDailyEl.checked),
      Boolean(forceVisualEl && forceVisualEl.checked)
    );

    // Persist LLM search-term config (independent of the schedule slicing).
    const llmToggleEl = document.getElementById('llmToggle');
    await pywebview.api.set_llm_config(
      Boolean(llmToggleEl && llmToggleEl.checked),
      llm_provider(),
      llm_model_value(),
      document.getElementById('llmApiKey').value,
      document.getElementById('llmLocale').value
    );

    const scheduleCalls = payloads.map(p =>
      pywebview.api.set_schedule(p.id, p.payload)
    );

    const startupInfo = await pywebview.api.get_launch_on_startup();
    let startupCall = Promise.resolve(true);
    if (startupInfo && startupInfo.supported && startupInfo.enabled !== startupWanted) {
      startupCall = pywebview.api.set_launch_on_startup(startupWanted);
    }

    // Close-to-tray: persist unconditionally. The backend reads it at next
    // app launch, so saving each time is cheap and avoids a stale state.
    const closeToTrayCall = pywebview.api.set_close_to_tray(closeToTrayWanted);

    const results = await Promise.all([...scheduleCalls, startupCall, closeToTrayCall]);
    const startupOk = results[results.length - 2];
    const scheduleResults = results.slice(0, -2);
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
    settings_clear_dirty();
    close_settings_modal({ force: true });
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
    const busy = driverWarmingUp || balanceFetching;
    const shouldEnable = Boolean(current && current.first_setup_done) && !busy;
    const label = startBtn.querySelector('.btn-label');
    if (!label || label.textContent === 'Start run' || label.textContent === 'Loading…') {
      startBtn.disabled = !shouldEnable;
      if (label) label.textContent = busy ? 'Loading…' : 'Start run';
    }

    update_status_indicator();

    // Stats are per-account — refresh the compact card for the new selection.
    refresh_stats_ui();

    // Keep the Settings modal's account entries in sync if it is open.
    sync_settings_accounts();
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

  // Block Start until the warmup finishes.
  driverWarmingUp = true;
  const startBtn = document.getElementById('start_btn');
  if (startBtn) {
    startBtn.disabled = true;
    const label = startBtn.querySelector('.btn-label');
    if (label && (label.textContent === 'Start run' || label.textContent === 'Loading…')) {
      label.textContent = 'Loading…';
    }
  }

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
  driverWarmingUp = false;

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

  // Header settings button.
  const settingsBtn = document.getElementById('settingsBtn');
  if (settingsBtn) settingsBtn.addEventListener('click', open_settings_modal);

  // Settings navigation (delegated: account entries are built dynamically).
  const settingsNav = document.getElementById('settings_nav');
  if (settingsNav) {
    settingsNav.addEventListener('click', (e) => {
      const item = e.target.closest('.settings-nav-item');
      if (item && item.dataset.panel) settings_go(item.dataset.panel);
    });
  }
  const settingsAddAccount = document.getElementById('settingsAddAccount');
  if (settingsAddAccount) settingsAddAccount.addEventListener('click', prompt_and_create_account);

  // Unsaved-changes tracking: any edit inside a panel marks that panel.
  const settingsBody = document.getElementById('settings_pane_body');
  if (settingsBody) {
    const markFromEvent = (e) => {
      if (!e.target.matches('input, select, textarea')) return;
      const panel = e.target.closest('.settings-panel');
      if (panel) settings_mark_dirty(panel.dataset.panel);
    };
    settingsBody.addEventListener('change', markFromEvent);
    settingsBody.addEventListener('input', markFromEvent);
  }

  // Settings modal leaves only through Save or Cancel (no close cross, no
  // click-outside), so a change is never dropped by accident.
  const settingsCancel = document.getElementById('settingsCancel');
  if (settingsCancel) settingsCancel.addEventListener('click', () => close_settings_modal());
  const settingsSave = document.getElementById('settingsSave');
  if (settingsSave) settingsSave.addEventListener('click', save_settings);
  // Escape behaves like Cancel. Deferred so the generic modal's own Escape
  // handler (registered below) runs first and cannot cancel the
  // "Discard changes?" prompt this may open.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const appModal = document.getElementById('app_modal');
    if (appModal && !appModal.hidden) return;
    if (settings_is_open()) setTimeout(() => close_settings_modal(), 0);
  });

  // LLM feature toggle dims/undims its config fields live (and fills the
  // model picker the first time it is switched on); eye button shows or
  // hides the API key.
  const llmToggle = document.getElementById('llmToggle');
  if (llmToggle) llmToggle.addEventListener('change', llm_on_toggle_change);
  const llmKeyToggle = document.getElementById('llmApiKeyToggle');
  if (llmKeyToggle) {
    llmKeyToggle.addEventListener('click', () => {
      const key = document.getElementById('llmApiKey');
      set_api_key_visible(Boolean(key && key.type === 'password'));
    });
  }

  // Model picker: provider switch refills it, "Custom…" reveals a text
  // field, the refresh button and a freshly pasted key load the list, and
  // the key-portal link opens the provider's page in the browser.
  const llmProviderSel = document.getElementById('llmProvider');
  if (llmProviderSel) llmProviderSel.addEventListener('change', llm_on_provider_change);
  const llmModelSel = document.getElementById('llmModel');
  if (llmModelSel) {
    llmModelSel.addEventListener('change', () => {
      llm_apply_custom_state();
      if (llmModelSel.value === LLM_CUSTOM_MODEL) {
        const custom = document.getElementById('llmModelCustom');
        if (custom) custom.focus();
      }
    });
  }
  const llmRefresh = document.getElementById('llmModelRefresh');
  if (llmRefresh) llmRefresh.addEventListener('click', llm_load_models);
  const llmKeyInput = document.getElementById('llmApiKey');
  if (llmKeyInput) {
    llmKeyInput.addEventListener('change', () => {
      if (llmKeyInput.value.trim()) llm_load_models();
    });
  }
  const llmKeyLink = document.getElementById('llmKeyLink');
  if (llmKeyLink) {
    llmKeyLink.addEventListener('click', (e) => {
      e.preventDefault();
      if (llmKeyLink.dataset.url) pywebview.api.open_link(llmKeyLink.dataset.url);
    });
  }

  // About panel actions.
  const aboutCheck = document.getElementById('aboutCheckUpdates');
  if (aboutCheck) aboutCheck.addEventListener('click', about_check_updates);
  const aboutFolder = document.getElementById('aboutOpenFolder');
  if (aboutFolder) {
    aboutFolder.addEventListener('click', () => {
      pywebview.api.open_data_folder().then(ok => {
        if (!ok) show_toast('Could not open the data folder.', 'error');
      });
    });
  }
  const aboutGithub = document.getElementById('aboutGithub');
  if (aboutGithub) aboutGithub.addEventListener('click', () => pywebview.api.open_link(aboutRepoUrl));

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
  // Report the OS/browser language so LLM query generation can default to it.
  try {
    if (navigator && navigator.language &&
        typeof pywebview.api.set_detected_locale === 'function') {
      pywebview.api.set_detected_locale(navigator.language);
    }
  } catch (e) {
    console.error('Failed to report locale:', e);
  }

  pywebview.api.get_settings().then(function(settings) {
    const toggle = document.getElementById('hideBrowserToggle');
    if (toggle) toggle.checked = Boolean(settings.hide_browser);
  });

  // Load saved query counts from global settings.
  pywebview.api.get_queries_counts().then(function(counts) {
    const pcField = document.getElementById('count_pc');
    const mobileField = document.getElementById('count_mobile');
    if (pcField) pcField.value = counts.queries_pc;
    if (mobileField) mobileField.value = counts.queries_mobile;
  }).catch(err => {
    console.error('Failed to load query counts:', err);
  });

  refresh_account_ui();
  start_loader();
});
