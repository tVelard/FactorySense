(function () {
  const initial = window.__INITIAL__ || { machines: [], activeAlerts: [] };

  function severityRank(s) {
    return { ok: 0, warning: 1, critical: 2 }[s] ?? 0;
  }

  function setMachineBadge(machineId, status) {
    const card = document.querySelector(`.machine-card[data-machine-id="${machineId}"]`);
    if (!card) return;
    card.className = `machine-card status-${status}`;
    const badge = card.querySelector('.badge');
    badge.className = `badge badge-${status}`;
    badge.textContent = status;
  }

  function bumpMachineStatusIfWorse(machineId, severity) {
    const card = document.querySelector(`.machine-card[data-machine-id="${machineId}"]`);
    if (!card) return;
    const current = card.className.match(/status-(\w+)/)[1];
    if (severityRank(severity) > severityRank(current)) {
      setMachineBadge(machineId, severity);
    }
  }

  function renderNewAlert(alert) {
    const list = document.getElementById('alert-list');
    const li = document.createElement('li');
    li.className = `alert alert-${alert.severity}`;
    li.dataset.alertId = alert.id;
    li.innerHTML = `<strong>${alert.machine_id}</strong> — ${alert.sensor} (${alert.severity}) : ${alert.value}
      <button class="ack-button" data-alert-id="${alert.id}">Acquitter</button>`;
    list.prepend(li);
    bumpMachineStatusIfWorse(alert.machine_id, alert.severity);
  }

  function markAlertAcknowledged(alert) {
    const li = document.querySelector(`li[data-alert-id="${alert.id}"]`);
    if (!li) return;
    li.classList.add('acknowledged');
    const button = li.querySelector('.ack-button');
    if (button) button.remove();
  }

  async function acknowledgeAlert(alertId) {
    await fetch(`/api/alerts/${alertId}/ack`, { method: 'POST' });
  }

  document.addEventListener('click', (event) => {
    if (event.target.classList.contains('ack-button')) {
      acknowledgeAlert(event.target.dataset.alertId);
    }
  });

  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    const pill = document.getElementById('connection-status');

    ws.onopen = () => {
      pill.textContent = 'connecté';
      pill.className = 'status-pill status-pill--ok';
    };
    ws.onclose = () => {
      pill.textContent = 'reconnexion...';
      pill.className = 'status-pill status-pill--warn';
      setTimeout(connectWebSocket, 2000);
    };
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'alert_new') renderNewAlert(msg.alert);
      if (msg.type === 'alert_ack') markAlertAcknowledged(msg.alert);
    };
  }

  async function loadChart(machineId, sensor) {
    const canvas = document.querySelector(`canvas[data-chart="${sensor}"][data-machine="${machineId}"]`);
    if (!canvas) return;
    const res = await fetch(`/api/history?machine_id=${encodeURIComponent(machineId)}&sensor=${sensor}&range=1h`);
    const points = await res.json();
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p.timestamp).toLocaleTimeString()),
        datasets: [{ label: sensor, data: points.map((p) => p.value), borderWidth: 1, pointRadius: 0 }],
      },
      options: { animation: false, scales: { x: { display: false } } },
    });
  }

  initial.machines.forEach((m) => {
    ['vibration', 'temperature', 'pressure'].forEach((sensor) => loadChart(m.machine_id, sensor));
  });

  connectWebSocket();
})();
