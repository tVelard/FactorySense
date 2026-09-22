const assert = require('assert');
const WebSocket = require('ws');

const FRONTEND_WS = process.env.FRONTEND_WS || 'ws://localhost:3000/ws';
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

function postTelemetry(payload) {
  return fetch(`${BACKEND_URL}/telemetry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

async function main() {
  const ws = new WebSocket(FRONTEND_WS);
  await new Promise((resolve, reject) => {
    ws.on('open', resolve);
    ws.on('error', reject);
  });

  const messagePromise = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('timed out waiting for alert_new')), 10000);
    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'alert_new') {
        clearTimeout(timeout);
        resolve(msg);
      }
    });
  });

  const machineId = `ws-test-${Date.now()}`;
  const res = await postTelemetry({
    machine_id: machineId,
    timestamp: new Date().toISOString(),
    vibration: 7.0,
    temperature: 45.0,
    pressure: 5.0,
  });
  assert.strictEqual(res.status, 201, 'expected telemetry POST to succeed');

  const msg = await messagePromise;
  assert.strictEqual(msg.alert.machine_id, machineId);
  assert.strictEqual(msg.alert.severity, 'critical');

  const rootRes = await fetch('http://localhost:3000/');
  assert.strictEqual(rootRes.status, 200, 'expected frontend root to return 200');
  const rootBody = await rootRes.text();
  assert.ok(rootBody.includes('machine-card'), 'expected dashboard HTML to contain machine-card');

  const ackRes = await fetch(`http://localhost:3000/api/alerts/${msg.alert.id}/ack`, { method: 'POST' });
  assert.strictEqual(ackRes.status, 200, 'expected ack proxy route to return 200');
  const ackBody = await ackRes.json();
  assert.strictEqual(ackBody.status, 'acknowledged');

  ws.close();
  console.log('OK: frontend relayed alert_new over WebSocket');
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
