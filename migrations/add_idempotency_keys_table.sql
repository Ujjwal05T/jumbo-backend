-- Migration: Add idempotency_keys table
-- Date: 2026-01-27
-- Description: Creates idempotency_keys table to prevent duplicate plan creation from network retries

-- Create idempotency_keys table
CREATE TABLE idempotency_keys (
    id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    [key] VARCHAR(255) NOT NULL UNIQUE,
    request_path VARCHAR(500) NOT NULL,
    request_body_hash VARCHAR(64) NULL,
    response_body NVARCHAR(MAX) NULL,
    response_status INT NULL,
    created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
    expires_at DATETIME NOT NULL
);

-- Create indexes for faster lookups
CREATE UNIQUE INDEX idx_idempotency_keys_key ON idempotency_keys([key]);
CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys(expires_at);
CREATE INDEX idx_idempotency_keys_request_path ON idempotency_keys(request_path);

-- Add comments to columns for documentation
EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'Unique idempotency key sent by client to prevent duplicate requests',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'key';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'API endpoint path (e.g., /plans)',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'request_path';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'SHA256 hash of request body for additional validation',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'request_body_hash';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'Cached response body in JSON format',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'response_body';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'HTTP response status code',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'response_status';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'Expiration timestamp (keys expire after 24 hours)',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys',
    @level2type = N'COLUMN', @level2name = N'expires_at';

-- Add table description
EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'Stores idempotency keys to prevent duplicate API requests from network retries. Keys automatically expire after 24 hours.',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'idempotency_keys';

PRINT 'Idempotency keys table created successfully';
