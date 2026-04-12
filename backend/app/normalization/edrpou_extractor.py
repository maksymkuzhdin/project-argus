"""
Project Argus — EDRPOU Extraction

Extracts EDRPOU codes from raw declaration JSONs for Prozorro enrichment.
"""

import logging

logger = logging.getLogger(__name__)

def _is_valid_edrpou(value: str | None) -> bool:
    if not value:
        return False
    s = str(value).strip()
    if not s or s == "0":
        return False
    if not s.isdigit():
        return False
    return True

def extract_edrpous(declaration_data: dict) -> dict:
    """Extract EDRPOU codes from a raw declaration.
    
    Returns:
        {
            "employer_edrpou": str | None,
            "income_source_edrpous": list[str],
            "securities_edrpous": list[str],
            "bank_edrpous": list[str],
        }
    """
    result = {
        "employer_edrpou": None,
        "income_source_edrpous": [],
        "securities_edrpous": [],
        "bank_edrpous": [],
    }

    try:
        data = declaration_data.get("data", {})
        if not isinstance(data, dict):
            return result
    except Exception as e:
        logger.warning(f"Error accessing declaration data: {e}")
        return result

    # 1. Employer EDRPOU (step 1)
    try:
        step1 = data.get("step_1", {})
        if isinstance(step1, dict):
            step1_data = step1.get("data", {})
            if isinstance(step1_data, dict):
                val = step1_data.get("workPlaceEdrpou")
                if _is_valid_edrpou(val):
                    result["employer_edrpou"] = str(val).strip()
    except Exception as e:
        logger.warning(f"Error extracting employer EDRPOU: {e}")

    # 2. Income sources (step 11)
    income_edrpous = set()
    try:
        step11 = data.get("step_11", {})
        if isinstance(step11, dict) and not step11.get("isNotApplicable"):
            step11_data = step11.get("data", [])
            
            # Handle dictionary case (if step11_data is a dict wrapped around the list, or nested)
            items = []
            if isinstance(step11_data, list):
                items = step11_data
            elif isinstance(step11_data, dict):
                items = step11_data.values()
                
            for item in items:
                if not isinstance(item, dict):
                    continue
                sources = item.get("sources", [])
                if isinstance(sources, list):
                    for source in sources:
                        if isinstance(source, dict):
                            val = source.get("sourceuacompanycode")
                            if _is_valid_edrpou(val):
                                income_edrpous.add(str(val).strip())
    except Exception as e:
        logger.warning(f"Error extracting income source EDRPOUs: {e}")
    result["income_source_edrpous"] = sorted(list(income_edrpous))

    # 3. Securities (step 15)
    securities_edrpous = set()
    try:
        step15 = data.get("step_15", {})
        if isinstance(step15, dict) and not step15.get("isNotApplicable"):
            step15_data = step15.get("data", [])
            items = []
            if isinstance(step15_data, list):
                items = step15_data
            elif isinstance(step15_data, dict):
                items = step15_data.values()
            
            for item in items:
                if not isinstance(item, dict):
                    continue
                val = item.get("emitentuacompanycode")
                if _is_valid_edrpou(val):
                    securities_edrpous.add(str(val).strip())
    except Exception as e:
        logger.warning(f"Error extracting securities EDRPOUs: {e}")
    result["securities_edrpous"] = sorted(list(securities_edrpous))

    # 4. Bank accounts (step 17)
    bank_edrpous = set()
    try:
        step17 = data.get("step_17", {})
        if isinstance(step17, dict) and not step17.get("isNotApplicable"):
            step17_data = step17.get("data", [])
            items = []
            if isinstance(step17_data, list):
                items = step17_data
            elif isinstance(step17_data, dict):
                items = step17_data.values()
                
            for item in items:
                if not isinstance(item, dict):
                    continue
                val = item.get("establishmentuacompanycode")
                if _is_valid_edrpou(val):
                    bank_edrpous.add(str(val).strip())
    except Exception as e:
        logger.warning(f"Error extracting bank EDRPOUs: {e}")
    result["bank_edrpous"] = sorted(list(bank_edrpous))

    return result
