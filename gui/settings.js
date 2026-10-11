// =========================================================================
// Settings › Accounts — per-account panel helpers: identity header, setup
// banner and the rename / re-run setup / delete actions. The panels
// themselves are assembled in script.js (build_account_panel), where the
// generic toast / modal / avatar helpers also live.
// =========================================================================

const ACCOUNT_ICONS = {
  rename: '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
  setup:  '<svg viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15A9 9 0 1 1 18 5.3L23 10"/></svg>',
  trash:  '<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>',
};

/**
 * Header of an account panel: large avatar, label, state line and the
 * action buttons. `acc` = {id, label, first_setup_done, is_current}.
 */
function build_account_identity(acc) {
  const head = document.createElement('div');
  head.className = 'settings-account-head';

  head.appendChild(make_avatar(acc, 'lg'));

  const text = document.createElement('div');
  text.className = 'settings-account-text';

  const name = document.createElement('div');
  name.className = 'settings-account-name';
  name.textContent = acc.label;

  const meta = document.createElement('div');
  meta.className = 'settings-account-meta';
  const state = document.createElement('span');
  state.className = acc.first_setup_done ? 'ok' : 'pending';
  state.textContent = acc.first_setup_done ? 'Ready' : 'Setup pending';
  meta.appendChild(state);
  if (acc.is_current) meta.appendChild(document.createTextNode(' · Current account'));

  text.appendChild(name);
  text.appendChild(meta);
  head.appendChild(text);

  head.appendChild(build_account_actions(acc));
  return head;
}

function build_account_actions(acc) {
  const actions = document.createElement('div');
  actions.className = 'account-actions';

  const resetupBtn = document.createElement('button');
  resetupBtn.type = 'button';
  resetupBtn.className = 'icon-btn';
  resetupBtn.title = acc.first_setup_done ? 'Re-run setup' : 'Run setup';
  resetupBtn.setAttribute('aria-label', resetupBtn.title);
  resetupBtn.innerHTML = ACCOUNT_ICONS.setup;
  resetupBtn.addEventListener('click', () => run_account_setup(acc));

  const renameBtn = document.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'icon-btn';
  renameBtn.title = 'Rename';
  renameBtn.setAttribute('aria-label', 'Rename');
  renameBtn.innerHTML = ACCOUNT_ICONS.rename;
  renameBtn.addEventListener('click', async () => {
    const newLabel = await prompt_modal(
      'Rename account',
      `Enter a new name for "${acc.label}".`,
      acc.label,
      { confirmLabel: 'Rename' }
    );
    if (newLabel === null) return;
    const trimmed = String(newLabel).trim();
    if (!trimmed) return;
    pywebview.api.rename_account(acc.id, trimmed).then(ok => {
      if (!ok) show_toast('Rename failed.', 'error');
      else show_toast(`Renamed to "${trimmed}".`, 'success');
    });
  });

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'icon-btn danger';
  deleteBtn.title = 'Delete';
  deleteBtn.setAttribute('aria-label', 'Delete');
  deleteBtn.innerHTML = ACCOUNT_ICONS.trash;
  deleteBtn.addEventListener('click', async () => {
    const confirmed = await confirm_modal(
      `Delete "${acc.label}"?`,
      'This removes its browser profile, history, and daily-set status. This cannot be undone.',
      { confirmLabel: 'Delete', danger: true }
    );
    if (!confirmed) return;
    pywebview.api.delete_account(acc.id).then(success => {
      if (!success) show_toast('Delete failed.', 'error');
      else show_toast(`"${acc.label}" deleted.`, 'success');
    });
  });

  actions.appendChild(resetupBtn);
  actions.appendChild(renameBtn);
  actions.appendChild(deleteBtn);
  return actions;
}

/** Banner shown on an account whose first setup has not been completed. */
function build_setup_note(acc) {
  const note = document.createElement('div');
  note.className = 'settings-setup-note';

  const text = document.createElement('p');
  const strong = document.createElement('b');
  strong.textContent = "This account isn't set up yet.";
  text.appendChild(strong);
  text.appendChild(document.createTextNode(' Sign in once in the browser so runs can start.'));

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-primary small';
  btn.textContent = 'Run setup';
  btn.addEventListener('click', () => run_account_setup(acc));

  note.appendChild(text);
  note.appendChild(btn);
  return note;
}

// Opens the browser for First Setup; the promise resolves once setup ends.
function run_account_setup(acc) {
  show_toast(`Opening browser to set up "${acc.label}"…`, 'info', { duration: 6000 });
  pywebview.api.rerun_setup(acc.id).then(ok => {
    if (!ok) show_toast('Setup was not completed.', 'error');
  });
}
