import os
import sys
import pandas as pd
import streamlit as st
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.misc import ensure_csv_schema
from scripts.run_batch import process_row
from clients import lead_cache, scrape_cache
from scripts.run_batch import redraft_email

from dotenv import load_dotenv
load_dotenv()

# ------------------------------------------------------------

st.title("Leads Information Sheet", text_alignment="center")
st.set_page_config(layout="wide")


if "lead_results" not in st.session_state:
    st.session_state.lead_results = []
if "running" not in st.session_state:
    st.session_state.running = False

# ----------------------------------------------------------------------------

def _full_address_of(row) -> str:
    return ", ".join([
        str(row["Property Address"]),
        str(row["City"]),
        str(row["State"]),
        str(row["Country"]),
    ])


def _bucket_color(bucket: str) -> str:
    return {
        "High":         "green",
        "Medium":       "orange",
        "Low":          "blue",
        "Needs Review": "red",
    }.get(bucket, "gray")


def _render_lead_card(result: dict) -> None:
    li = result["lead_info"]
    score  = li["lead_score"]
    bucket = li["priority_bucket"]
    color  = _bucket_color(bucket)
    feats  = result["features"]
    email  = result["outreach_email"]

    score_percentage = score * 100

    with st.container(border=True):
        top = st.columns([4, 1])
        top[0].markdown(
            f"### {result['property_name']}  "
            f":{color}[**{bucket}**]"
        )
        top[0].caption(result["full_address"])
        top[1].metric("Lead score", f"{score_percentage:.2f}%")

        st.progress(min(max(score, 0.0), 1.0))

        cols = st.columns(5)
        for col, (k, v) in zip(cols, li["score_breakdown"].items()):
            col.metric(k.replace("_", " ").title(), f"{v:.2f}")

        st.markdown("**Why this score**")
        for r in li.get("reason_codes", []) or ["(no reasons generated)"]:
            st.markdown(f"- {r}")

        kpi = st.columns(4)
        kpi[0].metric("Units",          feats.get("unit_count")      or "—")
        kpi[1].metric("Active listings", feats.get("active_listings") or "—")
        kpi[2].metric("Reviews",        feats.get("review_count")    or "—")
        kpi[3].metric("Property Managed By",        feats.get("manager")         or "—")


        # Render the email
        st.markdown("**Draft outreach email**")
        if email:
            with st.container(border=True):
                st.markdown(f"**Subject:** {email['subject']}")
                st.markdown("---")
                # st.markdown handles paragraph breaks on '\n\n'.
                # Use a copy-friendly fallback below if needed.
                st.markdown(email["body"])
            ctrl = st.columns([1, 1, 4])
            regen_key = f"regen_{result['property_name']}_{result['full_address']}"
            if ctrl[0].button("Regenerate", key=regen_key):
                with st.spinner("Re-drafting…"):
                    new_email = redraft_email(pd.Series(result["row"]))
                if new_email:
                    result["outreach_email"] = new_email   # mutates session_state ref
                    st.toast("Email regenerated.")
                else:
                    st.error(
                        "Could not redraft email — check that features are "
                        "cached for this row."
                    )
                st.rerun()
            with ctrl[1].popover("Copy"):
                st.code(
                    f"Subject: {email['subject']}\n\n{email['body']}",
                    language=None,
                )
            drafted_at = email.get("drafted_at")
            if drafted_at:
                ctrl[2].caption(f"Drafted {drafted_at}")
        else:
            st.caption("(no email drafted yet. Click Generate Data on this row)")
 

        with st.expander("Raw Features", expanded=False):
            st.json(feats, expanded=False)


        with st.expander("Raw Lead Information", expanded=False):
            st.json(li, expanded=False)


# ----------------------------------------------------------------------------
# create a form for the SDR to input the new lead information
with st.sidebar.form("new_lead_form", clear_on_submit=True):
    st.write("Please fill this form to create a new lead.")
    # Lead's name and email
    name = st.text_input("Name")
    email = st.text_input("Email")
    property_name = st.text_input("Property Name")

    # Building they manage
    property_address = st.text_input("Address")
    city = st.text_input("City")
    state = st.text_input("State")
    zipcode = st.text_input("Zipcode")
    country = st.text_input("Country")

    submitted = st.form_submit_button("Submit")

    if submitted:
        if name and email and property_address and city and state and country:

            ensure_csv_schema('data/sample_input.csv')

            new_row = pd.DataFrame([{
                "Name": name,
                "Email": email,
                "Property Name": property_name,
                "Property Address": property_address,
                "City": city,
                "State": state,
                "Zipcode": zipcode,
                "Country": country}
            ])

            new_row.to_csv("data/sample_input.csv", mode='a', header=False, index=False)
            st.success("New lead created successfully!")
            st.rerun()
        else:
            st.error("Error:Please fill out all fields.")
            

if os.path.exists("data/sample_input.csv"):
    # show the list of leads in a table
    df = pd.read_csv("data/sample_input.csv", dtype={"Zipcode": str})
    df["Zipcode"] = (
        df["Zipcode"]
        .fillna("")
        .astype("string")
        .str.replace(r"\.0$", "", regex=True)  # cleanup old float-looking zips like 30326.0
    )
    df_with_selection = df.copy()
    df_with_selection.insert(0, "Run",     False)
    df_with_selection.insert(1, "Refresh", False)
    df_with_selection["Delete"] = False

    #df_with_selection.insert(8, "Delete", False)

    # ========= Zip Code Editing Section =========

    editable_cols = ["Run", "Refresh", "Delete", "Zipcode"]  # only this one is editable
    disabled_cols = [c for c in df_with_selection.columns if c not in editable_cols]

    edited_df = st.data_editor(
        df_with_selection,
        hide_index=True,
        width="stretch",
        disabled=disabled_cols,
        column_config={
            "Refresh": st.column_config.CheckboxColumn(
                "Run",
                help=(
                    "Process this row when you click Generate Lead. "
                    "Uses cached results if available."
                ),
                default=False,
            ),
            "Refresh": st.column_config.CheckboxColumn(
                "Refresh",
                help=(
                    "Process this row AND bypass the LLM cache (forces fresh "
                    "LLM call). Firecrawl scrape cache is preserved."
                ),
                default=False,
            ),
            "Delete": st.column_config.CheckboxColumn(default=False),
            "Zipcode": st.column_config.TextColumn(
                "Zipcode",
                help="Enter 5-digit ZIP code",
                max_chars=5,
            ),
        },
    )

    # enable deletion of selected rows in the csv file by adding a delete button to the table
    if st.button("Delete selections"):
        rows_to_delete = edited_df["Delete"]
        if rows_to_delete.any():
            updated_df = df.loc[~rows_to_delete].reset_index(drop=True)
            updated_df.to_csv("data/sample_input.csv", index=False)
            st.success(f"Deleted {int(rows_to_delete.sum())} lead(s).")
            st.rerun()
        else:
            st.warning("Select at least one lead to delete.")


    if st.button("Save zipcode edits"):
        zip_series = edited_df["Zipcode"].astype(str).str.strip()

        # keep digits only, then enforce 5 chars
        zip_series = zip_series.str.replace(r"\D", "", regex=True)
        valid = zip_series.str.fullmatch(r"\d{5}") | (zip_series == "")

        if not valid.all():
            st.error("ZIP must be 5 digits (or blank).")
        else:
            df["Zipcode"] = zip_series
            df.to_csv("data/sample_input.csv", index=False)
            st.success("Zipcodes updated.")
            st.rerun()
    


# ----------------------------------------------------------------------------

st.divider()
st.subheader("Generate lead intelligence")

c1, c2 = st.columns([3, 2])
with c1:
    n_run     = int(edited_df["Run"].fillna(False).sum())
    n_refresh = int(edited_df["Refresh"].fillna(False).sum())
    n_total   = len(edited_df)
    st.caption(
        f"**{n_total}** rows · "
        f"**{n_run}** to run · **{n_refresh}** to refresh"
    )


with c2:
    s1 = scrape_cache.stats()
    s2 = lead_cache.stats()
    st.caption(
        f"Scrape cache: **{s1['scrapes_cached']}** pages · "
        f"Feature cache: **{s2['feature_rows_cached']}** properties"
    )


if st.button("Generate Lead", type="primary", disabled=st.session_state.running):
    selected = edited_df[
        edited_df["Run"].fillna(False) | edited_df["Refresh"].fillna(False)
    ].copy()


    if selected.empty:
        st.warning(
            "Select at least one row (tick **Run** or **Refresh**) "
            "before clicking Generate Data."
        )
    else:
        st.session_state.lead_results = []
        st.session_state.running = True


        # 1. Invalidate lead_cache for rows ticked under Refresh.
        invalidated = 0
        for _, r in selected.iterrows():
            if bool(r.get("Refresh")):
                lead_cache.invalidate(r["Property Name"], _full_address_of(r))
                invalidated += 1
        if invalidated:
            st.toast(f"Invalidated {invalidated} cached row(s).")


        # 2. Process ONLY the selected rows.
        total    = len(selected)
        progress = st.progress(0.0, text="Starting…")
        latest   = st.empty()

        try:
            for i, (_, row) in enumerate(selected.iterrows(), start=1):
                result = process_row(row, force_fresh_llm=False)
                st.session_state.lead_results.append(result)
                progress.progress(
                    i / max(total, 1),
                    text=f"Processed {i}/{total} — {result['property_name']}",
                )
                latest.info(
                    f"`{result['property_name']}` → "
                    f"score **{result['lead_info']['lead_score']:.2f}** "
                    f"({result['lead_info']['priority_bucket']})"
                )
        finally:
            st.session_state.running = False
            progress.empty()
            latest.empty()


        st.success(f"Done — {len(st.session_state.lead_results)} lead(s) processed.")
        st.rerun()


# -------- results panel --------
if st.session_state.lead_results:
    st.divider()
    st.subheader("Lead intelligence")

    sort_mode = st.radio(
        "Sort by",
        ["Score (high → low)", "Score (low → high)", "Property name"],
        horizontal=True,
        index=0,
    )

    results = list(st.session_state.lead_results)
    if sort_mode == "Score (high → low)":
        results.sort(key=lambda r: r["lead_info"]["lead_score"], reverse=True)
    elif sort_mode == "Score (low → high)":
        results.sort(key=lambda r: r["lead_info"]["lead_score"])
    else:
        results.sort(key=lambda r: r["property_name"].lower())

    for r in results:
        _render_lead_card(r)
    
