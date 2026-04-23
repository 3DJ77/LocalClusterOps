#!/usr/bin/env node

process.env.MONGOMS_DISTRO = process.env.MONGOMS_DISTRO || 'ubuntu-22.04';

const { MongoMemoryServer } = require('mongodb-memory-server');
const fs = require('fs');
const path = require('path');

const port = Number.parseInt(process.env.BCC_MONGO_PORT || '27017', 10);
const dbName = process.env.BCC_MONGO_DB || 'LibreChat';
const version = process.env.BCC_MONGO_VERSION || '7.0.14';
const dbPath =
  process.env.BCC_MONGO_DB_PATH || path.resolve(__dirname, '..', '.bcc-runtime', 'mongo-data');

let server;

async function main() {
  fs.mkdirSync(dbPath, { recursive: true });

  server = await MongoMemoryServer.create({
    binary: {
      version,
    },
    instance: {
      port,
      portGeneration: false,
      dbName,
      ip: '127.0.0.1',
      dbPath,
      storageEngine: 'wiredTiger',
    },
  });

  console.log(`[bcc] MongoDB memory server ready: ${server.getUri()}`);
  console.log(`[bcc] MongoDB dbPath: ${dbPath}`);
  console.log('[bcc] Keep this process running while using LibreChat.');
}

async function shutdown(signal) {
  console.log(`[bcc] ${signal} received, stopping MongoDB memory server...`);
  if (server) {
    await server.stop();
  }
  process.exit(0);
}

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));

main().catch((error) => {
  console.error('[bcc] Failed to start MongoDB memory server:', error);
  process.exit(1);
});
