import pytest
from app.normalization.edrpou_extractor import extract_edrpous, _is_valid_edrpou

def test_is_valid_edrpou():
    assert _is_valid_edrpou("12345678") == True
    assert _is_valid_edrpou("123") == True
    assert _is_valid_edrpou("0") == False
    assert _is_valid_edrpou("") == False
    assert _is_valid_edrpou(None) == False
    assert _is_valid_edrpou("123A") == False
    assert _is_valid_edrpou(" 12345678 ") == True

def test_extract_edrpous():
    data = {
        "data": {
            "step_1": {
                "data": {
                    "workPlaceEdrpou": "11111111"
                }
            },
            "step_11": {
                "isNotApplicable": False,
                "data": [
                    {
                        "sources": [
                            {"sourceuacompanycode": "22222222"},
                            {"sourceuacompanycode": "0"}
                        ]
                    },
                    {
                        "sources": [
                            {"sourceuacompanycode": " 33333333 "}
                        ]
                    }
                ]
            },
            "step_15": {
                "isNotApplicable": False,
                "data": [
                    {"emitentuacompanycode": "44444444"},
                    {"emitentuacompanycode": "invalid"}
                ]
            },
            "step_17": {
                "isNotApplicable": False,
                "data": [
                    {"establishmentuacompanycode": "55555555"},
                    {"establishmentuacompanycode": "55555555"}
                ]
            }
        }
    }
    
    extracted = extract_edrpous(data)
    
    assert extracted["employer_edrpou"] == "11111111"
    assert extracted["income_source_edrpous"] == ["22222222", "33333333"]
    assert extracted["securities_edrpous"] == ["44444444"]
    assert extracted["bank_edrpous"] == ["55555555"]

def test_extract_empty():
    extracted = extract_edrpous({})
    assert extracted["employer_edrpou"] is None
    assert extracted["income_source_edrpous"] == []
    
    extracted = extract_edrpous({"data": {"step_11": {"isNotApplicable": True}}})
    assert extracted["income_source_edrpous"] == []
