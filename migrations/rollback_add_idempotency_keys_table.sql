-- Rollback Migration: Drop idempotency_keys table
-- Date: 2026-01-27
-- Description: Rollback script to remove idempotency_keys table

-- Drop indexes first
DROP INDEX IF EXISTS idx_idempotency_keys_key ON idempotency_keys;
DROP INDEX IF EXISTS idx_idempotency_keys_expires_at ON idempotency_keys;
DROP INDEX IF EXISTS idx_idempotency_keys_request_path ON idempotency_keys;

-- Drop the table
DROP TABLE IF EXISTS idempotency_keys;

PRINT 'Idempotency keys table dropped successfully';
