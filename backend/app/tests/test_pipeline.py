from decimal import Decimal
from app.services.pipeline import process_declaration

def test_process_declaration_cash_and_bank_separation():
    # A mock declaration with both cash and bank accounts in step_12
    raw = {
        "id": "doc-123",
        "data": {
            "step_1": {
                "data": {
                    "firstname": "John",
                    "lastname": "Doe",
                    "workPost": "Director",
                    "workPlace": "Agency"
                }
            },
            "step_12": {
                "isNotApplicable": 0,
                "data": [
                    {
                        "objectType": "Готівкові кошти",
                        "sizeAssets": "100000",
                        "assetsCurrency": "1" # UAH
                    },
                    {
                        "objectType": "Кошти, розміщені на банківських рахунках",
                        "sizeAssets": "50000",
                        "assetsCurrency": "1" # UAH
                    },
                    {
                        "objectType": "Внески до кредитних спілок та інших небанківських фінансових установ",
                        "sizeAssets": "25000",
                        "assetsCurrency": "1" # UAH
                    },
                    {
                        "objectType": "Криптовалюта",
                        "sizeAssets": "5000",
                        "assetsCurrency": "2" # USD
                    }
                ]
            }
        }
    }

    # Processing the declaration
    summary = process_declaration(raw)

    # 100,000 cash vs 75,000 bank => total monetary assets = 175,000 (Crypto is not counted in cash/bank, but is in total assets currently? Total monetary is sum_amounts(monetary). Wait, _sum_amounts(monetary) will sum ALL monetary assets, including crypto: 100k + 50k + 25k + 5k = 180,000.
    assert summary["total_assets"] == "180000"
    
    # Let's check the score. 
    # The actual cash=100k, bank=75k. 
    # cash_to_bank_ratio rule flags if cash > 0.8 * total_liquid (cash+bank).
    # 0.8 * 175,000 = 140,000. 
    # Our cash is 100,000, which is < 140,000, so it should NOT be flagged!
    assert "cash_to_bank_ratio" not in summary["triggered_rules"]

def test_process_declaration_cash_heavy():
    # A mock declaration with mostly cash
    raw = {
        "id": "doc-123",
        "data": {
            "step_12": {
                "isNotApplicable": 0,
                "data": [
                    {
                        "objectType": "Готівкові кошти",
                        "sizeAssets": "200000",
                        "assetsCurrency": "1" # UAH
                    },
                    {
                        "objectType": "Кошти, розміщені на банківських рахунках",
                        "sizeAssets": "10000",
                        "assetsCurrency": "1" # UAH
                    }
                ]
            }
        }
    }

    summary = process_declaration(raw)

    # Cash=200k, bank=10k. 
    # Cash is > 80% of (cash+bank) => 200k / 210k = 95%.
    # Should flag!
    assert "cash_to_bank_ratio" in summary["triggered_rules"]
