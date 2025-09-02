#!/usr/bin/env python3
"""
Inventory Data Import Script
Imports inventory data from Excel file to the inventory_items table
Supports batch processing for large datasets (5700+ rows)
"""

import pandas as pd
import os
import sys
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

# Add the app directory to Python path to import models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.database import SessionLocal, engine
from app.models import InventoryItem

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('inventory_import.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class InventoryImporter:
    def __init__(self, excel_file_path: str, batch_size: int = 1000):
        self.excel_file_path = excel_file_path
        self.batch_size = batch_size
        self.total_processed = 0
        self.total_errors = 0
        
    def validate_file(self) -> bool:
        """Validate if the Excel file exists and is readable"""
        if not os.path.exists(self.excel_file_path):
            logger.error(f"File not found: {self.excel_file_path}")
            return False
        
        try:
            # Try to read the first few rows to validate format
            df_sample = pd.read_excel(self.excel_file_path, nrows=5)
            logger.info(f"File validation successful. Columns: {list(df_sample.columns)}")
            logger.info(f"Sample data shape: {df_sample.shape}")
            return True
        except Exception as e:
            logger.error(f"File validation failed: {e}")
            return False
    
    def clean_and_transform_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and transform the data before insertion"""
        logger.info("Cleaning and transforming data...")
        
        # Make a copy to avoid modifying original
        df_clean = df.copy()
        
        # Expected column mapping (adjust based on your Excel file structure)
        # You may need to modify these column names to match your Excel file
        column_mapping = {
            'SNO': 'sno_from_file',
            'S.No': 'sno_from_file',
            'Serial No': 'sno_from_file',
            'REEL NO': 'reel_no',
            'ReelNo': 'reel_no',
            'Reel_No': 'reel_no',
            'GSM': 'gsm',
            'BF': 'bf',
            'SIZE': 'size',
            'WEIGHT': 'weight_kg',
            'Weight (KG)': 'weight_kg',
            'WeightKG': 'weight_kg',
            'GY/N': 'grade',
            'Stock Date': 'stock_date',
            'StockDate': 'stock_date',
            'date': 'stock_date'
        }
        
        # Rename columns based on mapping
        for old_name, new_name in column_mapping.items():
            if old_name in df_clean.columns:
                df_clean = df_clean.rename(columns={old_name: new_name})
                logger.info(f"Mapped column '{old_name}' to '{new_name}'")
        
        # Handle missing columns by creating them with default values
        required_columns = ['sno_from_file', 'reel_no', 'gsm', 'bf', 'size', 'weight_kg', 'grade', 'stock_date']
        for col in required_columns:
            if col not in df_clean.columns:
                df_clean[col] = None
                logger.warning(f"Column '{col}' not found, setting to None")
        
        # Data cleaning and type conversion
        try:
            # Convert numeric columns with better error handling
            if 'sno_from_file' in df_clean.columns:
                df_clean['sno_from_file'] = pd.to_numeric(df_clean['sno_from_file'], errors='coerce')
                df_clean['sno_from_file'] = df_clean['sno_from_file'].astype('Int64')  # Nullable integer
            
            if 'gsm' in df_clean.columns:
                df_clean['gsm'] = pd.to_numeric(df_clean['gsm'], errors='coerce')
                df_clean['gsm'] = df_clean['gsm'].astype('Int64')  # Nullable integer
                
            if 'bf' in df_clean.columns:
                df_clean['bf'] = pd.to_numeric(df_clean['bf'], errors='coerce')
                df_clean['bf'] = df_clean['bf'].astype('Int64')  # Nullable integer
                
            if 'weight_kg' in df_clean.columns:
                df_clean['weight_kg'] = pd.to_numeric(df_clean['weight_kg'], errors='coerce')
                # Remove any infinite or very large values that might cause SQL Server issues
                df_clean['weight_kg'] = df_clean['weight_kg'].replace([float('inf'), float('-inf')], None)
                df_clean.loc[df_clean['weight_kg'] > 999999, 'weight_kg'] = None
            
            # Convert date column
            if 'stock_date' in df_clean.columns:
                df_clean['stock_date'] = pd.to_datetime(df_clean['stock_date'], errors='coerce')
            
            # Convert string columns and handle NaN
            string_columns = ['reel_no', 'size', 'grade']
            for col in string_columns:
                if col in df_clean.columns:
                    df_clean[col] = df_clean[col].astype(str).replace('nan', None)
            
            # Add import timestamp
            df_clean['record_imported_at'] = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Error during data cleaning: {e}")
            raise
        
        logger.info(f"Data cleaning completed. Shape: {df_clean.shape}")
        return df_clean
    
    def insert_batch(self, db: Session, batch_df: pd.DataFrame) -> tuple[int, int]:
        """Insert records one by one to avoid SQL Server batch issues"""
        success_count = 0
        error_count = 0
        
        # Convert DataFrame to list of dictionaries
        records = batch_df.to_dict('records')
        
        for i, record in enumerate(records):
            try:
                # Clean and validate data before insertion
                weight_kg = record.get('weight_kg')
                if pd.isna(weight_kg) or weight_kg is None:
                    weight_kg = None
                elif isinstance(weight_kg, (int, float)):
                    # Convert to float and handle edge cases
                    weight_kg = float(weight_kg)
                    if weight_kg < 0 or weight_kg > 999999:
                        weight_kg = None
                
                # Clean integer fields
                def clean_int(val):
                    if pd.isna(val) or val is None:
                        return None
                    try:
                        return int(val) if val != '' else None
                    except:
                        return None
                
                # Create InventoryItem instance
                inventory_item = InventoryItem(
                    sno_from_file=clean_int(record.get('sno_from_file')),
                    reel_no=str(record.get('reel_no')) if record.get('reel_no') is not None else None,
                    gsm=clean_int(record.get('gsm')),
                    bf=clean_int(record.get('bf')),
                    size=str(record.get('size')) if record.get('size') is not None else None,
                    weight_kg=weight_kg,
                    grade=str(record.get('grade')) if record.get('grade') is not None else None,
                    stock_date=record.get('stock_date') if pd.notna(record.get('stock_date')) else None,
                    record_imported_at=record.get('record_imported_at')
                )
                
                db.add(inventory_item)
                db.commit()  # Commit each record individually
                success_count += 1
                
                # Progress indicator
                if (i + 1) % 100 == 0:
                    logger.info(f"  Processed {i + 1}/{len(records)} records in batch")
                    
            except Exception as e:
                db.rollback()
                logger.error(f"Error inserting record {i+1}: {record}. Error: {e}")
                error_count += 1
                continue
        
        logger.info(f"Batch completed: {success_count} success, {error_count} errors")
        return success_count, error_count
    
    def import_data(self) -> bool:
        """Main method to import data from Excel file"""
        logger.info(f"Starting import from: {self.excel_file_path}")
        
        # Validate file
        if not self.validate_file():
            return False
        
        try:
            # Read Excel file
            logger.info("Reading Excel file...")
            df = pd.read_excel(self.excel_file_path)
            logger.info(f"Total rows in Excel: {len(df)}")
            
            # Clean and transform data
            df_clean = self.clean_and_transform_data(df)
            
            # Process in batches
            total_rows = len(df_clean)
            logger.info(f"Processing {total_rows} rows in batches of {self.batch_size}")
            
            db = SessionLocal()
            try:
                for i in range(0, total_rows, self.batch_size):
                    batch_end = min(i + self.batch_size, total_rows)
                    batch_df = df_clean.iloc[i:batch_end]
                    
                    logger.info(f"Processing batch {i//self.batch_size + 1}: rows {i+1} to {batch_end}")
                    
                    success, errors = self.insert_batch(db, batch_df)
                    self.total_processed += success
                    self.total_errors += errors
                    
                    logger.info(f"Batch completed: {success} success, {errors} errors")
            
            finally:
                db.close()
            
            # Summary
            logger.info("=" * 50)
            logger.info("IMPORT SUMMARY")
            logger.info("=" * 50)
            logger.info(f"Total rows processed: {self.total_processed}")
            logger.info(f"Total errors: {self.total_errors}")
            logger.info(f"Success rate: {(self.total_processed/(self.total_processed + self.total_errors))*100:.2f}%")
            
            return self.total_errors == 0
            
        except Exception as e:
            logger.error(f"Import failed with error: {e}")
            return False

def main():
    """Main function to run the import"""
    print("Inventory Data Import Script")
    print("=" * 40)
    
    # Get Excel file path from user
    excel_file = 'D:\\JumboReelApp\\backend\\Finishing Stock 21052025 (guptaji) (Autosaved).xlsx'
    
    if not excel_file:
        print("No file path provided. Exiting...")
        return
    
    # Create importer instance
    importer = InventoryImporter(excel_file, batch_size=1000)
    
    # Confirm before proceeding
    print(f"\nFile to import: {excel_file}")
    confirm = input("Do you want to proceed with the import? (y/N): ").strip().lower()
    
    if confirm != 'y':
        print("Import cancelled.")
        return
    
    # Start import
    print("\nStarting import process...")
    success = importer.import_data()
    
    if success:
        print("\n✅ Import completed successfully!")
    else:
        print("\n❌ Import completed with errors. Check the log file for details.")
    
    print("\nCheck 'inventory_import.log' for detailed logs.")

if __name__ == "__main__":
    main()