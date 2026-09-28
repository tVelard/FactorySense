(function () {
  const initial = window.__INITIAL__ || { machines: [], activeAlerts: [], sensors: [] };
  const SENSORS = Object.fromEntries(initial.sensors.map((s) => [s.key, s]));
  const STATUS_LABELS = { ok: 'Normal', warning: 'Avertissement', critical: 'Critique' };
  const SEVERITY_LABELS = { warning: 'Avertissement', critical: 'Critique' };

  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();

  const timeFormat = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const formatTime = (iso) => (iso ? timeFormat.format(new Date(iso)) : '');

  function severityRank(s) {
    return { ok: 0, warning: 1, critical: 2 }[s] ?? 0;
  }

  function machineCard(machineId) {
    return document.querySelector(`.machine-card[data-machine-id="${CSS.escape(machineId)}"]`);
  }

  function updateSummary() {
    const cards = [...document.querySelectorAll('.machine-card')];
    for (const status of ['warning', 'critical']) {
      const n = cards.filter((c) => c.dataset.status === status).length;
      const count = document.querySelector(`[data-count="${status}"]`);
      count.textContent = n;
      count.parentElement.toggleAttribute('data-active', n > 0);
      if (status === 'critical') count.nextSibling.textContent = n > 1 ? ' critiques' : ' critique';
    }
  }

  function setMachineStatus(machineId, status) {
    const card = machineCard(machineId);
    if (!card) return;
    card.dataset.status = status;
    const badge = card.querySelector('.status');
    badge.dataset.status = status;
    badge.textContent = STATUS_LABELS[status] || status;
    updateSummary();
  }

  function bumpMachineStatusIfWorse(machineId, severity) {
    const card = machineCard(machineId);
    if (card && severityRank(severity) > severityRank(card.dataset.status)) {
      setMachineStatus(machineId, severity);
    }
  }

  // Alerts ------------------------------------------------------------------

  const list = document.getElementById('alert-list');
  const countEl = document.getElementById('alert-count');
  const emptyEl = document.getElementById('alert-empty');

  function refreshAlertCount() {
    const active = list.querySelectorAll('.alert:not(.acknowledged)').length;
    countEl.textContent = active;
    emptyEl.hidden = list.children.length > 0;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function buildAlert(alert) {
    const sensor = SENSORS[alert.sensor] || { label: alert.sensor, unit: '' };
    const li = el('li', 'alert');
    li.dataset.alertId = alert.id;
    li.dataset.severity = alert.severity;
    li.dataset.key = `${alert.machine_id}|${alert.sensor}`;

    const dot = el('span', 'alert-severity');
    dot.title = SEVERITY_LABELS[alert.severity] || alert.severity;

    const title = el('span', 'alert-title');
    title.append(el('span', 'alert-machine', alert.machine_id), ` · ${sensor.label}`);

    const time = el('time', 'alert-time', formatTime(alert.raised_at));
    if (alert.raised_at) time.dateTime = alert.raised_at;

    const detail = el('span', 'alert-detail');
    detail.append(
      el('strong', null, `${SEVERITY_LABELS[alert.severity] || alert.severity} · ${Number(alert.value).toFixed(2)} ${sensor.unit}`),
      ` · seuil ${alert.threshold} ${sensor.unit}`
    );

    const actions = el('div', 'alert-actions');
    const button = el('button', 'ack-button', 'Acquitter');
    button.type = 'button';
    button.dataset.alertId = alert.id;
    actions.append(button);

    li.append(dot, title, time, detail, actions);
    return li;
  }

  function renderNewAlert(alert) {
    // The backend supersedes the previous active alert for the same machine and sensor.
    list.querySelectorAll('.alert:not(.acknowledged)').forEach((li) => {
      if (li.dataset.key === `${alert.machine_id}|${alert.sensor}`) li.remove();
    });
    list.prepend(buildAlert(alert));
    refreshAlertCount();
    bumpMachineStatusIfWorse(alert.machine_id, alert.severity);
  }

  function markAlertAcknowledged(alert) {
    const li = list.querySelector(`li[data-alert-id="${CSS.escape(String(alert.id))}"]`);
    if (!li) return;
    li.classList.add('acknowledged');
    const actions = li.querySelector('.alert-actions');
    actions.replaceChildren(el('span', 'alert-acked', `Acquittée à ${formatTime(alert.acknowledged_at) || formatTime(new Date().toISOString())}`));
    refreshAlertCount();
  }

  async function acknowledgeAlert(button) {
    const actions = button.parentElement;
    actions.querySelector('.alert-error')?.remove();
    button.disabled = true;
    button.textContent = 'Acquittement…';
    try {
      const res = await fetch(`/api/alerts/${encodeURIComponent(button.dataset.alertId)}/ack`, { method: 'POST' });
      if (!res.ok) throw new Error(res.status);
      markAlertAcknowledged(await res.json());
    } catch (err) {
      button.disabled = false;
      button.textContent = 'Réessayer';
      actions.append(el('span', 'alert-error', "Échec de l'acquittement"));
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('.ack-button');
    if (button && !button.disabled) acknowledgeAlert(button);
  });

  // Live connection ---------------------------------------------------------

  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    const indicator = document.getElementById('connection-status');

    ws.onopen = () => {
      indicator.dataset.state = 'open';
      indicator.textContent = 'Temps réel';
    };
    ws.onclose = () => {
      indicator.dataset.state = 'retry';
      indicator.textContent = 'Reconnexion…';
      setTimeout(connectWebSocket, 2000);
    };
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'alert_new') renderNewAlert(msg.alert);
      if (msg.type === 'alert_ack') markAlertAcknowledged(msg.alert);
    };
  }

  // Charts ------------------------------------------------------------------

  const thresholdLines = {
    id: 'thresholdLines',
    afterDatasetsDraw(chart, _args, opts) {
      const { ctx, chartArea, scales } = chart;
      ctx.save();
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1;
      for (const [value, stroke] of opts.lines) {
        const y = scales.y.getPixelForValue(value);
        if (y < chartArea.top || y > chartArea.bottom) continue;
        ctx.strokeStyle = stroke;
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
      }
      ctx.restore();
    },
  };

  async function loadChart(machineId, sensorKey) {
    const canvas = document.querySelector(
      `canvas[data-chart="${sensorKey}"][data-machine="${CSS.escape(machineId)}"]`
    );
    if (!canvas) return;
    const sensor = SENSORS[sensorKey];
    let points;
    try {
      const res = await fetch(`/api/history?machine_id=${encodeURIComponent(machineId)}&sensor=${sensorKey}&range=1h`);
      if (!res.ok) throw new Error(res.status);
      points = await res.json();
    } catch (err) {
      canvas.parentElement.replaceChildren(el('p', 'machine-foot', 'Historique indisponible'));
      return;
    }
    const values = points.map((p) => p.value);
    const max = Math.max(...values, 0);
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p) => formatTime(p.timestamp)),
        datasets: [{
          data: values,
          borderColor: color('--accent'),
          borderWidth: 1.25,
          pointRadius: 0,
          tension: 0.2,
        }],
      },
      options: {
        animation: false,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            callbacks: { label: (item) => `${item.formattedValue} ${sensor.unit}` },
          },
          thresholdLines: {
            lines: [[sensor.warning, color('--warning')], [sensor.critical, color('--critical')]],
          },
        },
        scales: {
          x: { display: false },
          y: {
            // Keep the warning line in view once readings get close to it.
            suggestedMax: max >= sensor.warning * 0.8 ? sensor.critical * 1.05 : undefined,
            border: { display: false },
            grid: { color: color('--line') },
            ticks: { color: color('--text-3'), font: { size: 10 }, maxTicksLimit: 3 },
          },
        },
      },
      plugins: [thresholdLines],
    });
  }

  // Init --------------------------------------------------------------------

  document.querySelectorAll('time[data-local-time]').forEach((t) => {
    t.textContent = formatTime(t.dateTime);
  });
  initial.activeAlerts.forEach((a) => list.append(buildAlert(a)));
  refreshAlertCount();
  updateSummary();
  initial.machines.forEach((m) => {
    Object.keys(SENSORS).forEach((sensor) => loadChart(m.machine_id, sensor));
  });
  connectWebSocket();
})();
