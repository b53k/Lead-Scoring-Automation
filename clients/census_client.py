import requests

DEFAULT_TIMEOUT = 10

def _safe_get_json(url, timeout=DEFAULT_TIMEOUT):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list) or len(data) < 2:
            return None, "invalid_payload"

        return data, None

    except (requests.RequestException, ValueError) as e:
        return None, str(e)


def _to_int(value, default = None):
    try:
        if value in (None, "", "null"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default

def _to_float(value, default = None):
    try:
        if value in (None, "", "null"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_census_data(zip_code):
    population_url = f"https://api.census.gov/data/2020/dec/dhc?get=group(P1)&ucgid=860Z200US{zip_code}"
    employment_rate_url = f"https://api.census.gov/data/2024/acs/acs5/profile?get=group(DP03)&ucgid=860Z200US{zip_code}"
    occupancy_status_url = f"https://api.census.gov/data/2024/acs/acs5?get=group(B25002)&ucgid=860Z200US{zip_code}"

    result = {}
    errors = {}
    
    # Employment Profile
    employment_data, err = _safe_get_json(employment_rate_url)

    if err:
        errors['employment'] = err
    else:
        headers, values = employment_data[0], employment_data[1]
        row_employment = dict(zip(headers, values))

        result['employed_population'] = _to_int(row_employment.get('DP03_0004E'), 0)
        result['unemployed_population'] = _to_int(row_employment.get('DP03_0005E'), 0)
        result['unemployment_rate'] = _to_float(row_employment.get('DP03_0005PE'), 0.0)
        result['employment_rate'] = _to_float(row_employment.get('DP03_0004PE'), 0.0)
        result['median_household_income'] = _to_float(row_employment.get('DP03_0062E'), 0.0)

    # Occupancy
    occupancy_status_data, err = _safe_get_json(occupancy_status_url)

    if err:
        errors['occupancy'] = err
    else:
        headers, values = occupancy_status_data[0], occupancy_status_data[1]
        row_occupancy = dict(zip(headers, values))

        result['total_housing_units'] = _to_int(row_occupancy.get('B25002_001E'), 0)
        result['occupied_housing_units'] = _to_int(row_occupancy.get('B25002_002E'), 0)
        result['vacant_housing_units'] = _to_int(row_occupancy.get('B25002_003E'), 0)

        total = result['total_housing_units']
        occupied = result['occupied_housing_units']
        result['occupancy_rate'] = round((occupied / total) * 100, 2) if total > 0 else 0.0

    # Population
    population_data, err = _safe_get_json(population_url)

    if err:
        errors['population'] = err
    else:
        try:
            result['population'] = _to_int(population_data[1][2])
        except (IndexError, TypeError, ValueError):
            errors['population'] = "missing_population_field"

    return result, errors


def get_census_data_w_zipcode_fallback(zip_code):
    """
    Fallback to the nearest zip code if the zip code is not found.
    Try zipcode then +/- 1, +/-2.
    """
    
    base = int(zip_code[:5])
    last_error = None

    deltas = [0, -1, 1, -2, 2]
    for i, d in enumerate(deltas):
        candidate = str(base + d)
        if len(str(candidate)) != 5:
            candidate = '0' + candidate

        data, err = get_census_data(candidate)

        if data and not err:
            return data, candidate, err
        
        if i >= 0:
            print (f"Error getting census data for zipcode: {zip_code}. Trying {int(candidate)+deltas[i+1]}...")
        
        last_error = err
    
    return None, None, last_error

