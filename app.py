import streamlit as st
import pandas as pd
from datetime import datetime

from ArtportalenScript import (
    fetch_observations,
    observations_to_dataframe,
    read_month_list,
    get_seen_species_this_month,
    find_missing_species
)

st.set_page_config(
    page_title="MånX",
    page_icon="🐦",
    layout="wide"
)

st.title("🐦 MånX")
st.caption("Saknade månadsarter i Skåne")

if st.button("🔄 Uppdatera"):

    with st.spinner("Hämtar observationer från Artportalen..."):

        records = fetch_observations()

        observations = observations_to_dataframe(
            records
        )

        month_list, _ = read_month_list()

        current_month, seen_species = (
            get_seen_species_this_month(
                month_list
            )
        )

        (
            missing_observations,
            unique_missing_species
        ) = find_missing_species(
            observations,
            seen_species
        )

        species_summary = (
            missing_observations
            .groupby(
                ["Artnamn", "Vetenskapligt namn"]
            )
            .agg(
                AntalLokaler=("Lokal", "nunique"),
                Lokaler=(
                    "Lokal",
                    lambda x: "<br>".join(
                        sorted(
                            {
                                str(v)
                                for v in x
                                if pd.notna(v)
                            }
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
        

        top_locations = (
            missing_observations
            .groupby(
                ["Lokal", "Kommun"],
                dropna=False
            )
            .agg(
                AntalNyaArter=(
                    "Artnivå",
                    "nunique"
                )
            )
            .reset_index()
            .sort_values(
                "AntalNyaArter",
                ascending=False
            )
        )

    # Nyckeltal
    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Saknade arter",
        len(unique_missing_species)
    )

    col2.metric(
        "Observationer",
        len(missing_observations)
    )

    col3.metric(
        "Kontrollerad månad",
        current_month
    )

    # Flikar
    tab1, tab2, tab3 = st.tabs(
        [
            "🐦 Artöversikt",
            "📍 Alla lokaler",
            "⭐ Topp 5 lokaler"
        ]
    )
    
    with tab1:

        st.subheader(
            "Saknade månadsarter"
        )

        st.markdown(
            species_summary.to_html(
                escape=False,
                index=False
            ),
            unsafe_allow_html=True
        )

    with tab2:

        st.subheader(
            "Alla lokaler"
        )

        df_visning = (
            missing_observations[
                [
                    "Artnamn",
                    "Kommun",
                    "Lokal",
                    "Observationstid",
                    "Observatör"
                ]
            ]
            .sort_values(
                [
                    "Artnamn",
                    "Kommun",
                    "Lokal"
                ]
            )
            .reset_index(drop=True)
        )

        st.dataframe(
            df_visning,
            use_container_width=True
        )

    with tab3:

        st.subheader(
            "Topplokaler"
        )

        st.dataframe(
            top_locations.head(20),
            use_container_width=True
        )

    st.success(
        f"Senast uppdaterad: "
        f"{datetime.now():%Y-%m-%d %H:%M}"
    )