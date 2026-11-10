#!/usr/bin/env node
// stdio <-> websocket bridge for codex-acct (Python's stdlib has no websocket client).
// Usage: node codex-acct-ws.js <ws-url> <token>
// Reads one JSON-RPC message per line from stdin, writes one reply per line to stdout.

if (typeof WebSocket === 'undefined') {
  process.stderr.write(`codex-acct needs Node 22+ (found ${process.version})\n`);
  process.exit(1);
}

const url = process.argv[2];
const token = process.argv[3] || '';

const ws = new WebSocket(url, {
  headers: token ? { Authorization: `Bearer ${token}` } : {},
});

let ready = false;
const queue = [];

ws.onopen = () => {
  ready = true;
  for (const msg of queue) ws.send(msg);
  queue.length = 0;
};

ws.onmessage = (ev) => {
  process.stdout.write(ev.data + '\n');
};

ws.onerror = (e) => {
  process.stderr.write('ws error: ' + (e.message || 'unknown') + '\n');
  process.exit(1);
};

ws.onclose = () => process.exit(0);

let buf = '';
process.stdin.on('data', (chunk) => {
  buf += chunk.toString();
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    if (ready) ws.send(line);
    else queue.push(line);
  }
});

process.stdin.on('end', () => {
  setTimeout(() => process.exit(0), 500);
});
