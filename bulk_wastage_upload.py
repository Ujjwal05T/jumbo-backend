#!/usr/bin/env python3
"""
Bulk Wastage Upload Script
Reads CSV file and creates wastage inventory items via API calls
"""

import csv
import requests
import json
import sys
import os
from typing import Dict, List, Optional
import time
from dataclasses import dataclass

# Add the backend directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'jumbo-backend'))

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models import PaperMaster

@dataclass
class CSVRow:
    reel_no: str
    width_inches: float
    gsm: int
    bf: float  # Brightness Factor
    shade: str
    weight_kg: float

class WastageUploader:
    def __init__(self, api_base_url: str = "http://localhost:8000/api"):
        self.api_base_url = api_base_url
        self.db = SessionLocal()
        self.paper_cache = {}  # Cache for paper lookups
        self.success_count = 0
        self.error_count = 0
        self.errors = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def get_paper_id(self, gsm: int, bf: float, shade: str) -> Optional[str]:
        """Find paper_id by GSM and shade"""
        cache_key = f"{gsm}_{bf}_{shade}"

        # Check cache first
        if cache_key in self.paper_cache:
            return self.paper_cache[cache_key]

        # Query database
        paper = self.db.query(PaperMaster).filter(
            PaperMaster.gsm == gsm,
            PaperMaster.bf == bf,
            PaperMaster.shade.ilike(f"%{shade}%"),  # Case-insensitive partial match
            PaperMaster.status == "active"
        ).first()

        if paper:
            paper_id = str(paper.id)
            self.paper_cache[cache_key] = paper_id
            return paper_id

        # Cache the miss too
        self.paper_cache[cache_key] = None
        return None

    def parse_csv_row(self, row: Dict[str, str]) -> Optional[CSVRow]:
        """Parse and validate CSV row"""
        try:
            # Handle different possible column names for reel number
            reel_no = row.get('REEL NO', row.get('reel_no', row.get('reel no', ''))).strip()

            # Try to get width_inches from different columns
            width_inches = None
            for col in ['SIZE', 'size', 'width_inches', 'size(width inches)', 'width']:
                if col in row and row[col].strip():
                    try:
                        width_inches = float(row[col].strip())
                        break
                    except ValueError:
                        continue

            if width_inches is None:
                raise ValueError("No valid width_inches found")

            # Handle GSM column
            gsm = int(row.get('GSM', row.get('gsm', '0')).strip())

            # Handle BF column
            bf = float(row.get('BF', row.get('bf', '0')).strip())

            # Handle shade column
            shade = row.get('SHADE', row.get('shade', '')).strip()

            # Weight might be optional
            weight_kg = 0.0
            weight_str = row.get('WEIGHT', row.get('weight', row.get('weight_kg', ''))).strip()
            if weight_str:
                try:
                    weight_kg = float(weight_str)
                except ValueError:
                    weight_kg = 0.0

            return CSVRow(
                reel_no=reel_no,
                width_inches=width_inches,
                gsm=gsm,
                bf=bf,
                shade=shade,
                weight_kg=weight_kg
            )
        except Exception as e:
            print(f"Error parsing row: {e}")
            print(f"Row data: {row}")
            return None

    def create_wastage_item(self, csv_row: CSVRow) -> bool:
        """Create a single wastage item via API"""
        try:
            # Get paper_id
            paper_id = self.get_paper_id(csv_row.gsm, csv_row.bf, csv_row.shade)
            if not paper_id:
                error_msg = f"Paper not found for GSM: {csv_row.gsm}, BF: {csv_row.bf}, Shade: {csv_row.shade}"
                self.errors.append(error_msg)
                print(f"❌ {error_msg}")
                return False

            # Prepare API payload
            payload = {
                "width_inches": csv_row.width_inches,
                "paper_id": paper_id,
                "status": "available"
            }

            # Add optional fields
            if csv_row.weight_kg > 0:
                payload["weight_kg"] = csv_row.weight_kg

            if csv_row.reel_no:
                payload["reel_no"] = csv_row.reel_no

            # Make API call
            response = requests.post(
                f"{self.api_base_url}/wastage",
                json=payload,
                headers={
                    'Content-Type': 'application/json',
                    'ngrok-skip-browser-warning': 'true'
                },
                timeout=30
            )

            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                print(f"✅ Created wastage item: {result.get('frontend_id', 'N/A')} - {csv_row.width_inches}\" GSM:{csv_row.gsm}")
                return True
            else:
                error_msg = f"API error ({response.status_code}): {response.text}"
                self.errors.append(error_msg)
                print(f"❌ {error_msg}")
                return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {e}"
            self.errors.append(error_msg)
            print(f"❌ {error_msg}")
            return False
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            self.errors.append(error_msg)
            print(f"❌ {error_msg}")
            return False

    def upload_from_csv(self, csv_file_path: str, delay_seconds: float = 0.1):
        """Upload all wastage items from CSV file"""
        print(f"📁 Reading CSV file: {csv_file_path}")

        if not os.path.exists(csv_file_path):
            print(f"❌ File not found: {csv_file_path}")
            return

        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Try to detect delimiter
                sample = file.read(1024)
                file.seek(0)

                delimiter = ','
                if ';' in sample and sample.count(';') > sample.count(','):
                    delimiter = ';'

                reader = csv.DictReader(file, delimiter=delimiter)
                rows = list(reader)

                print(f"📊 Found {len(rows)} rows in CSV")
                print(f"📋 Columns: {', '.join(reader.fieldnames)}")
                print(f"🔄 Starting upload with {delay_seconds}s delay between requests...")
                print("-" * 60)

                for i, row in enumerate(rows, 1):
                    print(f"[{i}/{len(rows)}] Processing row...")

                    # Parse CSV row
                    csv_row = self.parse_csv_row(row)
                    if not csv_row:
                        self.error_count += 1
                        continue

                    # Create wastage item
                    if self.create_wastage_item(csv_row):
                        self.success_count += 1
                    else:
                        self.error_count += 1

                    # Add delay between requests
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)

                # Print summary
                print("-" * 60)
                print(f"📈 Upload Summary:")
                print(f"   ✅ Successful: {self.success_count}")
                print(f"   ❌ Failed: {self.error_count}")
                print(f"   📊 Total: {len(rows)}")

                if self.errors:
                    print(f"\n🚨 Errors encountered:")
                    for error in self.errors[-10:]:  # Show last 10 errors
                        print(f"   • {error}")

                    if len(self.errors) > 10:
                        print(f"   ... and {len(self.errors) - 10} more errors")

        except Exception as e:
            print(f"❌ Error reading CSV file: {e}")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python bulk_wastage_upload.py <csv_file_path> [api_url] [delay_seconds]")
        print("Example: python bulk_wastage_upload.py wastage_data.csv http://localhost:8000/api 0.1")
        sys.exit(1)

    csv_file_path = sys.argv[1]
    api_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000/api"
    delay_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1

    print("🚀 Bulk Wastage Upload Script")
    print(f"📁 CSV File: {csv_file_path}")
    print(f"🌐 API URL: {api_url}")
    print(f"⏱️ Delay: {delay_seconds}s between requests")
    print("=" * 60)

    with WastageUploader(api_url) as uploader:
        uploader.upload_from_csv(csv_file_path, delay_seconds)

if __name__ == "__main__":
    main()