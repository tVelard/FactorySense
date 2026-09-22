const express = require('express');
const path = require('path');
const http = require('http');
const WebSocket = require('ws');

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';
const BACKEND_WS_URL = process.env.BACKEND_WS_URL || 'ws://backend:8000/ws/alerts';
const PORT = process.env.PORT || 3000;

const app = express();
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

app.get('/', async (req, res) => {
  try {
    const [machinesRes, alertsRes] = await Promise.all([
      fetch(`${BACKEND_URL}/machines`),
      fetch(`${BACKEND_URL}/alerts?status=active`),
    ]);
    const machines = await machinesRes.json();
    const activeAlerts = await alertsRes.json();
    res.render('dashboard', { machines, activeAlerts });
  } catch (err) {
    console.error('[frontend] failed to load initial state:', err.message);
    res.render('dashboard', { machines: [], activeAlerts: [] });
  }
});

app.get('/api/history', async (req, res) => {
  const { machine_id, sensor, range } = req.query;
  try {
    const params = new URLSearchParams({ machine_id, sensor, range: range || '1h' });
    const backendRes = await fetch(`${BACKEND_URL}/telemetry/history?${params}`);
    res.status(backendRes.status).json(await backendRes.json());
  } catch (err) {
    res.status(502).json({ error: 'backend unreachable' });
  }
});

app.post('/api/alerts/:id/ack', async (req, res) => {
  try {
    const backendRes = await fetch(`${BACKEND_URL}/alerts/${req.params.id}/acknowledge`, {
      method: 'PATCH',
    });
    res.status(backendRes.status).json(await backendRes.json());
  } catch (err) {
    res.status(502).json({ error: 'backend unreachable' });
  }
});

const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/ws' });
const browserClients = new Set();

wss.on('connection', (ws) => {
  browserClients.add(ws);
  ws.on('close', () => browserClients.delete(ws));
  ws.on('error', () => browserClients.delete(ws));
});

function broadcastToBrowsers(message) {
  const payload = JSON.stringify(message);
  for (const ws of browserClients) {
    if (ws.readyState === WebSocket.OPEN) ws.send(payload);
  }
}

function connectUpstream(delay = 1000) {
  const upstream = new WebSocket(BACKEND_WS_URL);
  upstream.on('open', () => console.log('[frontend] connected to backend WS'));
  upstream.on('message', (data) => {
    try {
      broadcastToBrowsers(JSON.parse(data.toString()));
    } catch (err) {
      console.error('[frontend] failed to parse upstream WS message:', err.message);
    }
  });
  upstream.on('close', () => {
    console.log(`[frontend] backend WS closed, retrying in ${delay}ms`);
    setTimeout(() => connectUpstream(Math.min(delay * 2, 30000)), delay);
  });
  upstream.on('error', () => upstream.close());
}
connectUpstream();

server.listen(PORT, () => console.log(`[frontend] listening on ${PORT}`));
