import logging
import time
from datetime import datetime, timezone, timedelta
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.db.models import ProzorroEnrichment, DeclarantProfile

logger = logging.getLogger(__name__)

API_BASE_URL = "https://public-api.prozorro.gov.ua/api/2.5/contracts"
CACHE_EXPIRY_DAYS = 7


def _fetch_prozorro_contracts(edrpou: str):
    """Fetch all pages of contracts for a given supplier EDRPOU."""
    url = f"{API_BASE_URL}?supplier_identifier_id={edrpou}"
    contracts = []
    
    with httpx.Client(timeout=10.0) as client:
        for page in range(50):
            try:
                response = client.get(url)
            except httpx.RequestError as exc:
                return contracts, f"Request error: {exc}"
                
            if response.status_code == 429:
                logger.info(f"Rate limited (429) for {edrpou}. Sleeping 10s...")
                time.sleep(10)
                try:
                    response = client.get(url)
                except httpx.RequestError as exc:
                    return contracts, f"Request error after retry: {exc}"
            
            if response.status_code != 200:
                if response.status_code == 404:
                    return contracts, None # No contracts found is not an error
                return contracts, f"HTTP {response.status_code}: {response.text}"
                
            data = response.json()
            items = data.get("data", [])
            contracts.extend(items)
            
            next_page = data.get("next_page", {}).get("uri")
            if not next_page or not items:
                break
                
            url = next_page
            time.sleep(0.5)

    return contracts, None


def enrich_edrpou(edrpou: str, db: Session, force: bool = False) -> dict:
    """Enrich an EDRPOU code, returning the DB record dict.
    
    Uses cache if refreshed within 7 days, unless force=True.
    """
    if not edrpou or not edrpou.isdigit():
        return {}
        
    edrpou = edrpou.strip()
    
    # Check cache
    existing = db.query(ProzorroEnrichment).filter(ProzorroEnrichment.edrpou == edrpou).first()
    now_utc = datetime.now(timezone.utc)
    
    if not force and existing and existing.enriched_at:
        age = now_utc - existing.enriched_at.replace(tzinfo=timezone.utc)
        if age < timedelta(days=CACHE_EXPIRY_DAYS) and not existing.enrichment_error:
            # Refresh the row just in case we need it as dict
            return {
                "edrpou": existing.edrpou,
                "is_supplier": existing.is_supplier,
                "contract_count": existing.contract_count,
                "total_value_uah": float(existing.total_value_uah) if existing.total_value_uah else 0.0,
                "most_recent_contract_date": existing.most_recent_contract_date.isoformat() if existing.most_recent_contract_date else None,
                "procuring_entity_edrpou": existing.procuring_entity_edrpou,
            }

    # Fetch from API
    logger.info(f"Fetching Prozorro data for EDRPOU {edrpou}")
    raw_contracts, error_msg = _fetch_prozorro_contracts(edrpou)
    
    # Parse results
    is_supplier = False
    contract_count = 0
    total_uah = 0.0
    most_recent_date = None
    buyers = set()
    
    if raw_contracts:
        is_supplier = True
        contract_count = len(raw_contracts)
        
        for c in raw_contracts:
            val_obj = c.get("value", {})
            currency = val_obj.get("currency")
            if currency == "UAH":
                amt = val_obj.get("amountNet") or val_obj.get("amount", 0)
                try:
                    total_uah += float(amt)
                except (ValueError, TypeError):
                    pass
                    
            date_signed = c.get("dateSigned")
            if date_signed:
                try:
                    parsed_date = datetime.fromisoformat(date_signed.replace("Z", "+00:00")).date()
                    if most_recent_date is None or parsed_date > most_recent_date:
                        most_recent_date = parsed_date
                except ValueError:
                    pass
                    
            # Procuring entities can be a list or a single object. API docs usually put it under 'procuringEntity'
            # but occasionally it's part of 'buyers'. Let's check both just in case, but standard is 'procuringEntity'.
            # It's not a full tender object though, this is a contract object.
            # Usually: extracting procuringEntity.identifier.id
            ent = c.get("procuringEntity")
            if isinstance(ent, dict):
                buyer_id = ent.get("identifier", {}).get("id")
                if buyer_id:
                    buyers.add(str(buyer_id))
            
            # If standard API places it inside 'buyers' list
            for buyer in c.get("buyers", []):
                if isinstance(buyer, dict):
                    buyer_id = buyer.get("identifier", {}).get("id")
                    if buyer_id:
                        buyers.add(str(buyer_id))
    
    values = {
        "edrpou": edrpou,
        "is_supplier": is_supplier,
        "contract_count": contract_count,
        "total_value_uah": total_uah,
        "most_recent_contract_date": most_recent_date,
        "procuring_entity_edrpou": list(buyers),
        "enriched_at": now_utc,
        "enrichment_error": error_msg,
    }
    
    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
    else:
        new_record = ProzorroEnrichment(**values)
        db.add(new_record)
        
    db.commit()
    
    return values


def enrich_declaration_edrpous(declaration_id: str, db: Session, force: bool = False):
    """Enrich all EDRPOU codes stored for a given declaration."""
    profile = db.query(DeclarantProfile).filter(DeclarantProfile.declaration_id == declaration_id).first()
    if not profile:
        return
        
    codes = set()
    if profile.employer_edrpou:
        codes.add(profile.employer_edrpou)
        
    if profile.income_source_edrpous:
        for code in profile.income_source_edrpous:
            codes.add(code)
            
    if profile.securities_edrpous:
        for code in profile.securities_edrpous:
            codes.add(code)
            
    for code in codes:
        enrich_edrpou(code, db, force=force)
