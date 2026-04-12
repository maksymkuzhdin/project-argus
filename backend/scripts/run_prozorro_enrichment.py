#!/usr/bin/env python3
"""Project Argus - Run Prozorro enrichment for EDRPOU codes."""

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import DeclarantProfile, ProzorroEnrichment
from app.services.prozorro_enricher import enrich_edrpou

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argus.run_prozorro")

def parse_args():
    parser = argparse.ArgumentParser(description="Run Prozorro API enrichment.")
    parser.add_argument("--declarations-limit", type=int, default=0, help="Enrich EDRPOUs from N most recent un-enriched declarations.")
    parser.add_argument("--edrpou", type=str, help="Enrich a single EDRPOU directly and print result.")
    parser.add_argument("--force", action="store_true", help="Ignore the 7-day cache and re-fetch from Prozorro.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be enriched without hitting the API.")
    return parser.parse_args()


def main():
    args = parse_args()
    db = SessionLocal()
    
    try:
        if args.edrpou:
            logger.info(f"Enriching single EDRPOU: {args.edrpou}")
            if args.dry_run:
                logger.info("[DRY RUN] Would hit API for " + args.edrpou)
                return
            result = enrich_edrpou(args.edrpou, db, force=args.force)
            print("-" * 50)
            print("Result:", result)
            print("-" * 50)
            return

        limit = args.declarations_limit if args.declarations_limit > 0 else 100
        
        # Get declarations that have not been enriched completely or at all?
        # The script is supposed to "enrich EDRPOU codes from the N most recently ingested un-enriched declarations"
        # We'll just order by edrpou_extracted_at desc or something.
        logger.info(f"Loading up to {limit} declarations to enrich...")
        
        profiles = db.query(DeclarantProfile).filter(
            DeclarantProfile.edrpou_extracted_at.is_not(None)
        ).order_by(DeclarantProfile.edrpou_extracted_at.desc()).limit(limit).all()
        
        total_queried = 0
        hits = 0
        cr19_candidates = 0
        api_errors = 0
        
        seen_codes = set()
        
        for profile in profiles:
            employer = profile.employer_edrpou
            income_sources = set(profile.income_source_edrpous or [])
            securities = set(profile.securities_edrpous or [])
            
            codes_to_enrich = set()
            if employer: codes_to_enrich.add(employer)
            codes_to_enrich.update(income_sources)
            codes_to_enrich.update(securities)
            
            # Enrich all
            for code in codes_to_enrich:
                if code in seen_codes:
                    continue
                    
                seen_codes.add(code)
                total_queried += 1
                
                if args.dry_run:
                    logger.info(f"[DRY RUN] Would enrich {code}")
                    continue
                    
                res = enrich_edrpou(code, db, force=args.force)
                
                if res.get("enrichment_error"):
                    api_errors += 1
                    logger.error(f"Error enriching {code}: {res['enrichment_error']}")
                elif res.get("is_supplier"):
                    hits += 1
            
            # CR19 check
            if not args.dry_run and employer and income_sources:
                employer_record = db.query(ProzorroEnrichment).filter(ProzorroEnrichment.edrpou == employer).first()
                if employer_record:
                    for inc in income_sources:
                        inc_record = db.query(ProzorroEnrichment).filter(ProzorroEnrichment.edrpou == inc).first()
                        if inc_record and inc_record.is_supplier and inc_record.procuring_entity_edrpou:
                            if employer in inc_record.procuring_entity_edrpou:
                                logger.info(f"CR19 Candidate found! Declaration: {profile.declaration_id}, Employer: {employer}, Income: {inc}")
                                cr19_candidates += 1
                                break
                                
        if args.dry_run:
            logger.info(f"[DRY RUN] Unique EDRPOUs to query: {total_queried}")
            return
            
        logger.info(f"Done! EDRPOUs queried: {total_queried}, Prozorro hits: {hits}, API errors: {api_errors}, CR19 Candidates: {cr19_candidates}")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
