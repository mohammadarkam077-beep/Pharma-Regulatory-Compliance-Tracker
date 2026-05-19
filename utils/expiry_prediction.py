from datetime import date

import pandas as pd


COUNTRY_VALIDITY_YEARS = {
    "india": 5,
    "usa": 5,
    "united states": 5,
    "us": 5,
    "eu": 5,
    "european union": 5,
    "uk": 5,
    "united kingdom": 5,
    "canada": 5,
    "australia": 5,
    "germany": 5,
    "france": 5,
    "brazil": 5,
    "mexico": 5,
    "south africa": 5,
}

DEFAULT_VALIDITY_YEARS = 5


def parse_date(value):
    if pd.isna(value) or value == "":
        return None

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None

    return parsed.date()


def add_years(base_date, years):
    try:
        return base_date.replace(year=base_date.year + years)
    except ValueError:
        return base_date.replace(month=2, day=28, year=base_date.year + years)


def validity_years_for(country):
    if not country:
        return DEFAULT_VALIDITY_YEARS

    return COUNTRY_VALIDITY_YEARS.get(
        str(country).strip().lower(),
        DEFAULT_VALIDITY_YEARS,
    )


def risk_from_days(days_to_expiry):
    if days_to_expiry is None:
        return "Unknown", 99, "Add a renewal due date or submission date."

    if days_to_expiry < 0:
        return "Expired", 1, "Renewal is overdue. Escalate immediately."

    if days_to_expiry <= 30:
        return "Critical", 2, "Prepare renewal package and submit urgently."

    if days_to_expiry <= 90:
        return "High", 3, "Start renewal dossier and authority planning."

    if days_to_expiry <= 180:
        return "Medium", 4, "Collect documents and confirm renewal strategy."

    return "Low", 5, "Monitor in the normal renewal cycle."


def predict_record_expiry(row, today=None):
    today = today or date.today()

    renewal_due_date = parse_date(row.get("renewal_due_date"))
    submission_date = parse_date(row.get("submission_date"))

    if renewal_due_date:
        predicted_expiry_date = renewal_due_date
        prediction_basis = "Renewal due date"
        confidence = "High"
    elif submission_date:
        validity_years = validity_years_for(row.get("country"))
        predicted_expiry_date = add_years(submission_date, validity_years)
        prediction_basis = f"Estimated from submission date plus {validity_years} years"
        confidence = "Medium"
    else:
        predicted_expiry_date = None
        prediction_basis = "Insufficient date data"
        confidence = "Low"

    days_to_expiry = (
        (predicted_expiry_date - today).days
        if predicted_expiry_date
        else None
    )
    risk_level, risk_rank, recommended_action = risk_from_days(days_to_expiry)

    return {
        "predicted_expiry_date": predicted_expiry_date,
        "days_to_expiry": days_to_expiry,
        "expiry_risk": risk_level,
        "risk_rank": risk_rank,
        "prediction_basis": prediction_basis,
        "confidence": confidence,
        "recommended_action": recommended_action,
    }


def build_expiry_predictions(submissions_df, today=None):
    if submissions_df.empty:
        return submissions_df.copy()

    predictions = submissions_df.apply(
        lambda row: predict_record_expiry(row, today=today),
        axis=1,
        result_type="expand",
    )

    result = pd.concat([submissions_df.reset_index(drop=True), predictions], axis=1)
    result = result.sort_values(
        by=["risk_rank", "predicted_expiry_date", "product_name"],
        na_position="last",
    )

    return result.drop(columns=["risk_rank"])
