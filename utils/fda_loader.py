import requests
from datetime import datetime, timedelta
from sqlalchemy import text

from utils.sop_engine import get_matching_policies, assign_policy_to_submission

FDA_LABEL_ENDPOINT = "https://api.fda.gov/drug/label.json"
DEFAULT_PRODUCT_TYPE = "Pharmaceutical"
DEFAULT_SUBMISSION_TYPE = "New Registration"
DEFAULT_SUBMISSION_STATUS = "Pending"
DEFAULT_SUBMISSION_RENEWAL_DAYS = 30


def _first_value(value):
    if isinstance(value, list) and value:
        return value[0]
    return value


def _guess_product_type(openfda):
    product_type = _first_value(openfda.get("product_type")) if openfda else None
    if not product_type:
        return DEFAULT_PRODUCT_TYPE
    lower = str(product_type).lower()
    if "device" in lower:
        return "Medical Device"
    if "biologic" in lower:
        return "Biologics"
    if "combination" in lower:
        return "Combination Product"
    return DEFAULT_PRODUCT_TYPE


def _normalize_string(value):
    if isinstance(value, list):
        value = _first_value(value)
    if value is None:
        return None
    return str(value).strip()


def _extract_product_fields(record):
    openfda = record.get("openfda", {}) or {}
    product_name = _normalize_string(openfda.get("brand_name") or openfda.get("generic_name") or openfda.get("substance_name") or record.get("purpose") or record.get("indications_and_usage"))
    dosage_form = _normalize_string(openfda.get("dosage_form"))
    registration_no = _normalize_string(_first_value(openfda.get("application_number")) or _first_value(openfda.get("set_id")))
    product_type = _guess_product_type(openfda)
    country = "USA"
    strength = _normalize_string(_first_value(openfda.get("route")) or _first_value(openfda.get("pharm_class_cs")))

    return {
        "product_name": product_name or "FDA Product",
        "dosage_form": dosage_form,
        "strength": strength,
        "country": country,
        "registration_no": registration_no,
        "product_type": product_type,
    }


def _build_fda_search_request(search_query):
    search_query = str(search_query).strip()
    if not search_query:
        return None

    return f"openfda.brand_name:{search_query} OR openfda.generic_name:{search_query} OR openfda.substance_name:{search_query}"


def _perform_fda_request(session, params):
    headers = {
        "User-Agent": "RegulatoryComplianceTracker/1.0 (+https://example.com)"
    }
    response = session.get(FDA_LABEL_ENDPOINT, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()


def _extract_error_message(response):
    try:
        error_payload = response.json()
        if isinstance(error_payload, dict) and "error" in error_payload:
            return error_payload["error"].get("message") or str(error_payload["error"])
    except Exception:
        pass
    return None


def fetch_fda_drug_labels(limit=20, search_query=None, proxy_mode="auto"):
    params = {"limit": min(max(int(limit), 1), 50)}
    query = _build_fda_search_request(search_query)
    if query:
        params["search"] = query

    with requests.Session() as session:
        session.trust_env = proxy_mode == "auto"
        try:
            payload = _perform_fda_request(session, params)
        except requests.exceptions.ProxyError:
            if proxy_mode == "auto":
                session.trust_env = False
                payload = _perform_fda_request(session, params)
            else:
                raise
        except requests.exceptions.HTTPError as http_err:
            response = http_err.response
            status = response.status_code if response is not None else None
            if status and status >= 500 and query:
                # Retry using singular query fields when FDA service returns 500 on broad search.
                fallback_results = []
                for field in ["openfda.brand_name", "openfda.generic_name", "openfda.substance_name"]:
                    params["search"] = f"{field}:{search_query}"
                    try:
                        payload = _perform_fda_request(session, params)
                        fallback_results = payload.get("results", [])
                        if fallback_results:
                            break
                    except requests.exceptions.HTTPError:
                        continue
                if not fallback_results:
                    raise
                return [_extract_product_fields(item) for item in fallback_results]
            raise

        results = payload.get("results", [])
        return [_extract_product_fields(item) for item in results]


def load_sample_fda_products():
    return [
        {
            "product_name": "Aspirin 100 mg",
            "dosage_form": "Tablet",
            "strength": "100 mg",
            "country": "USA",
            "registration_no": "ANDA123456",
            "product_type": "Pharmaceutical",
        },
        {
            "product_name": "Aspirin 325 mg",
            "dosage_form": "Tablet",
            "strength": "325 mg",
            "country": "USA",
            "registration_no": "ANDA654321",
            "product_type": "Pharmaceutical",
        },
    ]


def _submission_exists(engine, product_id, submission_type):
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT submission_id FROM submissions WHERE product_id = :product_id AND submission_type = :submission_type"),
            {"product_id": product_id, "submission_type": submission_type},
        ).fetchone()
        return existing is not None


def create_submission_for_product(engine, product_id, submission_type=None, submission_status=None, renewal_due_days=None):
    submission_type = submission_type or DEFAULT_SUBMISSION_TYPE
    submission_status = submission_status or DEFAULT_SUBMISSION_STATUS
    renewal_due_days = renewal_due_days if renewal_due_days is not None else DEFAULT_SUBMISSION_RENEWAL_DAYS

    if _submission_exists(engine, product_id, submission_type):
        return None

    submission_date = datetime.now().date().isoformat()
    renewal_due_date = (datetime.now() + timedelta(days=renewal_due_days)).date().isoformat()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "INSERT INTO submissions (product_id, submission_type, submission_status, submission_date, renewal_due_date) VALUES (:product_id, :submission_type, :submission_status, :submission_date, :renewal_due_date)"
            ),
            {
                "product_id": product_id,
                "submission_type": submission_type,
                "submission_status": submission_status,
                "submission_date": submission_date,
                "renewal_due_date": renewal_due_date,
            },
        )
        conn.commit()
        return result.lastrowid


def import_fda_products(engine, product_rows, create_submissions=False, create_workflow=False):
    inserted = 0
    updated = 0
    inserted_product_ids = []

    with engine.connect() as conn:
        for row in product_rows:
            if not row.get("registration_no"):
                continue
            existing = conn.execute(
                text("SELECT product_id FROM products WHERE registration_no = :registration_no"),
                {"registration_no": row["registration_no"]},
            ).fetchone()
            if existing:
                conn.execute(
                    text(
                        "UPDATE products SET product_name = :product_name, dosage_form = :dosage_form, strength = :strength, country = :country, product_type = :product_type WHERE registration_no = :registration_no"
                    ),
                    row,
                )
                updated += 1
            else:
                result = conn.execute(
                    text(
                        "INSERT INTO products (product_name, dosage_form, strength, country, registration_no, product_type) VALUES (:product_name, :dosage_form, :strength, :country, :registration_no, :product_type)"
                    ),
                    row,
                )
                inserted += 1
                inserted_product_ids.append(result.lastrowid)
        conn.commit()

    created_submissions = 0
    created_workflows = 0

    if create_submissions or create_workflow:
        for product_id in inserted_product_ids:
            submission_id = None
            if create_submissions:
                submission_id = create_submission_for_product(engine, product_id)
                if submission_id:
                    created_submissions += 1
            if create_workflow:
                if submission_id is None:
                    submission_id = create_submission_for_product(engine, product_id)
                    if submission_id:
                        created_submissions += 1
                if submission_id is not None:
                    with engine.connect() as conn:
                        product = conn.execute(
                            text("SELECT product_type, country FROM products WHERE product_id = :product_id"),
                            {"product_id": product_id},
                        ).fetchone()
                        if product:
                            product_type, country = product
                            policies = get_matching_policies(engine, product_type, country, DEFAULT_SUBMISSION_TYPE)
                            if policies.empty:
                                policies = get_matching_policies(engine, None, None, None)
                            for _, policy in policies.iterrows():
                                assign_policy_to_submission(engine, int(policy["policy_id"]), submission_id, product_id)
                            created_workflows += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "created_submissions": created_submissions,
        "created_workflows": created_workflows,
    }
