# Data Dictionary

This document defines the normalized database tables produced by the Project Argus pipeline.  All tables use `declaration_id` as the foreign key linking back to the source declaration.

## `declarant_profiles`

Parsed from **step_1**.  One row per declaration.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (unique, indexed) | NAZK declaration UUID |
| `firstname` | string | Declarant first name |
| `lastname` | string | Declarant last name |
| `middlename` | string | Declarant patronymic |
| `work_post` | string | Job title / position |
| `work_place` | string | Employing organization |
| `post_type` | string | Position type classification |
| `post_category` | string | Position category classification |

## `family_members`

Parsed from **step_2**.  One row per declared family member.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `member_id` | string | Internal member ID (used by ownership references) |
| `relation` | string | Relationship to declarant (e.g. "чоловік", "дружина", "син") |
| `firstname` | string | Family member first name |
| `lastname` | string | Family member last name |
| `middlename` | string | Family member patronymic |

## `real_estate_assets`

Parsed from **step_3**.  One row per (property x ownership right).

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `object_type` | string | Property type (apartment, house, land, etc.) |
| `other_object_type` | string | Custom type when `object_type` is "Інше" |
| `total_area` | numeric | Total area in square meters |
| `total_area_raw` | string | Original unparsed area value |
| `total_area_status` | string | Placeholder status if area was not a real number |
| `cost_assessment` | numeric | Assessed value (UAH) |
| `cost_assessment_raw` | string | Original unparsed cost value |
| `cost_assessment_status` | string | Placeholder status if cost was not a real number |
| `owning_date` | string | Date of acquisition |
| `right_belongs_raw` | string | Raw `rightBelongs` ID from the declaration |
| `right_belongs_resolved` | string | Resolved owner: "declarant", family label, "third_party", or "unknown:X" |
| `ownership_type` | string | Type of ownership right |
| `percent_ownership` | string | Ownership percentage if shared |
| `country` | string | Property country |
| `region` | string | Property region |
| `district` | string | Property district |
| `community` | string | Property community |
| `city` | string | Property city |
| `city_type` | string | City type classification |
| `raw_iteration` | string | Original iteration index from the declaration JSON |

## `vehicles`

Parsed from **step_6**.  One row per vehicle.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `object_type` | string | Vehicle type (car, motorcycle, boat, etc.) |
| `brand` | string | Vehicle brand / manufacturer |
| `model` | string | Vehicle model |
| `graduation_year` | int | Year of manufacture |
| `owning_date` | string | Date of acquisition |
| `cost_date` | numeric | Acquisition cost (UAH) |
| `ownership_type` | string | Type of ownership right |
| `right_belongs_resolved` | string | Resolved owner |
| `raw_iteration` | string | Original iteration index |

## `income_entries`

Parsed from **step_11**.  One row per income source.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `person_ref` | string | Internal person ID (declarant = "1", family members by step_2 ID) |
| `income_type` | string | Income category (salary, dividends, gifts, etc.) |
| `income_type_other` | string | Custom type when `income_type` is "Інше" |
| `amount` | numeric | Income amount (UAH unless otherwise indicated) |
| `amount_raw` | string | Original unparsed amount value |
| `amount_status` | string | Placeholder status if amount was not a real number |
| `source_name` | string | Name of income source organization |
| `source_code` | string | EDRPOU code of source organization |
| `source_type` | string | Source type classification |
| `raw_iteration` | string | Original iteration index |

## `monetary_assets`

Parsed from **step_12**.  One row per monetary holding.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `person_ref` | string | Internal person ID |
| `asset_type` | string | Asset type (cash, bank deposit, securities, crypto, etc.) |
| `currency_raw` | string | Original currency string from declaration |
| `currency_code` | string | Extracted ISO 4217 currency code (UAH, USD, EUR, etc.) |
| `amount` | numeric | Asset amount in stated currency |
| `amount_raw` | string | Original unparsed amount value |
| `organization` | string | Holding institution name |
| `organization_status` | string | Placeholder status if organization was not provided |
| `ownership_type` | string | Type of ownership right |
| `raw_iteration` | string | Original iteration index |

## `bank_accounts`

Parsed from **step_17**.  One row per account-owner combination.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `institution_name` | string | Bank / financial institution name |
| `institution_code` | string | Institution EDRPOU code |
| `account_owner_resolved` | string | Resolved account owner |
| `raw_iteration` | string | Original iteration index |

## `anomaly_scores`

Computed by the scoring pipeline.  One row per declaration.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment primary key |
| `declaration_id` | string (indexed) | Parent declaration UUID |
| `total_score` | numeric | Composite anomaly score (0.0 – 1.0) |
| `triggered_rules` | string | Comma-separated list of triggered rule names |
| `explanation_summary` | string | Human-readable summary of all triggered rules |
| `rule_details_json` | string | Full JSON array of per-rule results |

## Ownership Resolution

Fields named `right_belongs_resolved` and `account_owner_resolved` are produced by comparing the raw `rightBelongs` or `person_has_account` ID against a **family index** built from step_2:

- `"1"` → `"declarant"`
- ID matching a step_2 entry → `"relationship (Firstname Lastname)"`
- `"j"` → `"third_party"`
- Anything else → `"unknown:<raw_id>"`

## Placeholder Status Values

When a numeric or text field contains a Ukrainian bracketed placeholder instead of a real value, the corresponding `*_status` column records the category:

| Status | Meaning |
|--------|---------|
| `confidential` | Value marked as confidential information |
| `not_applicable` | Field is not applicable to this declaration |
| `unknown` | Value is unknown to the declarant |
| `family_no_info` | Declarant has no information about family member's value |
