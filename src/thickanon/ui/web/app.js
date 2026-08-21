'use strict';

// Python pushes events here from its worker threads (see ui/api.py::_emit).
// Assigned immediately so an event that arrives during start-up is not lost.
window.thickanon = {
  on: function (name, payload) {
    if (name === 'progress') { onProgress(payload); }
    else if (name === 'files') { addFiles(payload && payload.paths); }
  }
};

const $ = (id) => document.getElementById(id);

const state = {
  files: [],
  env: null,
  scanId: null,
  review: [],
  reviewTotal: 0,
  reviewTruncated: false,
  approved: new Set(),
  report: null,
  busy: false,
  startedAt: 0,
  started: false,
  glinerAvailable: true
};

const DETECTION_INPUTS = ['mode', 'deny', 'gliner', 'gliner-labels', 'gliner-threshold', 'gliner-gpu'];

const LOCKED_WHILE_BUSY = [
  'browse-files', 'browse-folder', 'clear-files', 'choose-mapping', 'choose-backup',
  'mode', 'root', 'mapping', 'backup-enabled', 'deny', 'pass', 'pass-confirm',
  'gliner', 'gliner-labels', 'gliner-threshold', 'gliner-gpu', 'download-model'
];

const GLINER_CONTROLS = ['gliner', 'gliner-labels', 'gliner-threshold', 'gliner-gpu', 'download-model'];

const DERIVED_PATH_IDS = ['root', 'mapping', 'backup'];

/* ---------- small helpers ---------- */

function api() {
  return (window.pywebview && window.pywebview.api) || null;
}

function banner(message, kind) {
  const el = $('banner');
  const messages = Array.isArray(message) ? message.filter(Boolean) : (message ? [message] : []);
  if (!messages.length) { el.hidden = true; el.textContent = ''; return; }
  el.textContent = '';
  for (const line of messages) {
    const div = document.createElement('div');
    div.textContent = line;
    el.appendChild(div);
  }
  el.className = 'banner' + (kind === 'info' ? ' info' : '');
  el.hidden = false;
}

function basename(path) {
  const parts = String(path).split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function setBusy(busy) {
  state.busy = busy;
  $('scan').disabled = busy;
  $('deanonymize').disabled = busy;
  for (const id of LOCKED_WHILE_BUSY) { $(id).disabled = busy; }
  // #backup has its own enabled rule, so restore it rather than clobbering it.
  $('backup').disabled = busy || !$('backup-enabled').checked;
  // The neural-NER controls are gated by what this build contains, not by
  // whether a run is in flight. Re-enabling them here would let the user
  // switch on a backend the exe does not ship.
  if (!state.glinerAvailable) {
    for (const id of GLINER_CONTROLS) { $(id).disabled = true; }
  }
  $('cancel').hidden = !busy;
  $('progress').hidden = !busy;
  if (busy) {
    state.startedAt = performance.now();
    setProgress(0, 0, '', '');
  }
}

function setProgress(done, total, path, stage) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  $('progress-bar').style.width = pct + '%';
  const track = $('progress-bar').parentElement;
  track.setAttribute('role', 'progressbar');
  track.setAttribute('aria-valuemin', '0');
  track.setAttribute('aria-valuemax', '100');
  track.setAttribute('aria-valuenow', String(pct));
  const elapsed = Math.round((performance.now() - state.startedAt) / 1000);
  const verb = stage === 'apply' ? 'Writing' : stage === 'deanonymize' ? 'Restoring' : 'Scanning';
  $('progress-label').textContent = total
    ? `${verb} ${done} of ${total} (${pct}%) - ${elapsed}s`
    : `${verb}...`;
  $('progress-file').textContent = path || '';
}

function onProgress(p) {
  setProgress(p.done, p.total, p.path, p.stage);
}

/* ---------- file selection ---------- */

function addFiles(paths) {
  if (!paths || !paths.length) { return; }
  if (state.busy) { return; }
  for (const p of paths) {
    if (p && state.files.indexOf(p) === -1) { state.files.push(p); }
  }
  resetDerivedPaths(false);
  invalidateScan();
  renderFiles();
  applyDefaults();
}

function removeFile(path) {
  if (state.busy) { return; }
  state.files = state.files.filter((p) => p !== path);
  resetDerivedPaths(false);
  invalidateScan();
  renderFiles();
}

function renderFiles() {
  const list = $('files');
  list.textContent = '';
  for (const path of state.files) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = basename(path);
    label.title = path;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '\u00d7';
    remove.setAttribute('aria-label', 'Remove ' + basename(path));
    remove.addEventListener('click', () => removeFile(path));
    li.append(label, remove);
    list.appendChild(li);
  }
  const n = state.files.length;
  $('file-count').textContent = n ? `${n} item${n === 1 ? '' : 's'} selected` : '';
  $('clear-files').hidden = n === 0;
}

function resetDerivedPaths(force) {
  // root, mapping and backup are derived from the selection. Carrying folder
  // A's values into folder B's run is how a second run ends up writing over
  // the first run's key. A value the user typed themselves is kept unless the
  // selection is cleared outright.
  for (const id of DERIVED_PATH_IDS) {
    if (force) { delete $(id).dataset.userEdited; }
    if (force || $(id).dataset.userEdited !== 'true') { $(id).value = ''; }
  }
}

async function applyDefaults() {
  if (!state.files.length || !api()) { return; }
  const res = await api().suggest_defaults(state.files, $('root').value);
  if (!res || !res.ok) { return; }
  if (!$('root').value && res.root) { $('root').value = res.root; }
  if (!$('mapping').value && res.mapping) { $('mapping').value = res.mapping; }
  if (!$('backup').value && res.backup) { $('backup').value = res.backup; }
}

/* ---------- settings ---------- */

function collectOpts() {
  return {
    files: state.files,
    root: $('root').value,
    mapping: $('mapping').value,
    mode: $('mode').value,
    deny: $('deny').value,
    backup_enabled: $('backup-enabled').checked,
    backup: $('backup').value,
    passphrase: $('pass').value,
    gliner: $('gliner').checked,
    gliner_labels: $('gliner-labels').value,
    // '' means "unset"; 0 is a real threshold and must survive.
    gliner_threshold: $('gliner-threshold').value === '' ? null : Number($('gliner-threshold').value),
    gliner_gpu: $('gliner-gpu').checked
  };
}

function persistableSettings() {
  // Only preferences. Selection-derived paths and the passphrase are excluded
  // here as well as by the allowlist in ui/api.py.
  return {
    mode: $('mode').value,
    deny: $('deny').value,
    backup_enabled: $('backup-enabled').checked,
    gliner: $('gliner').checked,
    gliner_labels: $('gliner-labels').value,
    gliner_threshold: $('gliner-threshold').value,
    gliner_gpu: $('gliner-gpu').checked,
    theme: document.documentElement.getAttribute('data-theme') || ''
  };
}

function passphraseProblem() {
  const pass = $('pass').value;
  if (!pass) { return null; }
  if (pass !== $('pass-confirm').value) {
    return 'The passphrase and its confirmation do not match.';
  }
  return null;
}

function invalidateScan() {
  state.scanId = null;
}

/* ---------- scan / apply ---------- */

async function doScan() {
  if (!state.files.length) { banner('Choose some files first.'); return; }
  const problem = passphraseProblem();
  if (problem) { banner(problem); return; }
  banner('');
  $('report').hidden = true;
  setBusy(true);
  try {
    const res = await api().scan(collectOpts());
    if (!res.ok) { banner(res.error); return; }
    state.scanId = res.scan_id;
    state.review = res.review || [];
    state.reviewTotal = res.review_total || 0;
    state.reviewTruncated = !!res.review_truncated;
    state.approved = new Set(state.review.map((c) => c.id));
    if (!$('root').value && res.root) { $('root').value = res.root; }
    const notices = (res.warnings || []).slice();
    if (res.cancelled) {
      // The preview stops at whatever file the cancel landed on, and the files
      // after it were never examined. Offering to write from an incomplete
      // preview would report success over files that still contain PII.
      notices.push(`Scan cancelled after ${res.counts.files} file(s). The preview is incomplete, so nothing will be written. Scan again to anonymize.`);
      banner(notices, 'info');
      return;
    }
    if (notices.length) { banner(notices, 'info'); }
    if (state.reviewTotal === 0 && res.counts.auto === 0) {
      const lines = notices.concat([
        `Nothing to anonymize: no values were detected in ${res.counts.files} file(s). No files were changed.`
      ]);
      const skipped = Object.entries(res.skipped || {});
      if (skipped.length) {
        lines.push(`${skipped.length} file(s) could not be read and were not examined at all:`);
        for (const [path, why] of skipped.slice(0, 20)) { lines.push(`   ${path} - ${why}`); }
        if (skipped.length > 20) { lines.push(`   ...and ${skipped.length - 20} more.`); }
      }
      banner(lines, 'info');
      return;
    }
    if (state.reviewTotal > 0) {
      openReview(res);
    } else {
      await confirmAndApply(res);
    }
  } finally {
    setBusy(false);
  }
}

function summariseScan(scan) {
  const c = scan.counts;
  const parts = [`${c.auto} certain replacement${c.auto === 1 ? '' : 's'} across ${c.files} file${c.files === 1 ? '' : 's'}`];
  if (c.review) { parts.push(`${c.review} need your decision`); }
  if (c.skipped) { parts.push(`${c.skipped} file${c.skipped === 1 ? '' : 's'} skipped`); }
  return parts.join(', ');
}

async function confirmAndApply(scan) {
  const target = $('backup-enabled').checked
    ? 'Originals are backed up first.'
    : 'Originals are overwritten with no backup.';
  const ok = window.confirm(`${summariseScan(scan)}.\n\n${target}\n\nWrite these changes now?`);
  if (!ok) { return; }
  await doApply([]);
}

async function doApply(approvedIds, approveAll) {
  if (!state.scanId) { banner('The preview expired. Scan again.'); return; }
  setBusy(true);
  try {
    const opts = collectOpts();
    opts.approve_all = !!approveAll;
    const res = await api().apply(state.scanId, approvedIds, opts);
    state.scanId = null;
    if (!res.ok) { banner(res.error); return; }
    renderReport(res, 'anonymize');
  } finally {
    setBusy(false);
  }
}

async function doDeanonymize() {
  if (!state.files.length) { banner('Choose some files first.'); return; }
  if (!$('mapping').value) { banner('Choose the mapping file that was saved when these files were anonymized.'); return; }
  banner('');
  $('report').hidden = true;
  setBusy(true);
  try {
    const res = await api().deanonymize(collectOpts());
    if (!res.ok) { banner(res.error); return; }
    renderReport(res, 'deanonymize');
  } finally {
    setBusy(false);
  }
}

/* ---------- review overlay ---------- */

function openReview(scan) {
  $('review-count').textContent =
    `${state.reviewTotal} detection${state.reviewTotal === 1 ? '' : 's'} were not confident enough to replace automatically. Everything ticked will be replaced.`;
  const truncated = $('review-truncated');
  if (state.reviewTruncated) {
    truncated.textContent =
      `Showing the first ${state.review.length} of ${state.reviewTotal}. "Approve all" covers every one of them, but if you untick any row the ${state.reviewTotal - state.review.length} not shown will all be left in place.`;
    truncated.hidden = false;
  } else {
    truncated.hidden = true;
  }
  renderReviewGroups();
  $('review').showModal();
}

function renderReviewGroups() {
  const host = $('review-groups');
  host.textContent = '';
  const groups = new Map();
  for (const c of state.review) {
    if (!groups.has(c.type)) { groups.set(c.type, []); }
    groups.get(c.type).push(c);
  }
  for (const [type, items] of [...groups.entries()].sort()) {
    const section = document.createElement('section');
    section.className = 'review-group';

    const head = document.createElement('header');
    const title = document.createElement('h3');
    title.textContent = `${type} (${items.length})`;
    const approve = document.createElement('button');
    approve.type = 'button';
    approve.className = 'btn ghost small';
    approve.textContent = 'Approve all';
    approve.addEventListener('click', () => setGroup(items, true));
    const reject = document.createElement('button');
    reject.type = 'button';
    reject.className = 'btn ghost small';
    reject.textContent = 'Reject all';
    reject.addEventListener('click', () => setGroup(items, false));
    head.append(title, approve, reject);
    section.appendChild(head);

    for (const c of items) { section.appendChild(reviewRow(c)); }
    host.appendChild(section);
  }
  updateApplyLabel();
}

function reviewRow(candidate) {
  const row = document.createElement('div');
  row.className = 'review-row';

  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = state.approved.has(candidate.id);
  box.dataset.id = candidate.id;
  box.addEventListener('change', () => {
    if (box.checked) { state.approved.add(candidate.id); }
    else { state.approved.delete(candidate.id); }
    updateApplyLabel();
  });

  // Built with createTextNode + <mark>, never innerHTML: the snippet is file
  // content and must never be parsed as markup.
  const snippet = document.createElement('div');
  snippet.className = 'snippet';
  const text = candidate.context;
  snippet.appendChild(document.createTextNode(text.slice(0, candidate.context_start)));
  const mark = document.createElement('mark');
  mark.textContent = text.slice(candidate.context_start, candidate.context_end);
  snippet.appendChild(mark);
  snippet.appendChild(document.createTextNode(text.slice(candidate.context_end)));

  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = `${Math.round(candidate.score * 100)}% - ${basename(candidate.path)}`;
  meta.title = candidate.path;

  row.append(box, snippet, meta);
  return row;
}

function setGroup(items, checked) {
  for (const c of items) {
    if (checked) { state.approved.add(c.id); } else { state.approved.delete(c.id); }
  }
  for (const box of $('review-groups').querySelectorAll('input[type="checkbox"]')) {
    if (items.some((c) => c.id === box.dataset.id)) { box.checked = checked; }
  }
  updateApplyLabel();
}

function updateApplyLabel() {
  const n = state.approved.size;
  $('review-apply').textContent = `Apply (${n} approved)`;
}

/* ---------- report ---------- */

function makeTable(table, headers, rows) {
  table.textContent = '';
  const head = table.createTHead().insertRow();
  for (const h of headers) {
    const th = document.createElement('th');
    th.textContent = h;
    head.appendChild(th);
  }
  const body = table.createTBody();
  for (const cells of rows) {
    const tr = body.insertRow();
    cells.forEach((value, i) => {
      const td = tr.insertCell();
      td.textContent = value;
      td.className = i === 0 ? 'file' : 'num';
    });
  }
}

function renderReport(res, kind) {
  state.report = res.report;
  const headline = $('report-headline');
  headline.textContent = '';

  const add = (value, label) => {
    const box = document.createElement('div');
    const b = document.createElement('b');
    b.textContent = String(value);
    const s = document.createElement('span');
    s.textContent = label;
    box.append(b, s);
    headline.appendChild(box);
  };

  const types = $('report-types');
  types.textContent = '';
  const residual = $('report-residual');

  if (kind === 'anonymize') {
    const r = res.report;
    const applied = Object.values(r.files).reduce((a, f) => a + f.applied_count, 0);
    const left = Object.values(r.files).reduce((a, f) => a + f.flagged_count, 0);
    add(applied, 'values replaced');
    add(Object.keys(r.files).length, 'files written');
    add(left, 'left in place');
    add(Object.keys(r.skipped).length, 'files skipped');

    for (const [type, n] of Object.entries(r.totals).sort()) {
      const li = document.createElement('li');
      li.textContent = `${type}: ${n}`;
      types.appendChild(li);
    }

    const alerts = [];
    if (res.warning) { alerts.push(res.warning); }
    if (res.cancelled) {
      alerts.push('This run was cancelled part way through. Some files were written and some were left untouched - see the table below.');
    }
    if (r.residual_total > 0) {
      alerts.push(`${r.residual_total} value${r.residual_total === 1 ? '' : 's'} matching an email or IP pattern are still present in the written files. Review them before sharing anything.`);
    }
    residual.textContent = '';
    for (const message of alerts) {
      const line = document.createElement('div');
      line.textContent = message;
      residual.appendChild(line);
    }
    residual.hidden = alerts.length === 0;

    makeTable($('report-files'), ['File', 'Replaced', 'Left', 'Residual'],
      Object.entries(r.files).map(([p, f]) => [p, f.applied_count, f.flagged_count, f.residual_count]));

    const extra = [];
    if (res.mapping_path) { extra.push('Mapping saved to: ' + res.mapping_path); }
    if (res.backup_root) { extra.push('Originals backed up to: ' + res.backup_root); }
    banner(extra.join('   |   '), 'info');
  } else {
    const r = res.report;
    add(r.total_restored, 'values restored');
    add(Object.keys(r.files).length, 'files written');
    add(Object.keys(r.skipped).length, 'files skipped');

    const unknown = Object.entries(r.unknown_tokens);
    residual.textContent = '';
    if (unknown.length) {
      const line = document.createElement('div');
      line.textContent = `${unknown.length} token${unknown.length === 1 ? '' : 's'} in these files have no entry in this mapping (${unknown.slice(0, 5).map((u) => u[0]).join(', ')}). This is usually the wrong mapping file.`;
      residual.appendChild(line);
      residual.hidden = false;
    } else {
      residual.hidden = true;
    }

    makeTable($('report-files'), ['File', 'Restored'],
      Object.entries(r.files).map(([p, n]) => [p, n]));
    banner('');
  }

  const skipped = Object.entries(res.report.skipped);
  $('report-skipped-h').hidden = skipped.length === 0;
  $('report-skipped').hidden = skipped.length === 0;
  makeTable($('report-skipped'), ['File', 'Reason'], skipped.map(([p, why]) => [p, why]));

  $('report').hidden = false;
  $('report').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function copyReport() {
  if (!state.report) { return; }
  const text = JSON.stringify(state.report, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    banner('Report copied to the clipboard.', 'info');
  } catch (err) {
    // Clipboard access can be refused in an embedded webview; fall back to a
    // selection the user can copy with the keyboard.
    const area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    banner('Could not reach the clipboard. The report is selected - press Ctrl+C.', 'info');
    setTimeout(() => area.remove(), 15000);
  }
}

async function saveReport() {
  if (!state.report || !api()) { return; }
  const res = await api().save_report(state.report, 'thickanon-report.json');
  if (!res.ok) { banner(res.error); return; }
  if (res.path) { banner('Report saved to: ' + res.path, 'info'); }
}

/* ---------- theme ---------- */

function applyTheme(theme) {
  if (theme) { document.documentElement.setAttribute('data-theme', theme); }
  else { document.documentElement.removeAttribute('data-theme'); }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const next = current ? (current === 'dark' ? 'light' : '') : (dark ? 'light' : 'dark');
  applyTheme(next);
  saveSettings();
}

async function saveSettings() {
  if (api()) { await api().save_settings(persistableSettings()); }
}

/* ---------- start-up ---------- */

function bind() {
  $('browse-files').addEventListener('click', () => browse('files'));
  $('browse-folder').addEventListener('click', () => browse('folder'));
  $('clear-files').addEventListener('click', () => {
    state.files = [];
    resetDerivedPaths(true);
    invalidateScan();
    renderFiles();
  });
  $('choose-mapping').addEventListener('click', chooseMapping);
  $('choose-backup').addEventListener('click', chooseBackup);
  $('scan').addEventListener('click', doScan);
  $('deanonymize').addEventListener('click', doDeanonymize);
  $('cancel').addEventListener('click', () => api() && api().cancel());
  $('download-model').addEventListener('click', downloadModel);
  $('theme-toggle').addEventListener('click', toggleTheme);
  $('report-copy').addEventListener('click', copyReport);
  $('report-save').addEventListener('click', saveReport);

  $('pass').addEventListener('input', () => {
    $('pass-confirm-row').hidden = $('pass').value === '';
  });
  $('backup-enabled').addEventListener('change', () => {
    $('backup').disabled = !$('backup-enabled').checked;
    saveSettings();
  });
  for (const id of DETECTION_INPUTS) {
    $(id).addEventListener('change', () => { invalidateScan(); saveSettings(); });
  }
  $('deny').addEventListener('input', invalidateScan);

  for (const id of DERIVED_PATH_IDS) {
    $(id).addEventListener('input', () => { $(id).dataset.userEdited = 'true'; });
  }

  $('review-approve-all').addEventListener('click', () => setGroup(state.review, true));
  $('review-reject-all').addEventListener('click', () => setGroup(state.review, false));
  $('review-cancel').addEventListener('click', () => {
    $('review').close();
    banner('Review cancelled. Nothing was written. Scan again when you are ready.', 'info');
  });
  $('review-apply').addEventListener('click', async () => {
    const approveAll = state.reviewTruncated && state.approved.size === state.review.length;
    if (state.reviewTruncated && !approveAll) {
      const unseen = state.reviewTotal - state.review.length;
      const ok = window.confirm(
        `${unseen} detection(s) beyond the ${state.review.length} shown were never displayed.\n\n` +
        'Because you changed the selection, all of them will be LEFT IN PLACE and will still ' +
        'appear in the written files.\n\nContinue anyway?');
      if (!ok) { return; }
    }
    $('review').close();
    await doApply([...state.approved], approveAll);
  });

  // Visual feedback only. The drop itself is handled in Python, which is the
  // only place a real filesystem path is available.
  const drop = $('drop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragenter', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', () => drop.classList.remove('over'));

  // A file dropped anywhere except the drop zone would otherwise make the
  // WebView navigate to that file, replacing the app with no way back and no
  // address bar. The drop-zone handler stops propagation, so this only ever
  // sees strays.
  for (const type of ['dragover', 'drop']) {
    document.addEventListener(type, (e) => { e.preventDefault(); });
  }
}

async function browse(kind) {
  if (!api()) { return; }
  const res = kind === 'folder' ? await api().pick_folder() : await api().pick_files();
  if (res && res.ok && res.paths) { addFiles(res.paths); }
}

async function chooseMapping() {
  if (!api()) { return; }
  const suggested = $('mapping').value ? basename($('mapping').value) : 'thickanon-mapping.json';
  const res = await api().pick_mapping(suggested);
  if (res && res.ok && res.path) { $('mapping').value = res.path; }
}

async function chooseBackup() {
  if (!api()) { return; }
  const res = await api().pick_backup();
  if (res && res.ok && res.paths && res.paths.length) { $('backup').value = res.paths[0]; }
}

async function downloadModel() {
  if (!api()) { return; }
  banner('Downloading the GLiNER model. This can take several minutes.', 'info');
  const res = await api().download_model();
  banner(res.ok ? 'GLiNER model is ready.' : res.error, res.ok ? 'info' : '');
}

async function start() {
  state.started = true;
  banner('');
  bind();
  renderFiles();
  if (!api()) {
    banner('The Python bridge is not available. Start the app with the thickAnonymizer executable.');
    return;
  }
  const env = await api().environment();
  state.env = env;
  $('version').textContent = 'v' + env.version;

  const advanced = $('advanced');
  state.glinerAvailable = !!env.gliner.available;
  if (!state.glinerAvailable) {
    advanced.dataset.unavailable = 'true';
    $('gliner-note').textContent = env.gliner.reason;
    for (const id of GLINER_CONTROLS) { $(id).disabled = true; }
  } else {
    $('gliner-note').textContent = 'Slower and heavier than the default detector, but catches more names and organisations.';
  }

  const saved = await api().load_settings();
  const s = (saved && saved.settings) || {};
  if (s.mode) { $('mode').value = s.mode; }
  if (s.deny) { $('deny').value = s.deny; }
  if (s.backup_enabled === false) { $('backup-enabled').checked = false; $('backup').disabled = true; }
  if (s.gliner && env.gliner.available) { $('gliner').checked = true; }
  if (s.gliner_labels) { $('gliner-labels').value = s.gliner_labels; }
  if (s.gliner_threshold !== undefined && s.gliner_threshold !== null) {
    $('gliner-threshold').value = s.gliner_threshold;
  }
  if (s.gliner_gpu) { $('gliner-gpu').checked = true; }
  applyTheme(s.theme || '');
}

if (window.pywebview) {
  start();
} else {
  window.addEventListener('pywebviewready', start);
  // pywebview injects its bridge after this script runs, so the listener above
  // is the normal path. If it never fires the page is inert, and saying so is
  // better than leaving every control silently dead.
  setTimeout(() => {
    if (!state.started) {
      banner('This page is not running inside the thickAnonymizer app, so nothing on it will work. Launch thickAnonymizer.exe instead.');
    }
  }, 3000);
}
