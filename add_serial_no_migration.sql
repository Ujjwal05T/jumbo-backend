-- Migration script to add serial_no columns and sequences for inward and outward challan tables
-- Run this script in your SQL Server database

-- ============================================================================
-- Step 1: Create sequences for serial number generation
-- ============================================================================

-- Create sequence for inward challan serial numbers
IF NOT EXISTS (SELECT * FROM sys.sequences WHERE name = 'inward_challan_serial_seq')
BEGIN
    CREATE SEQUENCE inward_challan_serial_seq
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 99999
    CYCLE;
    PRINT 'Created sequence: inward_challan_serial_seq';
END
ELSE
BEGIN
    PRINT 'Sequence inward_challan_serial_seq already exists';
END

-- Create sequence for outward challan serial numbers
IF NOT EXISTS (SELECT * FROM sys.sequences WHERE name = 'outward_challan_serial_seq')
BEGIN
    CREATE SEQUENCE outward_challan_serial_seq
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 99999
    CYCLE;
    PRINT 'Created sequence: outward_challan_serial_seq';
END
ELSE
BEGIN
    PRINT 'Sequence outward_challan_serial_seq already exists';
END

-- ============================================================================
-- Step 2: Add serial_no columns to both tables
-- ============================================================================

-- Add serial_no column to inward_challan table
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_NAME = 'inward_challan' AND COLUMN_NAME = 'serial_no')
BEGIN
    ALTER TABLE inward_challan
    ADD serial_no NVARCHAR(10) NULL;

    PRINT 'Added serial_no column to inward_challan table';
END
ELSE
BEGIN
    PRINT 'Column serial_no already exists in inward_challan table';
END

-- Add serial_no column to outward_challan table
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_NAME = 'outward_challan' AND COLUMN_NAME = 'serial_no')
BEGIN
    ALTER TABLE outward_challan
    ADD serial_no NVARCHAR(10) NULL;

    PRINT 'Added serial_no column to outward_challan table';
END
ELSE
BEGIN
    PRINT 'Column serial_no already exists in outward_challan table';
END

-- ============================================================================
-- Step 3: Create indexes for better performance
-- ============================================================================

-- Create index on inward_challan serial_no column
IF NOT EXISTS (SELECT * FROM sys.indexes
               WHERE name = 'IX_inward_challan_serial_no' AND object_id = OBJECT_ID('inward_challan'))
BEGIN
    CREATE INDEX IX_inward_challan_serial_no ON inward_challan(serial_no);
    PRINT 'Created index on inward_challan.serial_no';
END
ELSE
BEGIN
    PRINT 'Index IX_inward_challan_serial_no already exists';
END

-- Create index on outward_challan serial_no column
IF NOT EXISTS (SELECT * FROM sys.indexes
               WHERE name = 'IX_outward_challan_serial_no' AND object_id = OBJECT_ID('outward_challan'))
BEGIN
    CREATE INDEX IX_outward_challan_serial_no ON outward_challan(serial_no);
    PRINT 'Created index on outward_challan.serial_no';
END
ELSE
BEGIN
    PRINT 'Index IX_outward_challan_serial_no already exists';
END

-- ============================================================================
-- Step 4: Add unique constraints (optional but recommended)
-- ============================================================================

-- Add unique constraint on inward_challan serial_no
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
               WHERE CONSTRAINT_NAME = 'UQ_inward_challan_serial_no' AND TABLE_NAME = 'inward_challan')
BEGIN
    ALTER TABLE inward_challan
    ADD CONSTRAINT UQ_inward_challan_serial_no UNIQUE (serial_no);
    PRINT 'Added unique constraint on inward_challan.serial_no';
END
ELSE
BEGIN
    PRINT 'Unique constraint UQ_inward_challan_serial_no already exists';
END

-- Add unique constraint on outward_challan serial_no
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
               WHERE CONSTRAINT_NAME = 'UQ_outward_challan_serial_no' AND TABLE_NAME = 'outward_challan')
BEGIN
    ALTER TABLE outward_challan
    ADD CONSTRAINT UQ_outward_challan_serial_no UNIQUE (serial_no);
    PRINT 'Added unique constraint on outward_challan.serial_no';
END
ELSE
BEGIN
    PRINT 'Unique constraint UQ_outward_challan_serial_no already exists';
END

-- ============================================================================
-- Step 5: Update existing records with serial numbers (optional)
-- ============================================================================

-- Generate serial numbers for existing inward challan records (if any)
DECLARE @inward_counter INT = 1;
DECLARE @inward_cursor CURSOR;
DECLARE @inward_id UNIQUEIDENTIFIER;

SET @inward_cursor = CURSOR FOR
    SELECT id FROM inward_challan WHERE serial_no IS NULL ORDER BY created_at;

OPEN @inward_cursor;
FETCH NEXT FROM @inward_cursor INTO @inward_id;

WHILE @@FETCH_STATUS = 0
BEGIN
    UPDATE inward_challan
    SET serial_no = FORMAT(@inward_counter, '00000')
    WHERE id = @inward_id;

    SET @inward_counter = @inward_counter + 1;
    FETCH NEXT FROM @inward_cursor INTO @inward_id;
END

CLOSE @inward_cursor;
DEALLOCATE @inward_cursor;

-- Update the sequence to start from the correct number
DECLARE @inward_max_counter INT;
SELECT @inward_max_counter = ISNULL(MAX(CAST(serial_no AS INT)), 0) FROM inward_challan WHERE serial_no IS NOT NULL;
IF @inward_max_counter > 0
BEGIN
    DECLARE @inward_restart_value INT = @inward_max_counter + 1;
    DECLARE @inward_sql NVARCHAR(100) = N'ALTER SEQUENCE inward_challan_serial_seq RESTART WITH ' + CAST(@inward_restart_value AS NVARCHAR(10));
    EXEC sp_executesql @inward_sql;
    PRINT 'Updated inward_challan_serial_seq to restart with ' + CAST(@inward_restart_value AS NVARCHAR(10));
END

-- Generate serial numbers for existing outward challan records (if any)
DECLARE @outward_counter INT = 1;
DECLARE @outward_cursor CURSOR;
DECLARE @outward_id UNIQUEIDENTIFIER;

SET @outward_cursor = CURSOR FOR
    SELECT id FROM outward_challan WHERE serial_no IS NULL ORDER BY created_at;

OPEN @outward_cursor;
FETCH NEXT FROM @outward_cursor INTO @outward_id;

WHILE @@FETCH_STATUS = 0
BEGIN
    UPDATE outward_challan
    SET serial_no = FORMAT(@outward_counter, '00000')
    WHERE id = @outward_id;

    SET @outward_counter = @outward_counter + 1;
    FETCH NEXT FROM @outward_cursor INTO @outward_id;
END

CLOSE @outward_cursor;
DEALLOCATE @outward_cursor;

-- Update the sequence to start from the correct number
DECLARE @outward_max_counter INT;
SELECT @outward_max_counter = ISNULL(MAX(CAST(serial_no AS INT)), 0) FROM outward_challan WHERE serial_no IS NOT NULL;
IF @outward_max_counter > 0
BEGIN
    DECLARE @outward_restart_value INT = @outward_max_counter + 1;
    DECLARE @outward_sql NVARCHAR(100) = N'ALTER SEQUENCE outward_challan_serial_seq RESTART WITH ' + CAST(@outward_restart_value AS NVARCHAR(10));
    EXEC sp_executesql @outward_sql;
    PRINT 'Updated outward_challan_serial_seq to restart with ' + CAST(@outward_restart_value AS NVARCHAR(10));
END

-- ============================================================================
-- Step 6: Verification queries
-- ============================================================================

PRINT '============================================================================';
PRINT 'MIGRATION COMPLETED - VERIFICATION';
PRINT '============================================================================';

-- Check sequences
SELECT
    name AS sequence_name,
    current_value,
    start_value,
    increment,
    minimum_value,
    maximum_value
FROM sys.sequences
WHERE name IN ('inward_challan_serial_seq', 'outward_challan_serial_seq');

-- Check columns
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('inward_challan', 'outward_challan')
AND COLUMN_NAME = 'serial_no';

-- Check indexes
SELECT
    i.name AS index_name,
    t.name AS table_name,
    c.name AS column_name,
    i.is_unique
FROM sys.indexes i
JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
JOIN sys.tables t ON i.object_id = t.object_id
WHERE c.name = 'serial_no' AND t.name IN ('inward_challan', 'outward_challan');

-- Check constraints
SELECT
    CONSTRAINT_NAME,
    TABLE_NAME,
    CONSTRAINT_TYPE
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
WHERE CONSTRAINT_NAME LIKE '%serial_no%'
AND TABLE_NAME IN ('inward_challan', 'outward_challan');

-- Sample data check
PRINT 'Sample records with serial numbers:';
SELECT TOP 5 id, serial_no, created_at FROM inward_challan ORDER BY created_at DESC;
SELECT TOP 5 id, serial_no, created_at FROM outward_challan ORDER BY created_at DESC;

PRINT '============================================================================';
PRINT 'MIGRATION VERIFICATION COMPLETED';
PRINT '============================================================================';