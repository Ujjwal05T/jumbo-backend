#!/usr/bin/env python3
"""
Frontend ID Migration Script
============================

Converts existing year-month based frontend IDs to simple sequential format.

Before: ORD-25-08-0001, PLN-25-08-0001, DSP-25-08-0001
After:  ORD-000001, PLN-000001, DSP-000001

IMPORTANT: 
1. Take database backup before running
2. Test on development environment first
3. Run during maintenance window
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple
import logging

# Add the app directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'id_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FrontendIDMigrator:
    """Handles migration of frontend IDs from year-month format to sequential format."""
    
    # Tables that use year-month format and need migration
    TABLES_TO_MIGRATE = {
        "order_master": {
            "prefix": "ORD",
            "old_pattern": r"%-%-%-%",  # ORD-YY-MM-NNNN
            "description": "Order Master records"
        },
        "plan_master": {
            "prefix": "PLN", 
            "old_pattern": r"%-%-%-%",  # PLN-YY-MM-NNNN
            "description": "Plan Master records"
        },
        "dispatch_record": {
            "prefix": "DSP",
            "old_pattern": r"%-%-%-%",  # DSP-YY-MM-NNNN
            "description": "Dispatch Record records"
        },
        "past_dispatch_record": {
            "prefix": "PDR",
            "old_pattern": r"%-%-%-%",  # PDR-YY-MM-NNNN
            "description": "Past Dispatch Record records"
        }
    }
    
    def __init__(self, connection_string: str):
        """Initialize migrator with database connection."""
        self.connection_string = connection_string
        self.engine = None
        self.Session = None
        self.migration_stats = {}
    
    def connect(self):
        """Establish database connection."""
        try:
            self.engine = create_engine(self.connection_string, echo=False)
            self.Session = sessionmaker(bind=self.engine)
            logger.info("✅ Database connection established")
        except Exception as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            raise
    
    def verify_backup_exists(self) -> bool:
        """Verify that a recent backup exists (placeholder - implement based on your backup strategy)."""
        logger.warning("⚠️  BACKUP VERIFICATION: Please ensure you have taken a recent database backup!")
        response = input("Have you taken a database backup? (yes/no): ").lower().strip()
        return response in ['yes', 'y']
    
    def analyze_migration_scope(self) -> Dict:
        """Analyze what needs to be migrated and provide impact assessment."""
        db = self.Session()
        analysis = {}
        
        try:
            logger.info("🔍 Analyzing migration scope...")
            
            total_records = 0
            for table_name, config in self.TABLES_TO_MIGRATE.items():
                # Check if table exists
                table_check = text(f"""
                    SELECT COUNT(*) as table_exists
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_NAME = :table_name
                """)
                table_exists = db.execute(table_check, {"table_name": table_name}).scalar()
                
                if not table_exists:
                    logger.warning(f"⚠️  Table {table_name} does not exist, skipping...")
                    continue
                
                # Count records with old format
                old_format_query = text(f"""
                    SELECT COUNT(*) as old_format_count
                    FROM {table_name}
                    WHERE frontend_id LIKE :pattern
                      AND frontend_id IS NOT NULL
                """)
                
                old_count = db.execute(old_format_query, {"pattern": config["old_pattern"]}).scalar()
                
                # Count total records
                total_query = text(f"SELECT COUNT(*) FROM {table_name}")
                total_count = db.execute(total_query).scalar()
                
                analysis[table_name] = {
                    "total_records": total_count,
                    "old_format_records": old_count,
                    "needs_migration": old_count > 0,
                    "prefix": config["prefix"],
                    "description": config["description"]
                }
                
                total_records += old_count
                
                logger.info(f"  📊 {table_name}: {old_count}/{total_count} records need migration")
            
            analysis["summary"] = {
                "total_tables": len([t for t in analysis.values() if isinstance(t, dict) and t.get("needs_migration")]),
                "total_records_to_migrate": total_records
            }
            
            logger.info(f"📈 Migration scope: {total_records} records across {len(analysis)-1} tables")
            return analysis
            
        except SQLAlchemyError as e:
            logger.error(f"❌ Error analyzing migration scope: {e}")
            raise
        finally:
            db.close()
    
    def migrate_table(self, table_name: str, config: Dict, dry_run: bool = False) -> Dict:
        """Migrate a single table's frontend IDs."""
        db = self.Session()
        migration_log = []
        
        try:
            logger.info(f"🚀 {'DRY RUN: ' if dry_run else ''}Migrating {table_name}...")
            
            # Get all records with old format IDs, ordered by creation date
            fetch_query = text(f"""
                SELECT id, frontend_id, created_at
                FROM {table_name}
                WHERE frontend_id LIKE :pattern
                  AND frontend_id IS NOT NULL
                ORDER BY created_at ASC, id ASC
            """)
            
            records = db.execute(fetch_query, {"pattern": config["old_pattern"]}).fetchall()
            
            if not records:
                logger.info(f"  ✅ No records to migrate in {table_name}")
                return {"migrated_count": 0, "errors": [], "log": []}
            
            prefix = config["prefix"]
            counter = 1
            errors = []
            
            for record in records:
                old_id = record.frontend_id
                new_id = f"{prefix}-{counter:06d}"
                
                # Log the change
                log_entry = f"{old_id} → {new_id}"
                migration_log.append(log_entry)
                
                if not dry_run:
                    try:
                        # Update the record
                        update_query = text(f"""
                            UPDATE {table_name}
                            SET frontend_id = :new_id,
                                updated_at = GETDATE()
                            WHERE id = :record_id
                        """)
                        
                        db.execute(update_query, {
                            "new_id": new_id,
                            "record_id": record.id
                        })
                        
                    except SQLAlchemyError as e:
                        error_msg = f"Failed to update record {record.id}: {e}"
                        errors.append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                        continue
                
                if counter % 100 == 0:
                    logger.info(f"  📊 Processed {counter} records...")
                
                counter += 1
            
            if not dry_run:
                db.commit()
                logger.info(f"  ✅ Migrated {counter-1} records in {table_name}")
            else:
                logger.info(f"  📋 DRY RUN: Would migrate {counter-1} records in {table_name}")
            
            return {
                "migrated_count": counter - 1,
                "errors": errors,
                "log": migration_log[:10]  # Keep first 10 for summary
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"❌ Error migrating {table_name}: {e}")
            raise
        finally:
            db.close()
    
    def run_migration(self, dry_run: bool = False) -> bool:
        """Run the complete migration process."""
        try:
            logger.info("="*60)
            logger.info(f"🚀 FRONTEND ID MIGRATION {'(DRY RUN)' if dry_run else ''}")
            logger.info("="*60)
            
            # Step 1: Verify backup
            if not dry_run and not self.verify_backup_exists():
                logger.error("❌ Migration aborted: No backup verification")
                return False
            
            # Step 2: Analyze scope
            analysis = self.analyze_migration_scope()
            if analysis["summary"]["total_records_to_migrate"] == 0:
                logger.info("✅ No records need migration")
                return True
            
            # Step 3: Confirm migration
            if not dry_run:
                logger.warning(f"⚠️  About to migrate {analysis['summary']['total_records_to_migrate']} records")
                response = input("Continue with migration? (yes/no): ").lower().strip()
                if response not in ['yes', 'y']:
                    logger.info("Migration cancelled by user")
                    return False
            
            # Step 4: Migrate each table
            migration_results = {}
            total_migrated = 0
            total_errors = 0
            
            for table_name, config in self.TABLES_TO_MIGRATE.items():
                if table_name not in analysis or not analysis[table_name]["needs_migration"]:
                    continue
                
                result = self.migrate_table(table_name, config, dry_run)
                migration_results[table_name] = result
                total_migrated += result["migrated_count"]
                total_errors += len(result["errors"])
                
                # Show sample migrations
                if result["log"]:
                    logger.info(f"    Sample migrations:")
                    for log_entry in result["log"][:3]:
                        logger.info(f"      {log_entry}")
            
            # Step 5: Summary
            logger.info("="*60)
            logger.info("📊 MIGRATION SUMMARY")
            logger.info("="*60)
            logger.info(f"Total records migrated: {total_migrated}")
            logger.info(f"Total errors: {total_errors}")
            
            if total_errors == 0:
                logger.info("Migration completed successfully!")
            else:
                logger.warning(f"Migration completed with {total_errors} errors")
                
                # Show detailed error information
                logger.warning("Error details:")
                for table_name, result in migration_results.items():
                    if result.get("errors"):
                        logger.warning(f"  {table_name}: {len(result['errors'])} errors")
                        for error in result["errors"][:3]:  # Show first 3 errors
                            logger.warning(f"    - {error}")
            
            # Store results for reference
            self.migration_stats = {
                "total_migrated": total_migrated,
                "total_errors": total_errors,
                "results_by_table": migration_results
            }
            
            return total_errors == 0
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return False
    
    def generate_sequence_creation_script(self) -> str:
        """Generate SQL script to create sequences with appropriate start values."""
        if not hasattr(self, 'migration_stats') or not self.migration_stats:
            logger.error("❌ Run migration first to generate sequence script")
            return ""
        
        script_lines = [
            "-- Database Sequence Creation Script",
            "-- Generated after frontend ID migration",
            "-- Run this script to create sequences for new ID generation",
            "",
            "USE [YourDatabaseName];  -- Update with actual database name",
            "GO",
            ""
        ]
        
        for table_name, config in self.TABLES_TO_MIGRATE.items():
            if table_name in self.migration_stats["results_by_table"]:
                migrated_count = self.migration_stats["results_by_table"][table_name]["migrated_count"]
                start_value = max(migrated_count + 1, 1)
                
                script_lines.extend([
                    f"-- Sequence for {table_name}",
                    f"CREATE SEQUENCE {table_name}_seq",
                    f"  START WITH {start_value}",
                    f"  INCREMENT BY 1",
                    f"  MINVALUE 1",
                    f"  NO MAXVALUE",
                    f"  NO CYCLE;",
                    ""
                ])
        
        return "\n".join(script_lines)


def main():
    """Main migration execution."""
    # Import configuration
    from migration_config import MigrationConfig
    
    # Validate configuration
    if not MigrationConfig.validate_config():
        return
    
    CONNECTION_STRING = MigrationConfig.get_connection_string()
    
    migrator = FrontendIDMigrator(CONNECTION_STRING)
    
    try:
        # Connect to database
        migrator.connect()
        
        # Run dry run first
        logger.info("Running dry run to preview changes...")
        success = migrator.run_migration(dry_run=True)
        
        if not success:
            logger.error("❌ Dry run failed, aborting migration")
            return
        
        # Ask user if they want to proceed with actual migration
        print("\n" + "="*60)
        response = input("Dry run completed. Run actual migration? (yes/no): ").lower().strip()
        
        if response in ['yes', 'y']:
            success = migrator.run_migration(dry_run=False)
            
            if success:
                # Generate sequence creation script
                sequence_script = migrator.generate_sequence_creation_script()
                
                script_filename = f"create_sequences_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
                with open(script_filename, 'w') as f:
                    f.write(sequence_script)
                
                logger.info(f"📄 Sequence creation script saved to: {script_filename}")
                logger.info("🎯 Next steps:")
                logger.info("  1. Review and run the sequence creation script")
                logger.info("  2. Update your ID_PATTERNS in id_generator.py")
                logger.info("  3. Deploy new sequence-based ID generator")
        else:
            logger.info("Migration cancelled by user")
            
    except Exception as e:
        logger.error(f"❌ Migration script failed: {e}")
        return


if __name__ == "__main__":
    main()