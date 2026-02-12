import Database from 'better-sqlite3'
import path from 'path'
import os from 'os'
import fs from 'fs'

const DB_PATH = process.env.DB_PATH || path.join(os.homedir(), 'space', 'spacebrr.db')
const DB_DIR = path.dirname(DB_PATH)

if (!fs.existsSync(DB_DIR)) {
  fs.mkdirSync(DB_DIR, { recursive: true })
}

const db = new Database(DB_PATH)
db.pragma('journal_mode = WAL')

db.exec(`
  CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    github_user TEXT NOT NULL,
    customer_id TEXT,
    subscription_status TEXT,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
  );

  CREATE INDEX IF NOT EXISTS idx_sessions_customer_id ON sessions(customer_id);
  CREATE INDEX IF NOT EXISTS idx_sessions_github_user ON sessions(github_user);
`)

export interface Session {
  id: string
  token: string
  githubUser: string
  customerId?: string
  subscriptionStatus?: string
}

export function createSession(id: string, token: string, githubUser: string): void {
  db.prepare(`
    INSERT INTO sessions (id, token, github_user) VALUES (?, ?, ?)
  `).run(id, token, githubUser)
}

export function getSession(id: string): Session | null {
  const row = db.prepare(`
    SELECT id, token, github_user, customer_id, subscription_status
    FROM sessions WHERE id = ?
  `).get(id) as any
  
  if (!row) return null
  
  return {
    id: row.id,
    token: row.token,
    githubUser: row.github_user,
    customerId: row.customer_id,
    subscriptionStatus: row.subscription_status,
  }
}

export function updateSession(id: string, updates: { customerId?: string, subscriptionStatus?: string }): void {
  const fields: string[] = []
  const values: any[] = []
  
  if (updates.customerId !== undefined) {
    fields.push('customer_id = ?')
    values.push(updates.customerId)
  }
  
  if (updates.subscriptionStatus !== undefined) {
    fields.push('subscription_status = ?')
    values.push(updates.subscriptionStatus)
  }
  
  if (fields.length === 0) return
  
  fields.push('updated_at = unixepoch()')
  values.push(id)
  
  db.prepare(`
    UPDATE sessions SET ${fields.join(', ')} WHERE id = ?
  `).run(...values)
}

export function findSessionsByCustomerId(customerId: string): Session[] {
  const rows = db.prepare(`
    SELECT id, token, github_user, customer_id, subscription_status
    FROM sessions WHERE customer_id = ?
  `).all(customerId) as any[]
  
  return rows.map(row => ({
    id: row.id,
    token: row.token,
    githubUser: row.github_user,
    customerId: row.customer_id,
    subscriptionStatus: row.subscription_status,
  }))
}

export function cleanupOldSessions(olderThanDays: number = 30): number {
  const threshold = Math.floor(Date.now() / 1000) - (olderThanDays * 86400)
  const result = db.prepare(`
    DELETE FROM sessions WHERE created_at < ?
  `).run(threshold)
  
  return result.changes
}
