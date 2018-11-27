#!/usr/bin/env python3
# Generates two JSON files: one for a rank plot and one for a sample
# scatterplot of log ratios.
#
# A lot of the code for processing input data in this file was based on code
# by Jamie Morton, some of which is now located in ipynb/Figure3.ipynb in
# https://github.com/knightlab-analyses/reference-frames.
#
# NOTE: For some reason, the sample plot JSON generated here differs somehow
# from the JSON generated by the notebook I was testing this with. Seems to
# just be an ordering issue, but a TODO is to write code that validates that
# that is the case (and it isn't actually messing up any of the data/metadata).

import numpy as np
import pandas as pd
from biom import load_table
import altair as alt
import json

# TODO use click to specify output JSON filenames, input data sources, default
# selected taxa?, etc

print("Processing input files...")
##### Load input files: ranks, BIOM table, metadata, select microbes
# The code in this section is taken from the notebook's start.
beta = pd.read_csv('byrd_inputs/beta.csv', index_col=0)
table = load_table('byrd_inputs/byrd_skin_table.biom').to_dataframe().to_dense().T
metadata = pd.read_table('byrd_inputs/byrd_metadata.txt', index_col=0)

# Exclude certain samples from the plots, if requested.
# TODO make this an option from the command line
sample_exclude = set(['MET0852', 'MET1504'])
metadata = metadata.loc[set(metadata.index) - sample_exclude]

# Get stuff ready for the rank plot
coefs = beta["C(Timepoint, Treatment('F'))[T.PF]"].sort_values()
x = np.arange(coefs.shape[0])

#### 1. Create Altair version of log(PostFlare/Flare) + K rank plot
print("Creating rank plot...")

# Define "classification." We'll use this list to determine the color each
# rank should be.

# Copied from later on in the Jupyter Notebook
numerator = []
denominator = []
# Check for common microbes between top and bottom of log ratio: if detected,
# classify them as "Both."
# This code is provided here for illustrative purposes and for future reference
# (in case we want to display an "initial" log ratio).
#set_top = set(numerator)
#set_bot = set(denominator)
#set_both = set_top & set_bot
#set_top_excl = set_top - set_bot
#set_bot_excl = set_bot - set_top

# based on definition of filtered_beta earlier in the original notebook
classification = pd.Series(index=coefs.index).fillna("None")
#classification[set_top_excl] = "Numerator"
#classification[set_bot_excl] = "Denominator"
#classification[set_both] = "Both"
# x is a numpy.ndarray; coefs is a pandas Series
postFlareRanksData = pd.DataFrame({'x': x, 'coefs': coefs, "classification": classification})

# The default size value of mark_bar() causes an apparent offset in the interval selection.
# Setting size to 1.0 fixes this; using mark_rule() also fixes this, probably because the lines in
# rule charts are just lines with a width of 1.0.
postflare_rank_chart = alt.Chart(
        postFlareRanksData.reset_index(),
        title="Ranks"
).mark_bar().encode(
    x=alt.X('x', title="Species", type="quantitative"),
    y=alt.Y('coefs', title="log(PostFlare / Flare) + K", type="quantitative"),
    color=alt.Color("classification",
        scale=alt.Scale(
            domain=["None", "Numerator", "Denominator", "Both"],
            range=["#e0e0e0", "#f00", "#00f", "#949"]
        )
    ),
    size=alt.value(1.0),
    tooltip=["x", "coefs", "classification", "index"]
).configure_axis(
    # Done in order to differentiate "None"-classification taxa from grid lines
    # (an imperfect solution to the problem mentioned in the NOTE below)
    gridOpacity=0.35
).interactive()

#### 2. Create Altair version of sample scatterplot data
print("Creating sample log ratio scatterplot...")

# Since we don't bother setting a default log ratio, we set the balance for
# every sample to NaN so that Altair will filter them out (producing an empty
# scatterplot by default, which makes sense).
#
# From the reference-frames notebook
#top = table[numerator].sum(axis=1)
#bot = table[denominator].sum(axis=1)
#balance = np.log(top) - np.log(bot)
balance = pd.Series(index=table.index).fillna(float('nan'))
data = pd.DataFrame({'balance': balance}, index=table.index)
data = pd.merge(data, metadata, left_index=True, right_index=True)

# Construct unified DataFrame, combining our "data" DataFrame with the "table" variable
# (in order to associate each sample with its corresponding abundances)
sample_metadata_and_abundances = pd.merge(data, table, left_index=True, right_index=True)

# "Reset the index" -- make the sample IDs a column (on the leftmost side)
sample_metadata_and_abundances.reset_index(inplace=True)

# Make note of the column names in the unified data frame.
# This constructs a dictionary mapping the column names to their integer indices
# (just the range of [0, 3084]). Similarly to smaa_i2sid above, we'll preserve
# this in the JSON.
smaa_cols = sample_metadata_and_abundances.columns
smaa_cn2si = {}
int_smaa_col_names = [str(i) for i in range(len(smaa_cols))]
for j in int_smaa_col_names:
    # (Altair doesn't seem to like accepting ints as column names, so we
    # mostly use the new column names as strings when we can.)
    smaa_cn2si[smaa_cols[int(j)]] = j

# Now, we replace column names (which include upwards of 3,000 lineages) with just the
# integer index from before.
#
# This saves *a lot* of space in the JSON file for the sample plot, since each column name is
# referenced once for each sample (and 50 samples * (~3000 taxonomy IDs ) * (~50 characters per ID)
# comes out to 7.5 MB, which is an underestimate).
sample_metadata_and_abundances.columns = int_smaa_col_names

# Create sample plot.
sample_logratio_chart = alt.Chart(
    sample_metadata_and_abundances,
    title="Log Ratio of Abundances in Samples"
).mark_circle().encode(
    alt.X(smaa_cn2si["Objective SCORAD"], title="SCORAD"),
    alt.Y(smaa_cn2si["balance"], title="log(Numerator / Denominator)"),
    color=alt.Color(
        smaa_cn2si["Timepoint"],
        title="Time: Baseline / Flare / Post-Flare",
        scale=alt.Scale(
            domain=["B", "PF", "F"],
            range=["#00c", "#0c0", "#c00"]
        )
    ),
    tooltip=[smaa_cn2si["index"]]
)#.interactive()

# Save JSON for sample plot (throwing in the column identifying dict from earlier).
print("Saving plot JSON files...")
sample_logratio_chart_json = sample_logratio_chart.to_dict()
sample_logratio_chart_json["datasets"]["col_names"] = smaa_cn2si
# For reference: https://stackoverflow.com/a/12309296
# Write the (modified to contain col_names as a dataset) JSON to a file.
# (This path will need to be changed for other systems, of course.)
with open("sample_logratio_plot.json", "w") as jfile:
    json.dump(sample_logratio_chart_json, jfile)

# Save JSON for the rank plot.
postflare_rank_chart.save("rank_plot.json")
print("Done.")
