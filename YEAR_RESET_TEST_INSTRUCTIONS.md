# Year Reset Testing Instructions (Dec 29, 2024)

## Overview
Temporary test code has been added to simulate year change on **December 29th** so you can test the counter reset functionality without waiting until January 1st.

## What's Changed

### Test Logic Added:
- **ID Generator** ([id_generator.py](app/services/id_generator.py:149-163))
- **Barcode Generator** ([barcode_generator.py](app/services/barcode_generator.py))

### Behavior on Dec 29:
- System treats today as if it's year **"26"** (2026)
- All new IDs/barcodes will use suffix `-26`
- Since no records exist with `-26`, counters will reset to `00001`

## How to Test

### Step 1: Create some records with current year (25)
```bash
# Example: Create an order
# This should generate: ORD-00001-25, ORD-00002-25, etc.
```

**Expected:**
- IDs end with `-25`
- Counters increment normally: `ORD-00001-25`, `ORD-00002-25`, `ORD-00003-25`

### Step 2: Check logs for test mode warning
Look for this log message:
```
WARNING: TEST MODE: Using year 26 for testing (Dec 29)
```

### Step 3: Create new records (simulates Jan 1st)
```bash
# Create another order
# This should generate: ORD-00001-26 (counter reset!)
```

**Expected:**
- IDs now end with `-26`
- Counter resets to `00001`: `ORD-00001-26`
- Old `-25` records are still in database, untouched

### Step 4: Verify counter reset for all types

Test different record types to verify each resets properly:

| Type | Year 25 (before) | Year 26 (after reset) |
|------|------------------|----------------------|
| Orders | `ORD-00123-25` | `ORD-00001-26` ✅ |
| Clients | `CL-00045-25` | `CL-00001-26` ✅ |
| Cut Rolls | `CR_00567-25` | `CR_00001-26` ✅ |
| Wastage | `WSB-00234-25` | `WSB-00001-26` ✅ |
| Manual Cut Rolls | `CR_08123-25` | `CR_08000-26` ✅ |

### Step 5: Query database to verify both years coexist
```sql
-- Check orders for both years
SELECT frontend_id, created_at
FROM order_master
WHERE frontend_id LIKE 'ORD-%'
ORDER BY created_at DESC;

-- Should see both:
-- ORD-00001-26 (newest)
-- ORD-00003-25
-- ORD-00002-25
-- ORD-00001-25 (oldest)
```

## Test Scenarios

### Scenario A: Normal Counter Increment (Year 25)
1. Create records
2. Verify: `ORD-00001-25`, `ORD-00002-25`, `ORD-00003-25`
3. Counter increments properly ✅

### Scenario B: Year Change Simulation (Year 26)
1. System detects Dec 29
2. Switches to year "26"
3. Queries database for `-26` records
4. Finds NONE → max_counter = 0
5. Generates: `ORD-00001-26` (reset!) ✅

### Scenario C: Continued Operations (Year 26)
1. Create more records
2. Verify: `ORD-00001-26`, `ORD-00002-26`, `ORD-00003-26`
3. Counter increments from new base ✅

### Scenario D: Manual Cut Roll Reserved Range
1. Year 25: `CR_08000-25` to `CR_08999-25`
2. Year 26: Resets to `CR_08000-26` ✅
3. Range limit still enforced (max 1001 per year)

## What to Check

### ✅ Checklist:
- [ ] Logs show "TEST MODE" warning
- [ ] New IDs use suffix `-26`
- [ ] Counters reset to `00001` (or `08000` for manual cut rolls)
- [ ] Old `-25` records remain unchanged
- [ ] Database can query both years separately
- [ ] Validation accepts both `-25` and `-26` formats
- [ ] Reserved ranges still work (CR_08000-26 to CR_09000-26)

## Expected Database State After Testing

```
Table: order_master
+----------------+---------------------+
| frontend_id    | created_at          |
+----------------+---------------------+
| ORD-00001-26   | 2024-12-29 10:15:00 | ← New year (reset)
| ORD-00002-26   | 2024-12-29 10:16:00 |
| ORD-00003-25   | 2024-12-28 14:30:00 | ← Old year
| ORD-00002-25   | 2024-12-28 12:00:00 |
| ORD-00001-25   | 2024-12-27 09:00:00 |
+----------------+---------------------+
```

## How to Switch Back to Year 25 for Testing

Edit the test code in both files:

**id_generator.py:156**
```python
# Change this:
current_year = "26"  # Change this to "25" to test old year behavior

# To this:
current_year = "25"  # Testing old year
```

Do the same in **barcode_generator.py** for all methods.

## IMPORTANT: Remove Test Code Before Production!

### When Testing is Complete:

1. **Search for**: `TEMPORARY TEST CODE`
2. **Remove all test blocks** in:
   - `id_generator.py` (lines 149-163)
   - `barcode_generator.py` (multiple methods)
3. **Restore to**:
   ```python
   current_year = datetime.now().strftime("%y")
   ```

### Or use this command to find all test code:
```bash
grep -n "TEMPORARY TEST CODE" app/services/*.py
```

## Production Behavior (After Removing Test Code)

On **January 1, 2026**:
- System automatically uses `current_year = "26"`
- Counters automatically reset to `00001`
- **No manual intervention needed!**

The year change happens naturally based on system date.

---

## Troubleshooting

### Issue: Still getting `-25` suffix
**Solution**: Check system date is Dec 29, or verify test code is active

### Issue: Logs don't show "TEST MODE" warning
**Solution**: Check logger level is set to WARNING or DEBUG

### Issue: Counter not resetting
**Solution**: Verify database has no `-26` records yet (should be empty)

### Issue: Getting errors about sequence
**Solution**: Test code bypasses SQL sequences - this is expected and normal

---

**Remember**: This is TEMPORARY TEST CODE. Remove it before deploying to production!
