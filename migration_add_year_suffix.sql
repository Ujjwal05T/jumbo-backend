-- =====================================================
-- Migration Script: Add Year Suffix to Existing IDs and Barcodes
-- =====================================================
-- This script updates all existing records to include year suffix
-- Format: OLD (ORD-00001) -> NEW (ORD-00001-25)
-- =====================================================

-- IMPORTANT: Backup your database before running this script!
-- Run these queries in order

-- =====================================================
-- OPTION 1: Use Current Year (25 for 2025)
-- Use this if you want all existing records to have the current year
-- =====================================================

-- SKIPPED: Client Master IDs (uses simple format CL-00001 without year suffix)
-- SKIPPED: User Master IDs (uses simple format USR-00001 without year suffix)
-- SKIPPED: Paper Master IDs (uses simple format PAP-00001 without year suffix)

-- 1. Update Manual Cut Roll IDs
UPDATE manual_cut_roll
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 2. Update Order Master IDs
UPDATE order_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 3. Update Order Item IDs
UPDATE order_item
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 4. Update Pending Order Master IDs
UPDATE pending_order_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 5. Update Pending Order Item IDs
UPDATE pending_order_item
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 6. Update Inventory Master IDs (frontend_id)
UPDATE inventory_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 7. Update Plan Master IDs
UPDATE plan_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 8. Update Production Order Master IDs
UPDATE production_order_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 9. Update Plan Order Link IDs
UPDATE plan_order_link
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 10. Update Plan Inventory Link IDs
UPDATE plan_inventory_link
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 11. Update Dispatch Record IDs
UPDATE dispatch_record
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 12. Update Dispatch Item IDs
UPDATE dispatch_item
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 13. Update Wastage Inventory IDs (frontend_id)
UPDATE wastage_inventory
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 14. Update Past Dispatch Record IDs
UPDATE past_dispatch_record
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 15. Update Inward Challan Serial Numbers
UPDATE inward_challan
SET serial_no = serial_no + '-25'
WHERE serial_no NOT LIKE '%-__'
  AND serial_no IS NOT NULL;

-- 16. Update Outward Challan Serial Numbers
UPDATE outward_challan
SET serial_no = serial_no + '-25'
WHERE serial_no NOT LIKE '%-__'
  AND serial_no IS NOT NULL;

-- 17. Update Order Edit Log IDs
UPDATE order_edit_log
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 18. Update Payment Slip Master IDs (both BI- and CI- prefixes)
UPDATE payment_slip_master
SET frontend_id = frontend_id + '-25'
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL
  AND (frontend_id LIKE 'BI-%' OR frontend_id LIKE 'CI-%');

-- =====================================================
-- BARCODES: Update barcode_id columns
-- =====================================================

-- 19. Update Inventory Master Barcodes (CR_, JR_, SET_, INV_, SCR-)
UPDATE inventory_master
SET barcode_id = barcode_id + '-25'
WHERE barcode_id NOT LIKE '%-__'  -- Only update if year suffix doesn't exist
  AND barcode_id IS NOT NULL
  AND (
    barcode_id LIKE 'CR[_]%'
    OR barcode_id LIKE 'JR[_]%'
    OR barcode_id LIKE 'SET[_]%'
    OR barcode_id LIKE 'INV[_]%'
    OR barcode_id LIKE 'SCR-%'
  );

-- 20. Update Manual Cut Roll Barcodes (CR_)
UPDATE manual_cut_roll
SET barcode_id = barcode_id + '-25'
WHERE barcode_id NOT LIKE '%-__'
  AND barcode_id IS NOT NULL
  AND barcode_id LIKE 'CR[_]%';

-- 21. Update Wastage Inventory Barcodes (WSB-)
UPDATE wastage_inventory
SET barcode_id = barcode_id + '-25'
WHERE barcode_id NOT LIKE '%-__-__'  -- WSB already has one dash, so pattern is different
  AND barcode_id IS NOT NULL
  AND barcode_id LIKE 'WSB-%'
  AND LEN(barcode_id) = 9;  -- WSB-00001 is 9 chars, WSB-00001-25 is 12 chars


-- =====================================================
-- OPTION 2: Use Year from Creation Date
-- Use this if you want to preserve the original year from created_at
-- Replace OPTION 1 queries with these
-- =====================================================

-- Example for Order Master (adjust table names as needed)
/*
UPDATE order_master
SET frontend_id = frontend_id + '-' + RIGHT(YEAR(created_at), 2)
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL
  AND created_at IS NOT NULL;
*/

-- Example with year extraction for each table:
/*
UPDATE client_master
SET frontend_id = frontend_id + '-' + RIGHT(CAST(YEAR(created_at) AS VARCHAR), 2)
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL
  AND created_at IS NOT NULL;

UPDATE order_master
SET frontend_id = frontend_id + '-' + RIGHT(CAST(YEAR(created_at) AS VARCHAR), 2)
WHERE frontend_id NOT LIKE '%-__'
  AND frontend_id IS NOT NULL
  AND created_at IS NOT NULL;

UPDATE inventory_master
SET frontend_id = frontend_id + '-' + RIGHT(CAST(YEAR(created_at) AS VARCHAR), 2),
    barcode_id = barcode_id + '-' + RIGHT(CAST(YEAR(created_at) AS VARCHAR), 2)
WHERE (frontend_id NOT LIKE '%-__' OR barcode_id NOT LIKE '%-__')
  AND created_at IS NOT NULL;
*/


-- =====================================================
-- VERIFICATION QUERIES
-- Run these to check the migration was successful
-- =====================================================

-- Check Client Master
SELECT TOP 10 frontend_id, created_at FROM client_master ORDER BY id DESC;

-- Check Order Master
SELECT TOP 10 frontend_id, created_at FROM order_master ORDER BY id DESC;

-- Check Inventory Master (both frontend_id and barcode_id)
SELECT TOP 10 frontend_id, barcode_id, created_at FROM inventory_master ORDER BY id DESC;

-- Check Wastage Inventory
SELECT TOP 10 frontend_id, barcode_id, created_at FROM wastage_inventory ORDER BY id DESC;

-- Check Manual Cut Roll
SELECT TOP 10 frontend_id, barcode_id, created_at FROM manual_cut_roll ORDER BY id DESC;

-- Count records without year suffix (should be 0 after migration)
SELECT
    'client_master' as table_name,
    COUNT(*) as records_without_suffix
FROM client_master
WHERE frontend_id NOT LIKE '%-__' AND frontend_id IS NOT NULL

UNION ALL

SELECT
    'order_master' as table_name,
    COUNT(*) as records_without_suffix
FROM order_master
WHERE frontend_id NOT LIKE '%-__' AND frontend_id IS NOT NULL

UNION ALL

SELECT
    'inventory_master_barcodes' as table_name,
    COUNT(*) as records_without_suffix
FROM inventory_master
WHERE barcode_id NOT LIKE '%-__' AND barcode_id IS NOT NULL
    AND (barcode_id LIKE 'CR[_]%' OR barcode_id LIKE 'JR[_]%' OR barcode_id LIKE 'SET[_]%');


-- =====================================================
-- ROLLBACK QUERIES (if needed)
-- Use these to remove year suffixes and restore original format
-- =====================================================

/*
-- IMPORTANT: These queries reverse the migration by removing year suffixes
-- Client Master, User Master, and Paper Master are NOT included (they never had year suffixes)

-- 1. Rollback Manual Cut Roll IDs
UPDATE manual_cut_roll
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 2. Rollback Order Master IDs
UPDATE order_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 3. Rollback Order Item IDs
UPDATE order_item
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 4. Rollback Pending Order Master IDs
UPDATE pending_order_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 5. Rollback Pending Order Item IDs
UPDATE pending_order_item
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 6. Rollback Inventory Master IDs (frontend_id)
UPDATE inventory_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 7. Rollback Plan Master IDs
UPDATE plan_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 8. Rollback Production Order Master IDs
UPDATE production_order_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 9. Rollback Plan Order Link IDs
UPDATE plan_order_link
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 10. Rollback Plan Inventory Link IDs
UPDATE plan_inventory_link
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 11. Rollback Dispatch Record IDs
UPDATE dispatch_record
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 12. Rollback Dispatch Item IDs
UPDATE dispatch_item
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 13. Rollback Wastage Inventory IDs (frontend_id)
UPDATE wastage_inventory
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 14. Rollback Past Dispatch Record IDs
UPDATE past_dispatch_record
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 15. Rollback Inward Challan Serial Numbers
UPDATE inward_challan
SET serial_no = LEFT(serial_no, LEN(serial_no) - 3)
WHERE serial_no LIKE '%-__'
  AND serial_no IS NOT NULL;

-- 16. Rollback Outward Challan Serial Numbers
UPDATE outward_challan
SET serial_no = LEFT(serial_no, LEN(serial_no) - 3)
WHERE serial_no LIKE '%-__'
  AND serial_no IS NOT NULL;

-- 17. Rollback Order Edit Log IDs
UPDATE order_edit_log
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL;

-- 18. Rollback Payment Slip Master IDs (both BI- and CI- prefixes)
UPDATE payment_slip_master
SET frontend_id = LEFT(frontend_id, LEN(frontend_id) - 3)
WHERE frontend_id LIKE '%-__'
  AND frontend_id IS NOT NULL
  AND (frontend_id LIKE 'BI-%' OR frontend_id LIKE 'CI-%');

-- =====================================================
-- ROLLBACK BARCODES
-- =====================================================

-- 19. Rollback Inventory Master Barcodes (CR_, JR_, SET_, INV_)
UPDATE inventory_master
SET barcode_id = LEFT(barcode_id, LEN(barcode_id) - 3)
WHERE barcode_id NOT LIKE '%-__-__'  -- Avoid WSB- format which has 2 dashes
  AND barcode_id LIKE '%-__'
  AND barcode_id IS NOT NULL
  AND (
    barcode_id LIKE 'CR[_]%-%__'
    OR barcode_id LIKE 'JR[_]%-%__'
    OR barcode_id LIKE 'SET[_]%-%__'
    OR barcode_id LIKE 'INV[_]%-%__'
  );

-- 20. Rollback SCR- barcodes in Inventory Master (SCR-00001-25 -> SCR-00001)
UPDATE inventory_master
SET barcode_id = LEFT(barcode_id, LEN(barcode_id) - 3)
WHERE barcode_id LIKE 'SCR-%-__'
  AND barcode_id IS NOT NULL;

-- 21. Rollback Manual Cut Roll Barcodes (CR_)
UPDATE manual_cut_roll
SET barcode_id = LEFT(barcode_id, LEN(barcode_id) - 3)
WHERE barcode_id LIKE 'CR[_]%-%__'
  AND barcode_id IS NOT NULL;

-- 22. Rollback Wastage Inventory Barcodes (WSB-00001-25 -> WSB-00001)
UPDATE wastage_inventory
SET barcode_id = LEFT(barcode_id, LEN(barcode_id) - 3)
WHERE barcode_id LIKE 'WSB-%-__'
  AND LEN(barcode_id) = 12  -- WSB-00001-25 is 12 chars
  AND barcode_id IS NOT NULL;

-- 23. Rollback Wastage Inventory frontend_id was already covered in step 13
*/
