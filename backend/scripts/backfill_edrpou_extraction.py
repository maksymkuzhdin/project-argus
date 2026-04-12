#!/usr/bin/env python3
"""Project Argus - Backfill EDRPOU extraction for existing declarations.

Reads raw JSON declarations for all records where edrpou_extracted_at IS NULL,
extracts the EDRPOU codes, and updates the declarant_profiles table.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy.orm import Session
from app.db.models import DeclarantProfile
from app.db.session import SessionLocal
from app.normalization.edrpou_extractor import extract_edrpous
from app.ingestion.save_raw import load_declaration, declaration_exists, declaration_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argus.backfill_edrpou")


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill EDRPOU codes from raw JSON.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of records to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Commit batch size.")
    return parser.parse_args()


def main():
    args = parse_args()
    db = SessionLocal()
    
    try:
        query = db.query(DeclarantProfile).filter(DeclarantProfile.edrpou_extracted_at.is_(None))
        if args.limit > 0:
            query = query.limit(args.limit)
            
        profiles = query.all()
        logger.info(f"Found {len(profiles)} profiles needing EDRPOU extraction.")
        
        resolved_count = 0
        empty_count = 0
        processed_count = 0
        
        for profile in profiles:
            doc_id = profile.declaration_id
            year = str(profile.declaration_year) if profile.declaration_year else "unknown"
            
            # Find the raw json. If it's stored under another year folder, we might need to search, 
            # but usually it's under year
            if not declaration_exists(doc_id, year):
                # Try finding it globally
                found = False
                base_dir = Path("data/raw")
                if base_dir.exists():
                    for match in base_dir.rglob(f"declaration_{doc_id}.json"):
                        path = match
                        found = True
                        break
                if not found:
                    logger.warning(f"Raw JSON not found for declaration {doc_id}")
                    # Still mark it as extracted to avoid infinite loop
                    profile.edrpou_extracted_at = datetime.now(timezone.utc)
                    continue
            else:
                path = declaration_path(doc_id, year)
                
            try:
                raw_data = load_declaration(path)
                extracted = extract_edrpous(raw_data)
                
                profile.employer_edrpou = extracted.get("employer_edrpou")
                profile.income_source_edrpous = extracted.get("income_source_edrpous", [])
                profile.securities_edrpous = extracted.get("securities_edrpous", [])
                profile.bank_edrpous = extracted.get("bank_edrpous", [])
                profile.edrpou_extracted_at = datetime.now(timezone.utc)
                
                if profile.employer_edrpou:
                    resolved_count += 1
                else:
                    empty_count += 1
                    
                processed_count += 1
                
                if args.batch_size > 0 and processed_count % args.batch_size == 0:
                    db.commit()
                    logger.info(f"Processed {processed_count} records...")
                    
            except Exception as e:
                logger.error(f"Error processing {doc_id}: {e}")
                
        db.commit()
        logger.info(f"Backfill complete! Processed: {processed_count}. Total resolved employer EDRPOUs: {resolved_count}, Empty employer EDRPOUs: {empty_count}.")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
