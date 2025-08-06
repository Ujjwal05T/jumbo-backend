-- Migration: Add plan generation tracking fields to pending_order_item table
-- Date: 2025-01-XX
-- Description: Add fields to track which pending orders were included in plan generation

-- Add new columns for plan generation tracking
ALTER TABLE pending_order_item 
ADD COLUMN included_in_plan_generation BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE pending_order_item 
ADD COLUMN generated_cut_rolls_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE pending_order_item 
ADD COLUMN plan_generation_date DATETIME NULL;

-- Add index for better query performance
CREATE INDEX idx_pending_order_item_plan_generation 
ON pending_order_item(included_in_plan_generation);

-- Update existing records (all existing pending orders were not included in plan generation by default)
-- No update needed since default values are already correct

COMMIT;