-- Rollback Migration: Remove rst_no and gross_weight from dispatch_record table
-- Date: 2025-12-30
-- Description: Rollback script to remove rst_no and gross_weight fields from dispatch_record table

-- Drop index first
DROP INDEX IF EXISTS idx_dispatch_record_rst_no ON dispatch_record;

-- Drop columns
ALTER TABLE dispatch_record
DROP COLUMN IF EXISTS rst_no;

ALTER TABLE dispatch_record
DROP COLUMN IF EXISTS gross_weight;
