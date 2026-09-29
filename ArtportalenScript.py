import os
import sys
from datetime import datetime

import pandas as pd
import requests
import urllib3


# ============================================================
# KONFIGURATION
# ============================================================

# API-nyckeln bör inte skrivas direkt i Pythonfilen.
# Ange den i PowerShell före körning:
# $env:ARTPORTALEN_API_KEY = "DIN_API_NYCKEL"

API_KEY = "6fbaf266e3e142449a0976329ef0736c"

EXCELFIL = (
    r"MånX.xlsx"
)

API_URL = (
    "https://api.artdatabanken.se/"
    "species-observation-system/v1/"
    "Observations/Search"
)

REQUESTING_SYSTEM = "SimonFors-ManX"

COUNTY_FEATURE_ID = "12"  # Skåne

BIRD_TAXON_ID = 4000104  # Aves

PAGE_SIZE = 1000

# Tillfällig lösning på SSL-inspektionen i företagsmiljön.
# I en slutlig lösning bör verify=False ersättas med rätt certifikat.
VERIFY_SSL = False


# ============================================================
# HJÄLPFUNKTIONER
# ============================================================

def scientific_name_to_species_level(scientific_name):
    """
    Normaliserar ett vetenskapligt namn till artnivå.

    Exempel:
        Corvus corone cornix -> Corvus corone
        Luscinia svecica svecica -> Luscinia svecica
        Phylloscopus collybita tristis -> Phylloscopus collybita
        Cygnus olor -> Cygnus olor

    Returnerar None för osäkra eller sammansatta taxon.
    """

    if scientific_name is None:
        return None

    name = str(scientific_name).strip()

    if not name:
        return None

    lower_name = name.lower()

    excluded_patterns = [
        " x ",
        " × ",
        " hybrid",
        " sp.",
        " spp.",
        " cf.",
        " aff."
    ]

    if any(pattern in lower_name for pattern in excluded_patterns):
        return None

    parts = name.split()

    if len(parts) < 2:
        return None

    genus = parts[0].strip()
    species = parts[1].strip()

    invalid_species_values = {
        "sp",
        "sp.",
        "spp",
        "spp.",
        "x",
        "×"
    }

    if species.lower() in invalid_species_values:
        return None

    return f"{genus} {species}"


def is_unambiguous_observation(vernacular_name, scientific_name):
    """
    Tar bort observationer som inte avser ett entydigt taxon.

    Exempel som filtreras bort:
        stäpphök/ängshök
        obestämd gås
        hybrider
        taxa på formen 'sp.'
    """

    common_name = str(vernacular_name or "").strip().lower()
    scientific_name = str(scientific_name or "").strip().lower()

    if not common_name or not scientific_name:
        return False

    excluded_common_name_patterns = [
        "/",
        "obestämd",
        "obestämda",
        "hybrid"
    ]

    if any(
        pattern in common_name
        for pattern in excluded_common_name_patterns
    ):
        return False

    if "domesticated populations" in scientific_name:
        return False
    return scientific_name_to_species_level(scientific_name) is not None



def safe_nested_get(data, *keys):
    """
    Hämtar ett värde säkert ur en nästlad dictionary.
    """

    current = data

    for key in keys:
        if not isinstance(current, dict):
            return None

        current = current.get(key)

        if current is None:
            return None

    return current


def find_month_list_column(dataframe):
    """
    Identifierar kolumnen som innehåller artnamn och vetenskapligt namn.
    Detta undviker beroendet av det märkliga kolumnnamnet
    'Summa\\xa0\\xa02161Artnamn'.
    """

    for column in dataframe.columns:
        normalized = (
            str(column)
            .replace("\xa0", " ")
            .lower()
            .strip()
        )

        if "artnamn" in normalized:
            return column

    raise ValueError(
        "Kunde inte hitta kolumnen med artnamn i MånX-filen."
    )


# ============================================================
# HÄMTA DAGENS OBSERVATIONER FRÅN ARTPORTALEN
# ============================================================

def fetch_observations():
    """
    Hämtar samtliga fågelobservationer i Skåne för dagens datum.
    Funktionen hanterar automatiskt fler än 1000 observationer.
    """

    if not API_KEY:
        print("Fel: Miljövariabeln ARTPORTALEN_API_KEY saknas.")
        print()
        print("Ange API-nyckeln i PowerShell med:")
        print('$env:ARTPORTALEN_API_KEY = "DIN_API_NYCKEL"')
        sys.exit(1)

    today = datetime.now().astimezone().date().isoformat()

    headers = {
        "Ocp-Apim-Subscription-Key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requesting-System": REQUESTING_SYSTEM
    }

    search_filter = {
        "date": {
            "startDate": f"{today}T00:00:00",
            "endDate": f"{today}T23:59:59",
            "dateFilterType": "OnlyStartDate"
        },
        "taxon": {
            "ids": [BIRD_TAXON_ID],
            "includeUnderlyingTaxa": True
        },
        "geographics": {
            "areas": [
                {
                    "areaType": "County",
                    "featureId": COUNTY_FEATURE_ID
                }
            ]
        },
        "occurrenceStatus": "Present",
        "output": {
            "fields": [
                "event.startDate",
                "event.endDate",
                "location.locality",
                "location.municipality",
                "location.county",
                "location.decimalLatitude",
                "location.decimalLongitude",
                "location.coordinateUncertaintyInMeters",
                "taxon.id",
                "taxon.scientificName",
                "taxon.vernacularName",
                "taxon.attributes.organismGroup",
                "occurrence.individualCount",
                "occurrence.organismQuantity",
                "occurrence.recordedBy",
                "occurrence.reportedBy",
                "occurrence.reportedDate",
                "occurrence.occurrenceId",
                "occurrence.url"
            ]
        }
    }

    all_records = []
    skip = 0
    total_count = None

    while total_count is None or skip < total_count:
        params = {
            "skip": skip,
            "take": PAGE_SIZE,
            "translationCultureCode": "sv-SE",
            "sensitiveObservations": "false",
            "outputFormat": "JSON",
            "validateSearchFilter": "true"
        }

        try:
            response = requests.post(
                url=API_URL,
                headers=headers,
                params=params,
                json=search_filter,
                verify=VERIFY_SSL,
                timeout=60
            )

            response.raise_for_status()

        except requests.exceptions.SSLError as error:
            print("SSL-fel:")
            print(error)
            sys.exit(1)

        except requests.exceptions.Timeout:
            print("Fel: API-anropet tog för lång tid.")
            sys.exit(1)

        except requests.exceptions.ConnectionError as error:
            print("Anslutningsfel:")
            print(error)
            sys.exit(1)

        except requests.exceptions.HTTPError:
            print("API-anropet misslyckades.")
            print("Statuskod:", response.status_code)
            print(response.text[:3000])
            sys.exit(1)

        except requests.exceptions.RequestException as error:
            print("Fel vid API-anrop:")
            print(error)
            sys.exit(1)

        try:
            result = response.json()

        except ValueError:
            print("API:t returnerade inte giltig JSON.")
            print(response.text[:3000])
            sys.exit(1)

        page_records = result.get("records", [])
        total_count = result.get("totalCount", 0)

        all_records.extend(page_records)

        if not page_records:
            break

        skip += len(page_records)

    print("Statuskod: 200")
    print("Datum:", today)
    print("Totalt antal matchande observationer:", total_count)
    print("Antal hämtade observationer:", len(all_records))

    return all_records


# ============================================================
# OMVANDLA OBSERVATIONER TILL DATAFRAME
# ============================================================

def observations_to_dataframe(records):
    """
    Omvandlar API-resultatet till en DataFrame och skapar
    en jämförelsenyckel på vetenskaplig artnivå.
    """

    rows = []

    for observation in records:
        vernacular_name = safe_nested_get(
            observation,
            "taxon",
            "vernacularName"
        )

        scientific_name = safe_nested_get(
            observation,
            "taxon",
            "scientificName"
        )

        species_level = scientific_name_to_species_level(
            scientific_name
        )

        rows.append({
            "Artnamn": vernacular_name,
            "Vetenskapligt namn": scientific_name,
            "Artnivå": species_level,
            "Taxon-ID": safe_nested_get(
                observation,
                "taxon",
                "id"
            ),
            "Kommun": safe_nested_get(
                observation,
                "location",
                "municipality",
                "name"
            ),
            "Län": safe_nested_get(
                observation,
                "location",
                "county",
                "name"
            ),
            "Lokal": safe_nested_get(
                observation,
                "location",
                "locality"
            ),
            "Latitud": safe_nested_get(
                observation,
                "location",
                "decimalLatitude"
            ),
            "Longitud": safe_nested_get(
                observation,
                "location",
                "decimalLongitude"
            ),
            "Osäkerhet meter": safe_nested_get(
                observation,
                "location",
                "coordinateUncertaintyInMeters"
            ),
            "Antal": (
                safe_nested_get(
                    observation,
                    "occurrence",
                    "individualCount"
                )
                or safe_nested_get(
                    observation,
                    "occurrence",
                    "organismQuantity"
                )
            ),
            "Observatör": safe_nested_get(
                observation,
                "occurrence",
                "recordedBy"
            ),
            "Rapportör": safe_nested_get(
                observation,
                "occurrence",
                "reportedBy"
            ),
            "Rapporterad": safe_nested_get(
                observation,
                "occurrence",
                "reportedDate"
            ),
            "Observationstid": safe_nested_get(
                observation,
                "event",
                "startDate"
            ),
            "Artportalen-länk": safe_nested_get(
                observation,
                "occurrence",
                "url"
            ),
            "Occurrence-ID": safe_nested_get(
                observation,
                "occurrence",
                "occurrenceId"
            )
        })

    dataframe = pd.DataFrame(rows)

    if dataframe.empty:
        return dataframe

    valid_mask = dataframe.apply(
        lambda row: is_unambiguous_observation(
            row["Artnamn"],
            row["Vetenskapligt namn"]
        ),
        axis=1
    )

    dataframe = dataframe[valid_mask].copy()

    dataframe = dataframe[
        dataframe["Artnivå"].notna()
    ].copy()

    return dataframe


# ============================================================
# LÄS OCH BEARBETA MÅNX
# ============================================================

def read_month_list():
    """
    Läser MånX med calamine och bygger jämförelsenyckel
    från det vetenskapliga namnet i artkolumnen.
    """

    try:
        dataframe = pd.read_excel(
            EXCELFIL,
            engine="calamine"
        )

    except FileNotFoundError:
        print("Fel: Excel-filen hittades inte:")
        print(EXCELFIL)
        sys.exit(1)

    except ImportError:
        print("Fel: python-calamine saknas.")
        print()
        print("Installera paketet i PowerShell med:")
        print("pip install python-calamine")
        sys.exit(1)

    except Exception as error:
        print("Kunde inte läsa MånX-filen:")
        print(error)
        sys.exit(1)

    species_column = find_month_list_column(dataframe)

    dataframe = dataframe[
        dataframe[species_column].notna()
    ].copy()

    split_names = dataframe[species_column].astype(str).str.split(
        ",",
        n=1,
        expand=True
    )

    dataframe["Listans artnamn"] = split_names[0].str.strip()

    if split_names.shape[1] > 1:
        dataframe["Vetenskapligt namn"] = (
            split_names[1]
            .str.strip()
        )
    else:
        dataframe["Vetenskapligt namn"] = None

    dataframe["Artnivå"] = dataframe[
        "Vetenskapligt namn"
    ].apply(scientific_name_to_species_level)

    dataframe = dataframe[
        dataframe["Artnivå"].notna()
    ].copy()

    return dataframe, species_column


# ============================================================
# IDENTIFIERA ARTER SEDDA UNDER AKTUELL MÅNAD
# ============================================================

def get_seen_species_this_month(month_dataframe):
    """
    Returnerar vetenskapliga artnivånamn för alla arter
    markerade med X under aktuell månad.
    """

    month_names = {
        1: "Jan",
        2: "Feb",
        3: "Mar",
        4: "Apr",
        5: "Maj",
        6: "Jun",
        7: "Jul",
        8: "Aug",
        9: "Sep",
        10: "Okt",
        11: "Nov",
        12: "Dec"
    }

    current_month = month_names[datetime.now().month]

    if current_month not in month_dataframe.columns:
        raise ValueError(
            f"Månadskolumnen '{current_month}' saknas i MånX."
        )

    marked_as_seen = (
        month_dataframe[current_month]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .eq("X")
    )

    seen_species = set(
        month_dataframe.loc[
            marked_as_seen,
            "Artnivå"
        ].dropna()
    )

    return current_month, seen_species


# ============================================================
# JÄMFÖR ARTPORTALEN MOT MÅNX
# ============================================================

def find_missing_species(
    observations_dataframe,
    seen_species
):
    """
    Filtrerar fram observationer vars vetenskapliga artnivå
    inte är markerad som sedd under aktuell månad.
    """

    missing_observations = observations_dataframe[
        ~observations_dataframe["Artnivå"].isin(
            seen_species
        )
    ].copy()

    missing_observations["Observationstid"] = (
        pd.to_datetime(
            missing_observations["Observationstid"],
            errors="coerce"
        )
        .dt.tz_localize(None)
    )

    missing_observations = missing_observations.sort_values(
        by=[
            "Artnamn",
            "Observationstid",
            "Lokal"
        ],
        na_position="last"
    )

    unique_missing_species = (
        missing_observations
        .sort_values(
            by="Observationstid",
            na_position="last"
        )
        .drop_duplicates(
            subset=["Artnivå"],
            keep="last"
        )
        .sort_values(
            by="Artnamn",
            na_position="last"
        )
    )

    return missing_observations, unique_missing_species


# ============================================================
# HUVUDPROGRAM
# ============================================================

def main():
    if not VERIFY_SSL:
        urllib3.disable_warnings(
            urllib3.exceptions.InsecureRequestWarning
        )

    records = fetch_observations()

    observations = observations_to_dataframe(records)

    if observations.empty:
        print()
        print(
            "Inga entydiga fågelobservationer hittades "
            "för dagens datum i Skåne."
        )
        return

    month_list, _ = read_month_list()

    current_month, seen_species = (
        get_seen_species_this_month(month_list)
    )

    missing_observations, unique_missing_species = (
        find_missing_species(
            observations,
            seen_species
        )
    )

    # ============================================================
    # TOPP 5 LOKALER
    # ============================================================

    top_locations = (
        missing_observations
        .groupby(
            ["Lokal", "Kommun"],
            dropna=False
        )
        .agg(
            AntalNyaArter=("Artnivå", "nunique")
        )
        .reset_index()
        .sort_values(
            "AntalNyaArter",
            ascending=False
        )
        .head(5)
    )

    # ============================================================
    # SKAPA RESULTATFIL
    # ============================================================

    output_file = (
        r"C:\Users\S38102\OneDrive - E.ON"
        r"\Övrigt\Fåglar\Listor\MånX_Resultat.xlsx"
    )

    html_file = (
        r"C:\Users\S38102\OneDrive - E.ON"
        r"\Övrigt\Fåglar\Listor\MånX_Resultat.html"
    )
    html = f"""
        <html>

        <head>
            <meta charset="utf-8">

            <title>MånX Resultat</title>

            <style>

                body {{
                    font-family: Arial;
                    margin: 20px;
                }}

                h1 {{
                    color: #114477;
                }}

                table {{
                    border-collapse: collapse;
                    width: 100%;
                }}

                td, th {{
                    border: 1px solid #cccccc;
                    padding: 8px;
                }}

                th {{
                    background-color: #d9eaf7;
                }}

            </style>

        </head>

        <body>

        <h1>MånX Resultat</h1>

        <p>
        Genererad:
        {datetime.now().strftime("%Y-%m-%d %H:%M")}
        </p>

        <h2>Nya arter idag</h2>

        {unique_missing_species[
            [
                "Artnamn",
                "Kommun",
                "Lokal",
                "Observationstid"
            ]
        ].to_html(index=False)}

        <h2>Topp 5 lokaler</h2>

        {top_locations.to_html(index=False)}

        </body>

        </html>
        """
    
    with open(
        html_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(html)

    print()
    print("HTML skapad:")
    print(html_file)

    display_columns = [
        "Artnamn",
        "Vetenskapligt namn",
        "Kommun",
        "Lokal",
        "Observationstid",
        "Observatör"
    ]


    species_summary = (
        missing_observations
        .groupby(
            ["Artnamn", "Vetenskapligt namn"]
        )
        .agg(
            AntalLokaler=("Lokal", "nunique"),
            Lokaler=(
                "Lokal",
                lambda x: "; ".join(
                    sorted(
                        set(
                            str(v)
                            for v in x
                            if pd.notna(v)
                        )
                    )
                )
            )
        )
        .reset_index()
        .sort_values(
            "AntalLokaler",
            ascending=False
        )
    )

    with pd.ExcelWriter(
        output_file,
        engine="xlsxwriter"
        
    ) as writer:

        species_summary.to_excel(
            writer,
            sheet_name="Artöversikt",
            index=False
        )

        unique_missing_species[
            display_columns
        ].to_excel(
            writer,
            sheet_name="Nya arter idag",
            index=False
        )

        all_locations_columns = [
            "Artnamn",
            "Vetenskapligt namn",
            "Kommun",
            "Lokal",
            "Observationstid",
            "Observatör"
        ]

        missing_observations[
            all_locations_columns
        ].sort_values(
            [
                "Artnamn",
                "Kommun",
                "Lokal",
                "Observationstid"
            ]
        ).to_excel(
            writer,
            sheet_name="Alla lokaler",
            index=False
        )


        top_locations.to_excel(
            writer,
            sheet_name="Topp 5 lokaler",
            index=False
        )

        workbook = writer.book

        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#D9EAF7"
        })

        for sheet_name in writer.sheets:

            worksheet = writer.sheets[sheet_name]

            if sheet_name == "Artöversikt":
                columns = species_summary.columns

            elif sheet_name == "Alla lokaler":
                columns = all_locations_columns

            elif sheet_name == "Nya arter idag":
                columns = display_columns

            else:
                columns = top_locations.columns

            for col_num, value in enumerate(columns):
                worksheet.write(
                    0,
                    col_num,
                    value,
                    header_format
                )

            worksheet.autofilter(0, 0, 5000, 20)

            worksheet.freeze_panes(1, 0)

            if sheet_name == "Nya arter idag":

                worksheet.set_column("A:A", 25)
                worksheet.set_column("B:B", 35)
                worksheet.set_column("C:C", 15)
                worksheet.set_column("D:D", 45)
                worksheet.set_column("E:E", 25)
                worksheet.set_column("F:F", 40)

            else:

                worksheet.set_column("A:A", 45)
                worksheet.set_column("B:B", 20)
                worksheet.set_column("C:C", 15)

            worksheet.set_column(
                0,
                20,
                25
            )

    print()
    print("Resultatfil skapad:")
    print(output_file)

    print()
    print("Aktuell månad:", current_month)
    print(
        "Arter redan sedda denna månad:",
        len(seen_species)
    )
    print(
        "Unika arter rapporterade idag:",
        observations["Artnivå"].nunique()
    )
    print(
        "Observationer av saknade månadsarter:",
        len(missing_observations)
    )
    print(
        "Unika saknade månadsarter:",
        len(unique_missing_species)
    )

    print()
    print("Unika saknade månadsarter:")
    print()

    display_columns = [
        "Artnamn",
        "Vetenskapligt namn",
        "Kommun",
        "Lokal",
        "Observationstid",
        "Observatör"
    ]

    if unique_missing_species.empty:
        print(
            "Inga rapporterade arter saknas i "
            f"månadslistan för {current_month}."
        )
    else:
        print(
            unique_missing_species[
                display_columns
            ].to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()
