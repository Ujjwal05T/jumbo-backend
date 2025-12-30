-- Migration: Add rst_no and gross_weight to dispatch_record table
-- Date: 2025-12-30
-- Description: Adds rst_no and gross_weight fields to dispatch_record table for OutwardChallan integration

-- Add rst_no column
ALTER TABLE dispatch_record
ADD COLUMN rst_no VARCHAR(50) NULL;

-- Add gross_weight column
ALTER TABLE dispatch_record
ADD COLUMN gross_weight DECIMAL(10, 3) NULL;

-- Create index on rst_no for faster lookups
CREATE INDEX idx_dispatch_record_rst_no ON dispatch_record(rst_no);

-- Add comment to columns for documentation
EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'RST number from OutwardChallan for auto-filling dispatch details',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'dispatch_record',
    @level2type = N'COLUMN', @level2name = N'rst_no';

EXEC sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'Gross weight from OutwardChallan in kilograms',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE',  @level1name = N'dispatch_record',
    @level2type = N'COLUMN', @level2name = N'gross_weight';
