'use strict';

const express   = require('express');
const http      = require('http');
const { Server} = require('socket.io');
const path      = require('path');

const state          = require('./state');
const apiRouter      = require('./routes/api');
const hardwareRouter = require('./routes/hardware');
const { initRoadCache, getRoadCacheMeta } = require('./roads');

const app    = express();
const server = http.createServer(app);
const io     = new Server(server, { cors: { origin: '*' } });

// Wire io into shared state so routes can broadcast
state.setIo(io);

// ── Middleware ────────────────────────────────────────────────────────────────
app.use(express.json());
app.use(express.static(path.join(__dirname, '../frontend/web/dist')));

// ── REST routes ───────────────────────────────────────────────────────────────
app.use('/api',             apiRouter);
app.use('/api/hardware',    hardwareRouter);

// ── Socket.io ─────────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  const addr = socket.handshake.address;
  console.log(`[socket] + connected  ${socket.id}  (${addr})`);

  // Send full node state immediately on connect
  socket.emit('init', Object.values(state.nodeState));

  // Send current solar flag
  socket.emit('solar:status', { active: state.getSolarActive() });

  socket.on('disconnect', () => {
    console.log(`[socket] - disconnected ${socket.id}`);
  });
});

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3000;

async function start() {
  try {
    await initRoadCache();
    const roads = getRoadCacheMeta();
    console.log(`[roads] cache ready from ${roads.source} (${roads.fetchedAt})`);
  } catch (error) {
    console.error('[roads] initial cache load failed:', error.message);
  }

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`\n  NEO server  →  http://localhost:${PORT}`);
    console.log(`  Simulate    →  http://localhost:${PORT}/api/simulate`);
    console.log(`  Health      →  http://localhost:${PORT}/api/health`);
    console.log(`  Roads       →  http://localhost:${PORT}/api/roads\n`);
  });
}

start().catch((error) => {
  console.error('[server] failed to start:', error);
  process.exit(1);
});
